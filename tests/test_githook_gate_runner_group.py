# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Stopping a child group (scripts/githook_runner.py): the whole group gets the grace period."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import time
import types
from typing import TYPE_CHECKING

import pytest
from scripts import githook_runner as runner

from tests.githook_support import alive

if TYPE_CHECKING:
    from pathlib import Path

LEADER = (
    "import os, subprocess, sys, time\n"
    "grandchild, marker, ready = sys.argv[1:4]\n"
    "child = subprocess.Popen([sys.executable, '-c', grandchild, marker, ready])\n"
    "end = time.monotonic() + 30\n"
    "while not os.path.exists(ready) and time.monotonic() < end:\n"
    "    pass\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(60)\n"
)
#: Cleans up for half a second after SIGTERM (like a docker client forwarding it), then writes.
SLOW_CLEANUP = (
    "import signal, sys, time\n"
    "marker, ready = sys.argv[1:3]\n"
    "def on_term(signum, frame):\n"
    "    time.sleep(0.5)\n"
    "    open(marker, 'w').write('cleaned')\n"
    "    sys.exit(0)\n"
    "signal.signal(signal.SIGTERM, on_term)\n"
    "open(ready, 'w').close()\n"
    "time.sleep(60)\n"
)
IGNORES_TERM = (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "open(sys.argv[2], 'w').close()\n"
    "time.sleep(60)\n"
)


def gone_soon(pid: int) -> bool:
    """True once the process is dead; SIGKILL is delivered asynchronously, so poll briefly."""
    deadline = time.monotonic() + 10
    while alive(pid) and time.monotonic() < deadline:
        pass
    return not alive(pid)


def start_group(grandchild: str, tmp_path: Path) -> tuple[subprocess.Popen[bytes], int]:
    """A leader that dies on SIGTERM and a grandchild in its group; returns both once ready."""
    argv = [
        sys.executable,
        "-c",
        LEADER,
        grandchild,
        str(tmp_path / "marker"),
        str(tmp_path / "ok"),
    ]
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, a throw-away process group
        argv, start_new_session=True, stdout=subprocess.PIPE
    )
    assert proc.stdout is not None
    return proc, int(proc.stdout.readline())


# --------------------------------------------------------------------------- group_alive


def test_the_group_of_this_process_is_alive() -> None:
    assert runner.group_alive(os.getpgrp()) is True


def test_a_group_without_members_is_not_alive() -> None:
    with subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True) as proc:
        proc.wait(timeout=30)
    assert runner.group_alive(proc.pid) is False


def test_a_group_that_may_not_be_signalled_counts_as_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_pgid: int, _signum: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "killpg", refuse)
    assert runner.group_alive(1) is False


# --------------------------------------------------------------------------- stop_group


def test_a_descendant_gets_its_cleanup_time_after_the_leader_died(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "GRACE_SECONDS", 5.0)
    proc, grandchild = start_group(SLOW_CLEANUP, tmp_path)
    with proc:
        runner.stop_group(proc)
    assert proc.returncode == -signal.SIGTERM
    assert (tmp_path / "marker").read_text(encoding="utf-8") == "cleaned"
    assert gone_soon(grandchild)


def test_a_descendant_that_outlasts_the_grace_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "GRACE_SECONDS", 0.5)
    proc, grandchild = start_group(IGNORES_TERM, tmp_path)
    with proc:
        runner.stop_group(proc)
    assert proc.returncode == -signal.SIGTERM
    assert gone_soon(grandchild)


def test_an_empty_group_is_not_waited_for(monkeypatch: pytest.MonkeyPatch) -> None:
    napped: list[float] = []
    monkeypatch.setattr(runner, "GRACE_SECONDS", 600.0)
    monkeypatch.setattr(
        runner, "time", types.SimpleNamespace(monotonic=time.monotonic, sleep=napped.append)
    )
    sleeping = [sys.executable, "-c", "import time; time.sleep(60)"]
    with subprocess.Popen(sleeping, start_new_session=True) as proc:  # noqa: S603 - fixed argv
        runner.stop_group(proc)
    assert proc.returncode == -signal.SIGTERM
    assert napped == []


def test_a_group_that_is_still_alive_is_polled_until_it_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "GRACE_SECONDS", 5.0)
    polled: list[float] = []
    real_sleep = time.sleep

    def record(seconds: float) -> None:
        polled.append(seconds)
        real_sleep(seconds)

    monkeypatch.setattr(
        runner, "time", types.SimpleNamespace(monotonic=time.monotonic, sleep=record)
    )
    proc, _grandchild = start_group(SLOW_CLEANUP, tmp_path)
    with proc:
        runner.stop_group(proc)
    assert polled
    assert set(polled) == {runner.GROUP_POLL_SECONDS}


class TermOnFirstWrite(io.StringIO):
    """An echo that sends SIGTERM to the gate when the leader reports that it is ready."""

    def write(self, text: str, /) -> int:
        os.kill(os.getpid(), signal.SIGTERM)
        return super().write(text)


def test_an_interrupted_run_lets_the_descendants_of_the_check_finish_their_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "GRACE_SECONDS", 5.0)
    argv = (
        sys.executable,
        "-c",
        LEADER,
        SLOW_CLEANUP,
        str(tmp_path / "marker"),
        str(tmp_path / "ok"),
    )
    command = runner.Command(argv, tmp_path, dict(os.environ))
    with pytest.raises(runner.GateInterruptedError) as caught:
        runner.SubprocessRunner().run(command, io.BytesIO(), TermOnFirstWrite())
    assert caught.value.code == 128 + signal.SIGTERM
    assert (tmp_path / "marker").read_text(encoding="utf-8") == "cleaned"
