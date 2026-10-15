"""Process side of the gate (scripts/githook_runner.py): child environment, signals, the runner."""

from __future__ import annotations

import io
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from scripts import githook_runner as runner

from tests.githook_support import Case, alive, case_id

if TYPE_CHECKING:
    from collections.abc import Buffer

HOME = Path("/home/dev")
LOCAL_BIN = "/home/dev/.local/bin"
LOCAL_VARS = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")


# --------------------------------------------------------------------------- build_child_env


def test_the_child_env_loses_git_local_variables_and_the_two_weakening_variables() -> None:
    base = {
        "GIT_DIR": "/r/.git",
        "GIT_INDEX_FILE": "/r/.git/index.lock",
        "GIT_WORK_TREE": "/r",
        "PYTEST_ADDOPTS": "-x --no-cov",
        "SANKEY_TEST_MONGO_URI": "mongodb://elsewhere",
        "SANKEY_MONGO_URI": "mongodb://kept",
        "HOME": "/home/dev",
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin",
    }
    env = runner.build_child_env(base, LOCAL_VARS, HOME)
    assert sorted(env) == ["HOME", "LANG", "PATH", "SANKEY_MONGO_URI", "UV_LOCKED"]
    assert env["SANKEY_MONGO_URI"] == "mongodb://kept"
    assert runner.DROPPED_ENV == ("PYTEST_ADDOPTS", "SANKEY_TEST_MONGO_URI")


def test_variables_git_does_not_call_local_stay() -> None:
    base = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "x", "PATH": "/usr/bin"}
    env = runner.build_child_env(base, LOCAL_VARS, HOME)
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_AUTHOR_NAME"] == "x"


PATHS = [
    Case("/usr/bin:/bin", f"{LOCAL_BIN}:/usr/bin:/bin", "prepended"),
    Case(f"/usr/bin:{LOCAL_BIN}:/bin", f"{LOCAL_BIN}:/usr/bin:/bin", "moved to the front once"),
    Case(f"{LOCAL_BIN}:/usr/bin", f"{LOCAL_BIN}:/usr/bin", "already first"),
    Case(f"{LOCAL_BIN}:/usr/bin:{LOCAL_BIN}", f"{LOCAL_BIN}:/usr/bin", "listed twice"),
    Case("/usr/bin::/bin:", f"{LOCAL_BIN}:/usr/bin:/bin", "empty entries dropped"),
    Case("", LOCAL_BIN, "empty path"),
]


@pytest.mark.parametrize("case", PATHS, ids=case_id)
def test_local_bin_comes_first_on_the_path_exactly_once(case: Case[str, str]) -> None:
    env = runner.build_child_env({"PATH": case.given}, (), HOME)
    assert env["PATH"] == case.expected


def test_a_missing_path_still_gets_local_bin() -> None:
    assert runner.build_child_env({}, (), HOME)["PATH"] == LOCAL_BIN


@pytest.mark.parametrize("value", [None, "0", "", "yes"])
def test_uv_is_always_locked(value: str | None) -> None:
    base = {} if value is None else {"UV_LOCKED": value}
    assert runner.build_child_env(base, (), HOME)["UV_LOCKED"] == "1"


def test_building_the_env_does_not_change_its_input() -> None:
    base = {"GIT_DIR": "x", "PATH": "/usr/bin"}
    runner.build_child_env(base, LOCAL_VARS, HOME)
    assert base == {"GIT_DIR": "x", "PATH": "/usr/bin"}


# --------------------------------------------------------------------------- exit codes


STATUSES = [
    Case(0, 0),
    Case(1, 1),
    Case(3, 3),
    Case(130, 130),
    Case(-1, 129),
    Case(-2, 130),
    Case(-9, 137),
    Case(-15, 143),
]


@pytest.mark.parametrize("case", STATUSES, ids=case_id)
def test_a_child_killed_by_signal_n_counts_as_128_plus_n(case: Case[int, int]) -> None:
    assert runner.exit_status(case.given) == case.expected


@pytest.mark.parametrize("signum", [1, 2, 15])
def test_the_interrupt_carries_the_shell_style_exit_code(signum: int) -> None:
    stop = runner.GateInterruptedError(signum)
    assert stop.code == 128 + signum
    assert str(stop) == f"interrupted by signal {signum}"


# --------------------------------------------------------------------------- process groups


def sleeper() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.PIPE,
    )


def test_kill_group_ends_the_whole_group() -> None:
    with sleeper() as proc:
        runner.kill_group(proc.pid, signal.SIGKILL)
        assert proc.wait(timeout=10) == -signal.SIGKILL


def test_kill_group_ignores_a_group_that_is_gone() -> None:
    with subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True) as proc:
        proc.wait(timeout=30)
    runner.kill_group(proc.pid, signal.SIGKILL)


def test_kill_group_ignores_a_group_it_may_not_signal() -> None:
    runner.kill_group(1, 0)


def test_stop_group_terminates_politely_first() -> None:
    with sleeper() as proc:
        runner.stop_group(proc)
        assert proc.returncode == -signal.SIGTERM


def test_stop_group_kills_a_child_that_ignores_terminate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "GRACE_SECONDS", 0.3)
    code = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "print('up', flush=True); time.sleep(60)"
    )
    with subprocess.Popen(  # noqa: S603 - fixed argv, a child that ignores SIGTERM
        [sys.executable, "-c", code], start_new_session=True, stdout=subprocess.PIPE
    ) as proc:
        assert proc.stdout is not None
        assert proc.stdout.readline() == b"up\n"
        runner.stop_group(proc)
        assert proc.returncode == -signal.SIGKILL


# --------------------------------------------------------------------------- signal handlers


def test_forward_signals_stops_the_child_and_raises_the_interrupt() -> None:
    with sleeper() as proc:
        with pytest.raises(runner.GateInterruptedError) as caught, runner.forward_signals(proc):
            os.kill(os.getpid(), signal.SIGTERM)
        assert caught.value.code == 128 + signal.SIGTERM
        assert proc.returncode == -signal.SIGTERM


@pytest.mark.parametrize("signum", runner.FORWARDED, ids=lambda s: s.name)
def test_every_termination_signal_is_forwarded(signum: signal.Signals) -> None:
    with sleeper() as proc:
        with pytest.raises(runner.GateInterruptedError) as caught, runner.forward_signals(proc):
            os.kill(os.getpid(), signum)
        assert caught.value.code == 128 + signum
        assert proc.returncode == -signal.SIGTERM


def test_forward_signals_restores_the_previous_handlers() -> None:
    before = {sig: signal.getsignal(sig) for sig in runner.FORWARDED}
    with sleeper() as proc:
        with runner.forward_signals(proc):
            assert all(signal.getsignal(sig) is not before[sig] for sig in runner.FORWARDED)
        assert {sig: signal.getsignal(sig) for sig in runner.FORWARDED} == before
        proc.kill()


def test_forward_signals_restores_the_handlers_when_the_body_raises() -> None:
    before = signal.getsignal(signal.SIGTERM)
    with sleeper() as proc:
        with pytest.raises(RuntimeError, match="boom"), runner.forward_signals(proc):
            raise RuntimeError("boom")
        assert signal.getsignal(signal.SIGTERM) == before
        proc.kill()


def test_raise_interrupt_raises_with_the_signal_number() -> None:
    with pytest.raises(runner.GateInterruptedError) as caught:
        runner.raise_interrupt(signal.SIGHUP, None)
    assert caught.value.code == 128 + signal.SIGHUP


def test_the_gate_unwinds_on_a_signal_between_two_children() -> None:
    before = {sig: signal.getsignal(sig) for sig in runner.FORWARDED}
    try:
        runner.install_gate_signals()
        assert all(signal.getsignal(sig) is runner.raise_interrupt for sig in runner.FORWARDED)
        with pytest.raises(runner.GateInterruptedError) as caught:
            os.kill(os.getpid(), signal.SIGINT)
        assert caught.value.code == 128 + signal.SIGINT
    finally:
        for sig, old in before.items():
            signal.signal(sig, old)


# --------------------------------------------------------------------------- SubprocessRunner


def command(
    code: str, env: dict[str, str] | None = None, cwd: Path | None = None
) -> runner.Command:
    full_env = dict(os.environ) if env is None else env
    return runner.Command((sys.executable, "-c", code), cwd or Path.cwd(), full_env)


def run(cmd: runner.Command) -> tuple[int, bytes, str]:
    log, echo = io.BytesIO(), io.StringIO()
    code = runner.SubprocessRunner().run(cmd, log, echo)
    return code, log.getvalue(), echo.getvalue()


def test_the_output_goes_to_the_log_and_to_the_echo() -> None:
    code, log, echo = run(command("print('hello'); print('world')"))
    assert (code, log, echo) == (0, b"hello\nworld\n", "hello\nworld\n")


def test_standard_error_is_merged_into_the_same_stream() -> None:
    code, log, echo = run(
        command("import sys; print('out', flush=True); print('err', file=sys.stderr)")
    )
    assert code == 0
    assert log.splitlines() == [b"out", b"err"]
    assert echo == log.decode()


def test_output_that_is_not_utf8_is_logged_exactly_and_echoed_with_replacement() -> None:
    code, log, echo = run(command("import sys; sys.stdout.buffer.write(b'a\\xffb\\n')"))
    assert (code, log, echo) == (0, b"a\xffb\n", "a�b\n")


def test_a_large_output_arrives_complete() -> None:
    code, log, echo = run(command("print('x' * 100 + '\\n' + 'y' * 200000)"))
    assert code == 0
    assert len(log) == 101 + 200001
    assert echo == log.decode()


@pytest.mark.parametrize("status", [1, 2, 3, 42, 255])
def test_the_exit_code_of_the_child_is_returned(status: int) -> None:
    assert run(command(f"import sys; sys.exit({status})"))[0] == status


def test_a_child_killed_by_a_signal_gives_128_plus_the_signal() -> None:
    code = "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
    assert run(command(code))[0] == 128 + signal.SIGKILL


def test_the_child_gets_the_given_environment_and_does_not_inherit_ours(tmp_path: Path) -> None:
    code = "import os; print(os.environ['MARK'], os.environ.get('HOME'), os.environ.get('USER'))"
    env = {"MARK": "kept", "PATH": os.environ["PATH"]}
    _, log, _ = run(command(code, env, tmp_path))
    assert log == b"kept None None\n"


def test_the_child_runs_in_the_given_directory(tmp_path: Path) -> None:
    _, log, _ = run(command("import os; print(os.getcwd())", cwd=tmp_path))
    assert Path(log.decode().strip()).resolve() == tmp_path.resolve()


def test_the_child_reads_an_empty_standard_input() -> None:
    _, log, _ = run(command("import sys; print(repr(sys.stdin.read()))"))
    assert log == b"''\n"


def test_the_child_leads_its_own_session_so_one_signal_reaches_its_whole_group() -> None:
    _, log, _ = run(
        command("import os; print(os.getsid(0) == os.getpid(), os.getpgrp() == os.getpid())")
    )
    assert log == b"True True\n"


def test_a_grandchild_that_keeps_the_pipe_open_does_not_hang_the_run_and_is_killed() -> None:
    code = "import subprocess; p = subprocess.Popen(['sleep', '60']); print(p.pid, flush=True)"
    status, log, _ = run(command(code))
    assert status == 0
    pid = int(log.split()[0])
    deadline = time.monotonic() + 10
    while alive(pid) and time.monotonic() < deadline:
        pass
    assert not alive(pid)


class BrokenLog(io.BytesIO):
    def write(self, _data: Buffer, /) -> int:
        raise OSError("disk full")


def test_an_error_while_copying_the_output_still_kills_and_reaps_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def recording(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        proc: subprocess.Popen[bytes] = real_popen(*args, **kwargs)
        started.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", recording)
    cmd = command("import time; print('up', flush=True); time.sleep(30)")
    with pytest.raises(OSError, match="disk full"):
        runner.SubprocessRunner().run(cmd, BrokenLog(), io.StringIO())
    (proc,) = started
    assert proc.returncode == -signal.SIGKILL
    assert proc.stdout is not None
    assert proc.stdout.closed


class FlushCounter(io.BytesIO):
    flushes = 0

    def flush(self) -> None:
        self.flushes += 1
        super().flush()


class TextFlushCounter(io.StringIO):
    flushes = 0

    def flush(self) -> None:
        self.flushes += 1
        super().flush()


def test_the_log_and_the_echo_are_flushed_as_the_output_arrives() -> None:
    log, echo = FlushCounter(), TextFlushCounter()
    cmd = command("print('one', flush=True); print('two')")
    assert runner.SubprocessRunner().run(cmd, log, echo) == 0
    assert log.flushes >= 1
    assert echo.flushes >= 1


HANDSHAKE_CHILD = (
    "import os, sys, time\n"
    "first, second = sys.argv[1:3]\n"
    "end = time.monotonic() + 30\n"
    "while not os.path.exists(first) and time.monotonic() < end:\n"
    "    pass\n"
    "print('go', flush=True)\n"
    "while not os.path.exists(second) and time.monotonic() < end:\n"
    "    pass\n"
)


class TouchOnWrite(io.StringIO):
    """An echo that creates a file when output arrives (it releases the child)."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def write(self, text: str, /) -> int:
        self.path.touch()
        return super().write(text)


def test_a_quiet_moment_while_the_child_runs_does_not_end_the_copy_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    real_select = select.select
    waits: list[float] = []

    def quiet_first_time(
        rlist: list[int], wlist: list[int], xlist: list[int], timeout: float
    ) -> tuple[list[int], list[int], list[int]]:
        waits.append(timeout)
        if len(waits) == 1:
            first.touch()
            return [], [], []
        return real_select(rlist, wlist, xlist, timeout)

    monkeypatch.setattr(select, "select", quiet_first_time)
    cmd = runner.Command(
        (sys.executable, "-c", HANDSHAKE_CHILD, str(first), str(second)), tmp_path, dict(os.environ)
    )
    log, echo = io.BytesIO(), TouchOnWrite(second)
    assert runner.SubprocessRunner().run(cmd, log, echo) == 0
    assert (log.getvalue(), echo.getvalue()) == (b"go\n", "go\n")
    assert len(waits) >= 2
    assert set(waits) == {runner.POLL_SECONDS}


class SignalOnFirstWrite(io.StringIO):
    """An echo that sends SIGTERM to the gate when the first output chunk arrives."""

    sent = False

    def write(self, text: str, /) -> int:
        if not self.sent:
            self.sent = True
            os.kill(os.getpid(), signal.SIGTERM)
        return super().write(text)


def test_a_signal_while_a_child_runs_stops_the_child_and_unwinds_the_run() -> None:
    cmd = command("import time; print('up', flush=True); time.sleep(60)")
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(runner.GateInterruptedError) as caught:
        runner.SubprocessRunner().run(cmd, io.BytesIO(), SignalOnFirstWrite())
    assert caught.value.code == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) == before


def test_a_command_is_a_value_object() -> None:
    cmd = runner.Command(("make", "lint"), Path("/r"), {"A": "1"})
    assert (cmd.argv, cmd.cwd, cmd.env) == (("make", "lint"), Path("/r"), {"A": "1"})
    with pytest.raises(AttributeError):
        cmd.argv = ("x",)  # type: ignore[misc]
