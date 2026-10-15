"""A run vouches for one tree: every check must start on the state that was verified for it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts import githook_messages as msg
from scripts import githook_push as push
from scripts.githook_exec import CheckRun
from scripts.githook_flows import head_target, run_names
from scripts.githook_git import Snapshot

from tests.githook_support import Rig, commit_file, make_rig, push_line, run_check

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def moved_line(check: str) -> str:
    return msg.MOVED.format(check=check)


def after_first_check(monkeypatch: pytest.MonkeyPatch, action: Callable[[], object]) -> None:
    """Run ``action`` once, in the gap right after the first check of a run has finished."""
    real = CheckRun.execute
    done: list[bool] = []

    def execute(self: CheckRun) -> int:
        code = real(self)
        if not done:
            done.append(True)
            action()
        return code

    monkeypatch.setattr(CheckRun, "execute", execute)


def save_a_file(rig: Rig) -> None:
    (rig.root / "saved.txt").write_text("saved\n", encoding="utf-8")


def commit_a_file(rig: Rig) -> None:
    commit_file(rig.root, "c.txt", "c\n", "feat: another commit")


def switch_to_main(rig: Rig) -> None:
    rig.git("checkout", "-q", "main")


FILE = pytest.param(save_a_file, id="a saved file")
COMMIT = pytest.param(commit_a_file, id="a new commit")
SWITCH = pytest.param(switch_to_main, id="a branch switch")


# --------------------------------------------------------------------------- one check


def test_a_check_does_not_start_when_the_state_is_not_the_verified_one(rig: Rig) -> None:
    target = head_target(rig.gate)
    save_a_file(rig)
    assert run_check(rig, "fast", target) == 1
    assert rig.text == moved_line("fast") + "\n"
    assert rig.runner.calls == []
    assert not rig.gate.store.base.exists()


def test_a_check_starts_when_the_state_is_still_the_verified_one(rig: Rig) -> None:
    target = head_target(rig.gate)
    assert run_check(rig, "fast", target) == 0
    assert rig.stamped("fast", target.tree)
    assert moved_line("fast") not in rig.text


def test_the_head_target_of_a_clean_tree_carries_its_baseline(rig: Rig) -> None:
    target = head_target(rig.gate)
    assert target.baseline == Snapshot(rig.tree(), ())
    assert target.baseline == target.observe()


def test_the_head_target_of_a_dirty_tree_has_no_baseline_and_is_not_stamped(rig: Rig) -> None:
    save_a_file(rig)
    target = head_target(rig.gate)
    assert target.baseline is None
    assert target.stampable is False


# --------------------------------------------------------------------------- run


@pytest.mark.parametrize("move", [FILE, COMMIT])
def test_a_run_stops_when_the_tree_moves_between_two_checks(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, move: Callable[[Rig], None]
) -> None:
    tree = rig.tree()
    after_first_check(monkeypatch, lambda: move(rig))
    assert run_names(rig.gate, ["push"], force=False) == 1
    assert rig.runner.labels == ["lint", "typecheck", "caps"]
    assert rig.stamped("fast", tree)
    assert not rig.stamped("cov", tree)
    assert not rig.stamped("cov", rig.tree())
    assert moved_line("cov") in rig.text.splitlines()


# --------------------------------------------------------------------------- pre-push


def feature_push(rig: Rig) -> str:
    rig.git("checkout", "-q", "-b", "feature")
    sha = commit_file(rig.root, "f.txt", "f\n", "feat: feature work")
    return push_line("refs/heads/feature", sha, "refs/heads/feature")


@pytest.mark.parametrize("move", [FILE, COMMIT, SWITCH])
def test_a_push_stops_when_the_tree_moves_between_two_jobs(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, move: Callable[[Rig], None]
) -> None:
    text = feature_push(rig)
    pushed = rig.tree()
    after_first_check(monkeypatch, lambda: move(rig))
    assert push.pre_push(rig.gate, "origin", text) == 1
    assert rig.runner.labels == ["lint", "typecheck", "caps"]
    lines = rig.text.splitlines()
    assert moved_line("cov") in lines
    assert (
        lines[-1] == "gate: push refused: cov failed (exit 1); checks that passed keep their stamps"
    )
    assert rig.stamped("fast", pushed)
    for name in ("cov", "memray", "e2e"):
        assert not rig.stamped(name, pushed)
        assert not rig.stamped(name, rig.tree())


class Phantom:
    """A check run that reports success and writes no stamp."""

    key = "phantom"

    def __init__(self, *_args: object) -> None:
        self.ran = True

    def execute(self) -> int:
        return 0


def test_a_job_that_passed_without_leaving_a_stamp_refuses_the_push(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = feature_push(rig)
    monkeypatch.setattr(push, "CheckRun", Phantom)
    assert push.pre_push(rig.gate, "origin", text) == 1
    tree12 = rig.tree()[:12]
    assert rig.text.splitlines() == [
        f"gate: push refused: fast passed but left no stamp for tree {tree12}; run the push again",
        "gate: push refused: fast failed (exit 1); checks that passed keep their stamps",
    ]


def test_run_job_returns_the_exit_code_of_a_failing_check_unchanged(rig: Rig) -> None:
    text = feature_push(rig)
    rig.runner.codes["lint"] = 9
    assert push.pre_push(rig.gate, "origin", text) == 1
    assert (
        "gate: push refused: fast failed (exit 9); checks that passed keep their stamps" in rig.text
    )
