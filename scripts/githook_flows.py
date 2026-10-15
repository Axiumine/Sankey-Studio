"""Hook flows over one tree: pre-commit, pre-merge-commit, ``run``, ``plan``, hooks-check."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Final

from scripts import githook_messages as msg
from scripts.githook_exec import (
    Gate,
    Target,
    describe_stamp,
    ensure_checks,
    missing_checks,
    offline_refusal,
)
from scripts.githook_git import Snapshot, worktree_matches_index
from scripts.githook_plan import TIER_CHECKS, Tier, resolve_names

if TYPE_CHECKING:
    from collections.abc import Sequence

HOOK_NAMES: Final = ("commit-msg", "pre-commit", "pre-merge-commit", "pre-push")
HOOKS_PATH: Final = ".githooks"
EXECUTABLE_MODE: Final = "100755"


def index_target(gate: Gate) -> Target:
    """The tree about to be committed (what ``git write-tree`` sees in the hook's index)."""
    repo = gate.repo
    synced = worktree_matches_index(repo.status())
    return Target(
        repo.index_tree(),
        lambda: Snapshot(repo.index_tree(), repo.status()),
        synced,
        "the working tree differs from the index",
    )


def head_target(gate: Gate, *, force: bool = False) -> Target:
    """The tree of HEAD; a run is stamped only when the working tree is clean.

    On a clean tree every check of the run must start on exactly this state (``baseline``): a
    branch switch or a saved file between two checks stops the run instead of being stamped.
    """
    repo = gate.repo
    start = Snapshot(repo.head_tree(), repo.status())
    clean = not start.status
    return Target(
        start.tree,
        lambda: Snapshot(repo.head_tree(), repo.status()),
        clean,
        "the working tree is not clean",
        force,
        start if clean else None,
    )


def print_plan(gate: Gate, header: str, names: Sequence[str], target: Target) -> list[str]:
    """Print one ``plan:`` line per check; returns the checks that would run."""
    todo = missing_checks(gate, names, target)
    gate.say(f"plan: {header} tree={target.tree[:12]}")
    for name in names:
        stamp = None if name in todo else gate.stamp_of(name, target.tree)
        state = "RUN" if stamp is None else f"STAMPED ({describe_stamp(stamp)})"
        gate.say(f"plan:   {name} {state}")
    refusal = offline_refusal(gate, todo)
    if refusal is not None:
        gate.say(f"plan: would refuse: {refusal}")
    if todo and not target.stampable:
        gate.say(f"plan: a run now would not be stamped: {target.why_not_stamped}")
    return todo


def dry_run_exit(gate: Gate, todo: Sequence[str]) -> int:
    """A dry run passes (0) only when the real run would have nothing left to run."""
    if todo:
        gate.say(msg.DRY_PENDING.format(count=len(todo)))
        return 1
    return 0


def commit_hook(gate: Gate, hook: str) -> int:
    """pre-commit and pre-merge-commit: the ``commit`` tier on the index tree."""
    target = index_target(gate)
    names = TIER_CHECKS[Tier.COMMIT]
    if gate.dry_run:
        return dry_run_exit(gate, print_plan(gate, hook, names, target))
    outcome = ensure_checks(gate, names, target)
    if outcome.code == 0:
        return 0
    template = msg.COMMIT_REFUSED if outcome.ran else msg.COMMIT_NOT_RUN
    gate.say(template.format(check=outcome.check, code=outcome.code))
    return 1


def run_names(gate: Gate, names: Sequence[str], *, force: bool) -> int:
    """``run``: the named checks (or tiers) on HEAD's tree."""
    checks = resolve_names(names)
    target = head_target(gate, force=force)
    if gate.dry_run:
        return dry_run_exit(gate, print_plan(gate, "run " + " ".join(names), checks, target))
    outcome = ensure_checks(gate, checks, target)
    return 0 if outcome.code == 0 else 1


def plan_names(gate: Gate, names: Sequence[str]) -> int:
    """``plan <names>``: what ``run`` would do on HEAD's tree; always exits 0."""
    checks = resolve_names(names)
    print_plan(gate, "run " + " ".join(names), checks, head_target(gate))
    return 0


def plan_commit(gate: Gate, hook: str) -> int:
    """``plan pre-commit``: what the commit hook would do now; always exits 0."""
    print_plan(gate, hook, TIER_CHECKS[Tier.COMMIT], index_target(gate))
    return 0


def hooks_problems(gate: Gate) -> list[str]:
    """Everything wrong with the hook wiring (empty when it is right)."""
    repo = gate.repo
    problems = []
    configured = repo.config("core.hooksPath")
    if configured is None or (
        configured != HOOKS_PATH and os.path.realpath(configured) != str(repo.root / HOOKS_PATH)
    ):
        problems.append(f"core.hooksPath is {configured!r}, expected {HOOKS_PATH!r} (make hooks)")
    for name in HOOK_NAMES:
        path = f"{HOOKS_PATH}/{name}"
        mode = repo.tracked_mode(path)
        if mode != EXECUTABLE_MODE:
            found = f"index mode {mode}" if mode else "not tracked"
            problems.append(f"{path}: {found}, expected index mode {EXECUTABLE_MODE}")
        if not os.access(repo.root / path, os.X_OK):
            problems.append(f"{path}: not executable on disk")
    return problems


def hooks_check(gate: Gate) -> int:
    """``hooks-check``: core.hooksPath and the modes of the hook files (``git ls-files -s``)."""
    problems = hooks_problems(gate)
    for problem in problems:
        gate.say(f"hooks-check: FAIL {problem}")
    if problems:
        return 1
    gate.say(
        f"hooks-check: ok (core.hooksPath={HOOKS_PATH}, {len(HOOK_NAMES)} hooks {EXECUTABLE_MODE})"
    )
    return 0
