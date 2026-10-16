# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Hook flows over one tree (scripts/githook_flows.py): commit hooks, run, plan, hooks-check."""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

import pytest
from scripts import githook_flows as flows
from scripts.githook_git import Repo
from scripts.githook_plan import UnknownNameError
from scripts.githook_stamps import GateLock

from tests.githook_support import Case, Rig, case_id, make_rig

if TYPE_CHECKING:
    from pathlib import Path

FAST = ["lint", "typecheck", "caps"]


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def write(rig: Rig, name: str, text: str = "new\n") -> None:
    (rig.root / name).write_text(text, encoding="utf-8")


def tree12(rig: Rig) -> str:
    return rig.tree()[:12]


# --------------------------------------------------------------------------- targets


def test_the_index_target_is_the_tree_about_to_be_committed(rig: Rig) -> None:
    write(rig, "b.txt")
    rig.git("add", "b.txt")
    target = flows.index_target(rig.gate)
    assert target.tree == rig.repo.index_tree()
    assert target.tree != rig.tree()
    assert target.stampable
    assert target.force is False


INDEX_STATES = [
    Case(("clean", ""), True, "clean"),
    Case(("staged", "b.txt"), True, "only staged"),
    Case(("unstaged", "a.txt"), False, "unstaged edit"),
    Case(("untracked", "u.txt"), False, "untracked file"),
]


@pytest.mark.parametrize("case", INDEX_STATES, ids=case_id)
def test_the_index_target_is_stampable_only_when_the_worktree_equals_the_index(
    rig: Rig, case: Case[tuple[str, str], bool]
) -> None:
    kind, name = case.given
    if kind == "staged":
        write(rig, name)
        rig.git("add", name)
    elif kind != "clean":
        write(rig, name, "changed\n")
    target = flows.index_target(rig.gate)
    assert target.stampable is case.expected
    assert target.why_not_stamped == "the working tree differs from the index"


def test_the_index_observer_sees_a_change_of_the_index_or_of_the_worktree(rig: Rig) -> None:
    target = flows.index_target(rig.gate)
    before = target.observe()
    assert target.observe() == before
    write(rig, "b.txt")
    assert target.observe() != before
    rig.git("add", "b.txt")
    assert target.observe().tree != before.tree


def test_the_head_target_is_the_head_tree_and_stampable_when_the_tree_is_clean(rig: Rig) -> None:
    target = flows.head_target(rig.gate)
    assert target.tree == rig.tree()
    assert target.stampable
    assert target.force is False
    assert flows.head_target(rig.gate, force=True).force is True


@pytest.mark.parametrize("dirt", ["untracked", "modified", "staged"])
def test_the_head_target_is_not_stampable_on_a_dirty_tree(rig: Rig, dirt: str) -> None:
    write(rig, "a.txt" if dirt != "untracked" else "u.txt", "dirty\n")
    if dirt == "staged":
        rig.git("add", "a.txt")
    target = flows.head_target(rig.gate)
    assert not target.stampable
    assert target.why_not_stamped == "the working tree is not clean"
    assert target.tree == rig.tree()


def test_the_head_observer_sees_a_new_commit_and_a_new_file(rig: Rig) -> None:
    target = flows.head_target(rig.gate)
    before = target.observe()
    write(rig, "b.txt")
    after_file = target.observe()
    assert after_file != before
    rig.git("add", "b.txt")
    rig.git("commit", "-q", "-m", "feat: b")
    assert target.observe().tree != before.tree


# --------------------------------------------------------------------------- pre-commit


@pytest.mark.parametrize("hook", ["pre-commit", "pre-merge-commit"])
def test_a_commit_hook_runs_fast_on_the_index_tree_and_stamps_it(rig: Rig, hook: str) -> None:
    write(rig, "b.txt")
    rig.git("add", "b.txt")
    tree = rig.repo.index_tree()
    assert flows.commit_hook(rig.gate, hook) == 0
    assert rig.runner.labels == FAST
    assert rig.stamped("fast", tree)
    assert not rig.stamped("fast", rig.tree())


def test_a_commit_of_an_already_stamped_tree_runs_nothing(rig: Rig) -> None:
    rig.stamp("fast", rig.repo.index_tree())
    assert flows.commit_hook(rig.gate, "pre-commit") == 0
    assert rig.runner.calls == []
    assert rig.text == "gate: fast: stamp found (took 1.5s, finished 2026-10-15T12:00:00Z)\n"


def test_a_failing_check_refuses_the_commit(rig: Rig) -> None:
    rig.runner.codes["lint"] = 1
    assert flows.commit_hook(rig.gate, "pre-commit") == 1
    assert rig.text.splitlines()[-1] == "gate: commit refused: fast failed (exit 1)"
    assert not rig.stamped("fast", rig.tree())


@pytest.mark.parametrize("failing", FAST)
def test_the_commit_is_refused_whichever_step_fails(rig: Rig, failing: str) -> None:
    rig.runner.codes[failing] = 5
    assert flows.commit_hook(rig.gate, "pre-merge-commit") == 1
    assert "gate: commit refused: fast failed (exit 5)" in rig.text


def test_a_partial_staging_is_tested_and_passes_but_is_not_stamped(rig: Rig) -> None:
    write(rig, "a.txt", "changed but not staged\n")
    assert flows.commit_hook(rig.gate, "pre-commit") == 0
    assert rig.runner.labels == FAST
    assert not rig.stamped("fast", rig.tree())
    assert rig.text.splitlines()[-1] == (
        "gate: fast: ok in 14.0s (not stamped: the working tree differs from the index)"
    )


def test_a_commit_while_a_push_gate_runs_is_refused_with_the_holder(rig: Rig) -> None:
    with GateLock(rig.gate.lock_path, "pid 5, pre-push, started 2026-10-15T10:00:00Z"):
        assert flows.commit_hook(rig.gate, "pre-commit") == 1
    assert rig.runner.calls == []
    lines = rig.text.splitlines()
    assert lines[0] == (
        f"gate: another gate run holds {rig.gate.lock_path} "
        "(pid 5, pre-push, started 2026-10-15T10:00:00Z); wait for it to finish"
    )
    assert lines[1] == "gate: commit refused: fast did not run (see the line above)"
    assert "failed" not in lines[1]


def test_the_commit_hook_uses_the_index_the_hook_was_given(rig: Rig, tmp_path: Path) -> None:
    alternate = tmp_path / "alt-index"
    shutil.copy(rig.root / ".git" / "index", alternate)
    env = {**rig.repo.env, "GIT_INDEX_FILE": str(alternate)}
    hook_repo = Repo(rig.repo.root, rig.repo.common_dir, env)
    write(rig, "c.txt")
    assert hook_repo.run("add", "c.txt").returncode == 0
    rig.gate.repo = hook_repo
    staged = hook_repo.index_tree()
    assert staged != rig.tree()
    assert flows.commit_hook(rig.gate, "pre-commit") == 0
    assert rig.stamped("fast", staged)
    assert not rig.stamped("fast", rig.tree())


# --------------------------------------------------------------------------- dry run


def dry(rig: Rig) -> None:
    rig.gate.environ = {"PATH": "/usr/bin", "SANKEY_GATE_DRY_RUN": "1"}


def test_a_dry_run_commit_prints_the_plan_runs_nothing_and_does_not_pass(rig: Rig) -> None:
    dry(rig)
    assert flows.commit_hook(rig.gate, "pre-commit") == 1
    assert rig.runner.calls == []
    assert rig.text == (
        f"plan: pre-commit tree={tree12(rig)}\n"
        "plan:   fast RUN\n"
        "gate: dry run: 1 check(s) would run, nothing was run\n"
    )
    assert not rig.gate.store.base.exists()


def test_a_dry_run_passes_only_when_nothing_would_run(rig: Rig) -> None:
    dry(rig)
    rig.stamp("fast", rig.tree())
    assert flows.commit_hook(rig.gate, "pre-merge-commit") == 0
    assert rig.text == (
        f"plan: pre-merge-commit tree={tree12(rig)}\n"
        "plan:   fast STAMPED (took 1.5s, finished 2026-10-15T12:00:00Z)\n"
    )


def test_the_dry_run_exit_is_one_with_pending_work_and_zero_without(rig: Rig) -> None:
    assert flows.dry_run_exit(rig.gate, []) == 0
    assert rig.text == ""
    assert flows.dry_run_exit(rig.gate, ["cov", "e2e"]) == 1
    assert rig.text == "gate: dry run: 2 check(s) would run, nothing was run\n"


def test_a_dry_run_of_run_reports_what_would_not_be_stamped(rig: Rig) -> None:
    dry(rig)
    write(rig, "u.txt")
    assert flows.run_names(rig.gate, ["cov"], force=False) == 1
    assert rig.text.splitlines()[:3] == [
        f"plan: run cov tree={tree12(rig)}",
        "plan:   cov RUN",
        "plan: a run now would not be stamped: the working tree is not clean",
    ]


# --------------------------------------------------------------------------- run


def test_run_runs_the_named_checks_on_head_in_run_order(rig: Rig) -> None:
    assert flows.run_names(rig.gate, ["e2e", "cov"], force=False) == 0
    assert rig.runner.labels == ["cov", "e2e"]
    assert rig.stamped("cov", rig.tree())
    assert rig.stamped("e2e", rig.tree())


def test_run_accepts_tier_names(rig: Rig) -> None:
    assert flows.run_names(rig.gate, ["push"], force=False) == 0
    assert rig.runner.labels == [*FAST, "cov", "memray", "e2e"]


def test_run_commit_is_the_fast_check(rig: Rig) -> None:
    assert flows.run_names(rig.gate, ["commit"], force=False) == 0
    assert rig.runner.labels == FAST


def test_run_skips_what_is_stamped_unless_forced(rig: Rig) -> None:
    rig.stamp("cov", rig.tree())
    assert flows.run_names(rig.gate, ["cov"], force=False) == 0
    assert rig.runner.calls == []
    assert flows.run_names(rig.gate, ["cov"], force=True) == 0
    assert rig.runner.labels == ["cov"]


def test_run_returns_one_for_any_failing_check_whatever_its_code(rig: Rig) -> None:
    rig.runner.codes["cov"] = 7
    assert flows.run_names(rig.gate, ["cov", "memray"], force=False) == 1
    assert rig.runner.labels == ["cov"]


def test_run_on_a_dirty_tree_passes_without_writing_a_stamp(rig: Rig) -> None:
    write(rig, "u.txt")
    assert flows.run_names(rig.gate, ["cov"], force=False) == 0
    assert not rig.stamped("cov", rig.tree())
    assert "(not stamped: the working tree is not clean)" in rig.text


def test_run_with_an_unknown_name_raises_the_name_error(rig: Rig) -> None:
    with pytest.raises(UnknownNameError, match="unknown check or tier 'nope'"):
        flows.run_names(rig.gate, ["fast", "nope"], force=False)
    assert rig.runner.calls == []


# --------------------------------------------------------------------------- plan


def test_plan_names_prints_one_line_per_check_and_runs_nothing(rig: Rig) -> None:
    rig.stamp("fast", rig.tree())
    assert flows.plan_names(rig.gate, ["push"]) == 0
    assert rig.runner.calls == []
    assert rig.text == (
        f"plan: run push tree={tree12(rig)}\n"
        "plan:   fast STAMPED (took 1.5s, finished 2026-10-15T12:00:00Z)\n"
        "plan:   cov RUN\n"
        "plan:   memray RUN\n"
        "plan:   e2e RUN\n"
    )


def test_plan_exits_zero_even_when_work_is_pending(rig: Rig) -> None:
    assert flows.plan_names(rig.gate, ["release"]) == 0
    assert flows.plan_commit(rig.gate, "pre-commit") == 0


def test_plan_says_when_an_offline_switch_would_refuse_the_run(rig: Rig) -> None:
    rig.gate.environ = {"TRIVY_OFFLINE": "1"}
    flows.plan_names(rig.gate, ["main"])
    assert (
        "plan: would refuse: gate: refusing to run security: TRIVY_OFFLINE is set; "
        "offline switches weaken the scans, unset it"
    ) in rig.text.splitlines()


def test_plan_does_not_mention_offline_for_a_plan_without_scans(rig: Rig) -> None:
    rig.gate.environ = {"TRIVY_OFFLINE": "1"}
    flows.plan_names(rig.gate, ["push"])
    assert "would refuse" not in rig.text


def test_plan_warns_that_a_run_on_a_dirty_tree_would_not_be_stamped(rig: Rig) -> None:
    write(rig, "u.txt")
    flows.plan_names(rig.gate, ["fast"])
    assert rig.text.splitlines()[-1] == (
        "plan: a run now would not be stamped: the working tree is not clean"
    )


def test_plan_stays_quiet_about_stamping_when_everything_is_stamped(rig: Rig) -> None:
    write(rig, "u.txt")
    rig.stamp("fast", rig.tree())
    flows.plan_names(rig.gate, ["fast"])
    assert "would not be stamped" not in rig.text


def test_plan_commit_describes_the_index_tree(rig: Rig) -> None:
    write(rig, "b.txt")
    rig.git("add", "b.txt")
    flows.plan_commit(rig.gate, "pre-merge-commit")
    index12 = rig.repo.index_tree()[:12]
    assert rig.text == f"plan: pre-merge-commit tree={index12}\nplan:   fast RUN\n"


def test_print_plan_returns_the_checks_that_would_run(rig: Rig) -> None:
    rig.stamp("cov", rig.tree())
    target = flows.head_target(rig.gate)
    assert flows.print_plan(rig.gate, "h", ["fast", "cov", "e2e"], target) == ["fast", "e2e"]
    forced = flows.head_target(rig.gate, force=True)
    assert flows.print_plan(rig.gate, "h", ["fast", "cov"], forced) == ["fast", "cov"]


# --------------------------------------------------------------------------- hooks-check


def install_hooks(rig: Rig, mode: int = 0o755, skip: str = "") -> None:
    folder = rig.root / ".githooks"
    folder.mkdir(exist_ok=True)
    for name in flows.HOOK_NAMES:
        if name == skip:
            continue
        path = folder / name
        path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        path.chmod(mode)
    rig.git("add", ".githooks")


def wire(rig: Rig, value: str = ".githooks") -> None:
    rig.git("config", "core.hooksPath", value)


def test_the_hook_wiring_has_the_four_hooks_and_the_mode_in_its_constants() -> None:
    assert flows.HOOK_NAMES == ("commit-msg", "pre-commit", "pre-merge-commit", "pre-push")
    assert (flows.HOOKS_PATH, flows.EXECUTABLE_MODE) == (".githooks", "100755")


def test_a_correct_wiring_has_no_problems(rig: Rig) -> None:
    wire(rig)
    install_hooks(rig)
    assert flows.hooks_problems(rig.gate) == []
    assert flows.hooks_check(rig.gate) == 0
    assert rig.text == "hooks-check: ok (core.hooksPath=.githooks, 4 hooks 100755)\n"


def test_an_absolute_hooks_path_to_the_same_folder_is_accepted(rig: Rig) -> None:
    install_hooks(rig)
    wire(rig, str(rig.root / ".githooks"))
    assert flows.hooks_problems(rig.gate) == []


@pytest.mark.parametrize("value", ["x", ".git/hooks", "/somewhere/else", "githooks"])
def test_another_hooks_path_is_a_problem(rig: Rig, value: str) -> None:
    install_hooks(rig)
    wire(rig, value)
    problems = flows.hooks_problems(rig.gate)
    assert len(problems) == 1
    assert problems[0].startswith("core.hooksPath is ")
    assert problems[0].endswith("expected '.githooks' (make hooks)")


def test_an_unset_hooks_path_is_a_problem(rig: Rig) -> None:
    install_hooks(rig)
    assert flows.hooks_problems(rig.gate) == [
        "core.hooksPath is None, expected '.githooks' (make hooks)"
    ]


def test_hooks_that_are_not_tracked_are_reported_one_by_one(rig: Rig) -> None:
    wire(rig)
    folder = rig.root / ".githooks"
    folder.mkdir()
    problems = flows.hooks_problems(rig.gate)
    assert [p for p in problems if "not tracked" in p] == [
        f".githooks/{name}: not tracked, expected index mode 100755" for name in flows.HOOK_NAMES
    ]
    assert len([p for p in problems if "not executable on disk" in p]) == 4


def test_a_hook_tracked_without_the_executable_bit_is_reported(rig: Rig) -> None:
    wire(rig)
    install_hooks(rig, mode=0o644)
    problems = flows.hooks_problems(rig.gate)
    assert ".githooks/pre-push: index mode 100644, expected index mode 100755" in problems
    assert ".githooks/pre-push: not executable on disk" in problems
    assert len(problems) == 8


def test_a_hook_that_is_tracked_executable_but_not_executable_on_disk_is_reported(rig: Rig) -> None:
    wire(rig)
    install_hooks(rig)
    (rig.root / ".githooks" / "pre-commit").chmod(0o644)
    assert flows.hooks_problems(rig.gate) == [".githooks/pre-commit: not executable on disk"]


def test_a_missing_hook_file_is_reported(rig: Rig) -> None:
    wire(rig)
    install_hooks(rig, skip="pre-push")
    assert flows.hooks_problems(rig.gate) == [
        ".githooks/pre-push: not tracked, expected index mode 100755",
        ".githooks/pre-push: not executable on disk",
    ]


def test_hooks_check_prints_every_problem_and_fails(rig: Rig) -> None:
    assert flows.hooks_check(rig.gate) == 1
    lines = rig.text.splitlines()
    assert lines[0] == "hooks-check: FAIL core.hooksPath is None, expected '.githooks' (make hooks)"
    assert len(lines) == 9
    assert all(line.startswith("hooks-check: FAIL ") for line in lines)
    assert "hooks-check: ok" not in rig.text


def test_hooks_check_reads_the_index_not_the_disk_for_the_mode(rig: Rig) -> None:
    wire(rig)
    install_hooks(rig)
    rig.git("update-index", "--chmod=-x", ".githooks/pre-push")
    assert os.access(rig.root / ".githooks" / "pre-push", os.X_OK)
    assert flows.hooks_problems(rig.gate) == [
        ".githooks/pre-push: index mode 100644, expected index mode 100755"
    ]
