"""OS errors of the gate (stamp, log, lock paths) end in a ``gate: refusing:`` line, no traceback.

A regular file is put where the gate needs a directory (and the other way round for the lock),
which fails the same way for root and for everybody else.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest
from scripts import githook_gate as cli
from scripts.githook_flows import head_target
from scripts.githook_stamps import GateLock

from tests.githook_support import Case, Rig, case_id, make_rig, push_line, run_check

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from scripts.githook_exec import Gate, Target


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def block_stamps(gate: Gate) -> None:
    """``hook-stamps/fast`` is a file."""
    gate.store.base.mkdir(parents=True)
    (gate.store.base / "fast").write_text("in the way\n", encoding="utf-8")


def block_logs(gate: Gate) -> None:
    """``hook-logs`` is a file."""
    gate.log_dir.parent.mkdir(parents=True, exist_ok=True)
    gate.log_dir.write_text("in the way\n", encoding="utf-8")


def block_log_file(gate: Gate) -> None:
    """``hook-logs/fast.log`` is a directory."""
    (gate.log_dir / "fast.log").mkdir(parents=True)


def block_lock(gate: Gate) -> None:
    """``hook-gate.lock`` is a directory."""
    gate.lock_path.mkdir(parents=True)


BLOCKS = [
    Case(block_stamps, "hook-stamps", "stamp directory"),
    Case(block_logs, "hook-logs", "log directory"),
    Case(block_log_file, "fast.log", "log file"),
    Case(block_lock, "hook-gate.lock", "lock file"),
]


def refused(rig: Rig, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    """Run the command line; it must exit 1 with one ``gate: refusing:`` line on standard error."""
    assert cli.main(list(argv), gate=rig.gate, stdin=io.StringIO()) == 1
    err = capsys.readouterr().err
    assert err.startswith("gate: refusing: ")
    assert err.count("\n") == 1
    assert "Traceback" not in err
    return err


@pytest.mark.parametrize("case", BLOCKS, ids=case_id)
@pytest.mark.parametrize("command", [["pre-commit"], ["run", "fast"]])
def test_an_unusable_path_refuses_with_a_gate_line_and_runs_nothing(
    rig: Rig,
    capsys: pytest.CaptureFixture[str],
    case: Case[Callable[[Gate], None], str],
    command: list[str],
) -> None:
    case.given(rig.gate)
    err = refused(rig, capsys, *command)
    assert case.expected in err
    assert rig.runner.calls == []
    assert "running" not in rig.text
    assert not rig.stamped("fast", rig.tree())


def test_a_stamp_directory_that_cannot_be_used_fails_before_the_check_starts(rig: Rig) -> None:
    block_stamps(rig.gate)
    with pytest.raises(OSError, match="fast"):
        run_check(rig, "fast")
    assert rig.runner.calls == []
    assert "running" not in rig.text


def test_a_log_directory_that_cannot_be_used_fails_before_the_check_starts(rig: Rig) -> None:
    block_logs(rig.gate)
    with pytest.raises(OSError, match="hook-logs"):
        run_check(rig, "fast")
    assert rig.runner.calls == []


def test_the_stamp_directory_is_not_needed_when_the_run_cannot_be_stamped(rig: Rig) -> None:
    block_stamps(rig.gate)
    (rig.root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    target = head_target(rig.gate)
    assert not target.stampable
    assert run_check(rig, "fast", target) == 0
    assert rig.runner.labels == ["lint", "typecheck", "caps"]
    assert "not stamped: the working tree is not clean" in rig.text


def test_a_stamp_directory_is_prepared_for_a_run_that_will_be_stamped(rig: Rig) -> None:
    target: Target = head_target(rig.gate)
    assert target.stampable
    assert run_check(rig, "fast", target) == 0
    assert (rig.gate.store.base / "fast").is_dir()
    assert rig.stamped("fast", rig.tree())


def test_an_os_error_during_a_run_is_a_refusal_line_and_frees_the_lock(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    def denied() -> None:
        raise PermissionError(13, "Permission denied", "/somewhere/stamp")

    rig.runner.effects["lint"] = denied
    err = refused(rig, capsys, "run", "fast")
    assert err == "gate: refusing: [Errno 13] Permission denied: '/somewhere/stamp'\n"
    assert not rig.stamped("fast", rig.tree())
    with GateLock(rig.gate.lock_path, "free again"):
        pass
    rig.runner.effects.clear()
    assert cli.main(["run", "fast"], gate=rig.gate, stdin=io.StringIO()) == 0
    assert rig.stamped("fast", rig.tree())


def test_an_os_error_of_the_pre_push_gate_is_a_refusal_line_too(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.git("checkout", "-q", "-b", "feature")
    block_lock(rig.gate)
    line = push_line("refs/heads/feature", rig.git("rev-parse", "HEAD"), "refs/heads/feature")
    assert cli.main(["pre-push"], gate=rig.gate, stdin=io.StringIO(line)) == 1
    err = capsys.readouterr().err
    assert err.startswith("gate: refusing: ")
    assert "hook-gate.lock" in err
    assert rig.runner.calls == []
