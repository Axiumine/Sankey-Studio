"""Process side of the hook gate: the environment of a check, the runner seam, signals.

``Runner`` is the seam the tests replace; ``SubprocessRunner`` is the real one. A child gets its
own session (``start_new_session``), so ``make``, pytest, browsers and docker clients form one
process group that SIGTERM, SIGINT and SIGHUP of the gate take down as a whole before the gate
exits with ``128 + signal``: the group gets SIGTERM, up to ``GRACE_SECONDS`` to end (not only the
leader: a docker client or a browser driver needs a moment to stop what it started), then SIGKILL.
This replaces the bash ``cmd & wait $!`` plus ``trap`` idiom: Python runs its handler as soon as
the blocking read is interrupted, so nothing is deferred until the child ends.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, Final, Protocol, TextIO

from scripts.githook_plan import MONGO_ENV

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

FORWARDED: Final = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
GRACE_SECONDS: Final = 10.0
GROUP_POLL_SECONDS: Final = 0.05
READ_SIZE: Final = 65536
POLL_SECONDS: Final = 0.5
#: Variables dropped from every child: they could weaken or redirect a check.
DROPPED_ENV: Final = ("PYTEST_ADDOPTS", MONGO_ENV)


class GateInterruptedError(Exception):
    """The gate received a signal; ``code`` is the exit status to use (128 + signal)."""

    def __init__(self, signum: int) -> None:
        super().__init__(f"interrupted by signal {signum}")
        self.code = 128 + signum


@dataclass(frozen=True, slots=True)
class Command:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]


class Runner(Protocol):
    def run(self, command: Command, log: BinaryIO, echo: TextIO) -> int:
        """Run to the end, tee the output to ``log`` and ``echo``, return the exit code."""
        ...


def build_child_env(
    base: Mapping[str, str], local_git_vars: tuple[str, ...], home: Path
) -> dict[str, str]:
    """Environment of a check: git's local variables gone, uv locked, ``~/.local/bin`` on PATH."""
    env = {k: v for k, v in base.items() if k not in local_git_vars and k not in DROPPED_ENV}
    local_bin = str(home / ".local" / "bin")
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    env["PATH"] = os.pathsep.join([local_bin, *(p for p in parts if p != local_bin)])
    env["UV_LOCKED"] = "1"
    return env


def exit_status(returncode: int) -> int:
    """A shell-style status: a child killed by signal N counts as 128 + N."""
    return returncode if returncode >= 0 else 128 - returncode


def kill_group(pgid: int, signum: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signum)


def group_alive(pgid: int) -> bool:
    """True while a process of the group exists (signal-0 probe; one we cannot signal is gone)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError, PermissionError:
        return False
    return True


def stop_group(proc: subprocess.Popen[bytes]) -> None:
    """TERM the child's group, give the whole group ``GRACE_SECONDS`` to end, KILL what is left.

    The leader (``make``, a shell) usually dies on SIGTERM at once while its descendants still
    clean up; they get the rest of the grace, not the instant the leader is gone.
    """
    deadline = time.monotonic() + GRACE_SECONDS
    kill_group(proc.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=GRACE_SECONDS)
    while group_alive(proc.pid) and time.monotonic() < deadline:
        time.sleep(GROUP_POLL_SECONDS)
    kill_group(proc.pid, signal.SIGKILL)
    proc.wait()


@contextlib.contextmanager
def forward_signals(proc: subprocess.Popen[bytes]) -> Iterator[None]:
    """While active, a termination signal stops the child group and raises the interrupt."""

    def handler(signum: int, _frame: object) -> None:
        stop_group(proc)
        raise GateInterruptedError(signum)

    previous = {sig: signal.signal(sig, handler) for sig in FORWARDED}
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


def raise_interrupt(signum: int, _frame: object) -> None:
    raise GateInterruptedError(signum)


def install_gate_signals() -> None:
    """Between children a termination signal still unwinds (Mongo gets stopped, locks freed)."""
    for sig in FORWARDED:
        signal.signal(sig, raise_interrupt)


class SubprocessRunner:
    """Runs a command in its own session and streams its merged output."""

    def run(self, command: Command, log: BinaryIO, echo: TextIO) -> int:
        proc = subprocess.Popen(  # noqa: S603 - argv list built by the gate, no shell
            list(command.argv),
            cwd=command.cwd,
            env=dict(command.env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        stdout = proc.stdout
        assert stdout is not None
        try:
            with forward_signals(proc):
                self._pump(proc, log, echo)
                code = proc.wait()
        finally:
            kill_group(proc.pid, signal.SIGKILL)
            proc.wait()
            stdout.close()
        return exit_status(code)

    @staticmethod
    def _pump(proc: subprocess.Popen[bytes], log: BinaryIO, echo: TextIO) -> None:
        """Copy output until EOF, or until the leader is gone and the pipe is drained."""
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        while True:
            ready, _, _ = select.select([fd], [], [], POLL_SECONDS)
            if ready:
                data = os.read(fd, READ_SIZE)
                if not data:
                    return
                log.write(data)
                log.flush()
                echo.write(data.decode("utf-8", "replace"))
                echo.flush()
            elif proc.poll() is not None:
                return
