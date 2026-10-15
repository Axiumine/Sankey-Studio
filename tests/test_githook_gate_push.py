"""The pre-push flow (scripts/githook_push.py): refs -> checks, stamps, refusals, resume, lock."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts import githook_push as push
from scripts.githook_git import GitError
from scripts.githook_plan import CHECK_ORDER
from scripts.githook_runner import GateInterruptedError
from scripts.githook_stamps import GateLock

from tests.githook_support import (
    ZERO,
    Case,
    Rig,
    case_id,
    commit_file,
    make_rig,
    push_line,
)

if TYPE_CHECKING:
    from pathlib import Path

FAST = ["lint", "typecheck", "caps"]
PUSH_TIER = ["fast", "cov", "memray", "e2e"]
PUSH_LABELS = [*FAST, "cov", "memray", "e2e"]
RELEASE_LABELS = [
    *PUSH_LABELS,
    "semgrep-test",
    "semgrep",
    "trivy",
    "ping-once",
    "e2e-mongo",
    "cov",
    "qodana",
    "mutate",
    "mutate-gate",
]


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def ahead(rig: Rig, message: str = "feat: feature work") -> str:
    """Branch ``feature`` one commit ahead of ``main``; HEAD ends on it. Returns its sha."""
    rig.git("checkout", "-q", "-b", "feature")
    return commit_file(rig.root, "f.txt", "feature\n", message)


def sha_of(rig: Rig, rev: str = "HEAD") -> str:
    return rig.git("rev-parse", rev)


def go(rig: Rig, text: str, remote: str = "origin") -> int:
    return push.pre_push(rig.gate, remote, text)


def lines_of(rig: Rig) -> list[str]:
    return rig.text.splitlines()


def track_origin(rig: Rig, rev: str = "main") -> None:
    rig.git("config", "remote.origin.url", "https://example.invalid/r.git")
    rig.git("update-ref", "refs/remotes/origin/main", sha_of(rig, rev))


# --------------------------------------------------------------------------- nothing to check


@pytest.mark.parametrize(
    "text", ["", "\n", "  \n\n", f"(delete) {ZERO} refs/heads/old {'a' * 40}\n"]
)
def test_an_empty_push_or_a_delete_needs_no_check(rig: Rig, text: str) -> None:
    assert go(rig, text) == 0
    assert rig.text == "gate: nothing to check, no ref is created or updated\n"
    assert rig.runner.calls == []


def test_a_delete_next_to_a_real_ref_is_skipped(rig: Rig) -> None:
    feature = ahead(rig)
    text = f"(delete) {ZERO} refs/heads/old {'a' * 40}\n" + push_line(
        "refs/heads/feature", feature, "refs/heads/feature"
    )
    assert go(rig, text) == 0
    assert rig.runner.labels == PUSH_LABELS


# --------------------------------------------------------------------------- ref -> checks


def prepare(rig: Rig, kind: str) -> str:
    """Make the repository ready for ``kind`` of push and return the stdin text."""
    if kind == "main":
        sha = sha_of(rig)
        return push_line("refs/heads/main", sha, "refs/heads/main")
    sha = ahead(rig)
    if kind == "branch":
        return push_line("refs/heads/feature", sha, "refs/heads/feature")
    if kind == "other name":
        return push_line("refs/heads/feature", sha, "refs/heads/review/42")
    if kind == "feature:main":
        return push_line("refs/heads/feature", sha, "refs/heads/main")
    if kind == "tag":
        rig.git("tag", "v1")
        return push_line("refs/tags/v1", sha, "refs/tags/v1")
    rig.git("tag", "-a", "v2", "-m", "release two")
    return push_line("refs/tags/v2", sha_of(rig, "refs/tags/v2"), "refs/tags/v2")


REF_CHECKS = [
    Case("branch", PUSH_LABELS, "a branch"),
    Case("other name", PUSH_LABELS, "a branch under another remote name"),
    Case("main", RELEASE_LABELS, "main"),
    Case("feature:main", RELEASE_LABELS, "feature:main"),
    Case("tag", RELEASE_LABELS, "a lightweight tag"),
    Case("annotated", RELEASE_LABELS, "an annotated tag"),
]


@pytest.mark.parametrize("case", REF_CHECKS, ids=case_id)
def test_each_pushed_ref_runs_the_checks_of_its_tier_in_order(
    rig: Rig, case: Case[str, list[str]]
) -> None:
    text = prepare(rig, case.given)
    assert go(rig, text) == 0
    assert rig.runner.labels == case.expected


def test_every_check_of_the_tier_is_stamped_for_the_pushed_tree(rig: Rig) -> None:
    text = prepare(rig, "feature:main")
    tree = rig.tree()
    assert go(rig, text) == 0
    assert all(rig.stamped(name, tree) for name in CHECK_ORDER)
    assert rig.gate.store.path("security", f"{tree}.20261015").is_file()
    assert not rig.stamped("fast", rig.tree("main"))


def test_a_branch_push_leaves_the_release_checks_alone(rig: Rig) -> None:
    text = prepare(rig, "branch")
    go(rig, text)
    tree = rig.tree()
    assert [name for name in CHECK_ORDER if rig.stamped(name, tree)] == PUSH_TIER


def test_an_annotated_tag_is_checked_through_the_tree_of_its_commit(rig: Rig) -> None:
    text = prepare(rig, "annotated")
    tag_object = sha_of(rig, "refs/tags/v2")
    assert tag_object != sha_of(rig, "feature")
    assert go(rig, text) == 0
    assert rig.stamped("fast", rig.tree("feature"))


def test_a_commit_with_the_same_tree_as_head_is_checked_by_that_tree(rig: Rig) -> None:
    pushed = sha_of(rig)
    rig.git("commit", "-q", "--allow-empty", "-m", "chore: amend without changes")
    assert sha_of(rig) != pushed
    assert go(rig, push_line("refs/heads/main", pushed, "refs/heads/main")) == 0
    assert rig.stamped("fast", rig.tree())


# --------------------------------------------------------------------------- stamps and resume


def test_nothing_runs_when_every_required_check_has_a_stamp(rig: Rig) -> None:
    text = prepare(rig, "branch")
    rig.stamp_all(PUSH_TIER, rig.tree())
    assert go(rig, text) == 0
    assert rig.runner.calls == []
    tree12 = rig.tree()[:12]
    assert lines_of(rig) == [
        *(
            f"gate: {name}: stamp found (took 1.5s, finished 2026-10-15T12:00:00Z) for {tree12}"
            for name in PUSH_TIER
        ),
        "gate: every required check has a stamp for the pushed tree(s)",
    ]


def test_stamps_of_a_dirty_or_wrong_tree_are_enough_when_nothing_has_to_run(rig: Rig) -> None:
    text = prepare(rig, "branch")
    rig.stamp_all(PUSH_TIER, rig.tree())
    rig.git("checkout", "-q", "main")
    (rig.root / "u.txt").write_text("dirty\n", encoding="utf-8")
    assert go(rig, text) == 0
    assert rig.runner.calls == []


def test_a_failing_check_refuses_the_push_and_keeps_the_stamps_that_passed(rig: Rig) -> None:
    text = prepare(rig, "branch")
    rig.runner.codes["memray"] = 3
    assert go(rig, text) == 1
    assert rig.runner.labels == [*FAST, "cov", "memray"]
    tree = rig.tree()
    assert [name for name in PUSH_TIER if rig.stamped(name, tree)] == ["fast", "cov"]
    assert lines_of(rig)[-2:] == [
        f"gate: FAILED memray (exit 3); log: {rig.gate.log_dir / 'memray.log'}",
        "gate: push refused: memray failed (exit 3); checks that passed keep their stamps",
    ]


def test_a_second_push_resumes_with_the_check_that_failed(rig: Rig) -> None:
    text = prepare(rig, "branch")
    rig.runner.codes["memray"] = 3
    go(rig, text)
    rig.runner.calls.clear()
    rig.runner.codes.clear()
    rig.out.truncate(0)
    rig.out.seek(0)
    assert go(rig, text) == 0
    assert rig.runner.labels == ["memray", "e2e"]
    tree12 = rig.tree()[:12]
    assert (
        f"gate: fast: stamp found (took 14.0s, finished 2026-10-15T12:30:00Z) for {tree12}"
        in rig.text
    )
    assert all(rig.stamped(name, rig.tree()) for name in PUSH_TIER)


@pytest.mark.parametrize("failing", ["lint", "cov", "e2e"])
def test_the_check_after_a_failure_never_starts(rig: Rig, failing: str) -> None:
    text = prepare(rig, "branch")
    rig.runner.codes[failing] = 1
    assert go(rig, text) == 1
    assert rig.runner.labels[-1] == failing


def test_a_junit_failure_refuses_the_push_like_any_other_failure(rig: Rig) -> None:
    text = prepare(rig, "branch")
    rig.runner.skips["e2e"] = ("no chrome",)
    assert go(rig, text) == 1
    assert "gate: e2e: junit: skipped test tests.test_skip::test_skip_0 (no chrome)" in lines_of(
        rig
    )
    assert lines_of(rig)[-1] == (
        "gate: push refused: e2e failed (exit 1); checks that passed keep their stamps"
    )


def test_a_tree_that_changes_during_a_check_voids_that_stamp_and_refuses(rig: Rig) -> None:
    text = prepare(rig, "branch")
    rig.runner.effects["cov"] = lambda: (rig.root / "stray.txt").write_text("x\n", encoding="utf-8")
    assert go(rig, text) == 1
    assert rig.stamped("fast", rig.tree())
    assert not rig.stamped("cov", rig.tree())
    assert "the working tree changed while it ran, no stamp written" in rig.text
    assert lines_of(rig)[-1].startswith("gate: push refused: cov failed (exit 1)")


def test_the_release_checks_stamped_earlier_are_not_run_again(rig: Rig) -> None:
    text = prepare(rig, "main")
    rig.stamp_all(["fast", "cov", "memray", "e2e", "e2e-mongo", "qodana", "mutation"], rig.tree())
    assert go(rig, text) == 0
    assert rig.runner.labels == ["semgrep-test", "semgrep", "trivy"]


def test_a_security_stamp_of_yesterday_does_not_count_today(rig: Rig) -> None:
    text = prepare(rig, "main")
    rig.stamp_all(CHECK_ORDER, rig.tree())
    assert go(rig, text) == 0
    assert rig.runner.calls == []
    rig.clock.advance(days=1)
    assert go(rig, text) == 0
    assert rig.runner.labels == ["semgrep-test", "semgrep", "trivy"]


def test_an_interrupt_unwinds_the_push_and_frees_the_lock(rig: Rig) -> None:
    text = prepare(rig, "branch")

    def interrupt() -> None:
        raise GateInterruptedError(15)

    rig.runner.effects["cov"] = interrupt
    with pytest.raises(GateInterruptedError):
        go(rig, text)
    assert rig.stamped("fast", rig.tree())
    assert not rig.stamped("cov", rig.tree())
    with GateLock(rig.gate.lock_path, "free"):
        pass


def test_a_check_stamped_by_someone_else_meanwhile_is_skipped(rig: Rig) -> None:
    text = prepare(rig, "branch")
    tree = rig.tree()
    rig.runner.effects["lint"] = lambda: rig.stamp("memray", tree)
    assert go(rig, text) == 0
    assert "memray" not in rig.runner.labels
    assert "gate: memray: stamped meanwhile, skipped" in lines_of(rig)


# --------------------------------------------------------------------------- refusals


def test_head_must_be_the_pushed_commit_and_the_message_says_how_to_fix_it(rig: Rig) -> None:
    feature = ahead(rig)
    rig.git("checkout", "-q", "main")
    assert go(rig, push_line("refs/heads/feature", feature, "refs/heads/feature")) == 1
    assert rig.runner.calls == []
    assert lines_of(rig) == [
        "gate: refusing to run checks: HEAD is not the commit being pushed",
        (
            f"gate:   refs/heads/feature ({feature[:12]}) needs fast, cov, memray, e2e; "
            f"its tree is {rig.tree('feature')[:12]} but the tree of HEAD is {rig.tree()[:12]}"
        ),
        "gate: check it out (git checkout feature) and push again",
    ]


def test_a_push_of_main_from_another_branch_asks_for_that_branch(rig: Rig) -> None:
    feature = ahead(rig)
    rig.git("checkout", "-q", "main")
    assert go(rig, push_line("refs/heads/feature", feature, "refs/heads/main")) == 1
    assert "needs fast, cov, memray, e2e, security, e2e-mongo, qodana, mutation;" in rig.text
    assert lines_of(rig)[-1] == "gate: check it out (git checkout feature) and push again"


def test_a_dirty_tree_is_refused_with_the_status_lines(rig: Rig) -> None:
    text = prepare(rig, "branch")
    (rig.root / "u.txt").write_text("untracked\n", encoding="utf-8")
    (rig.root / "f.txt").write_text("edited\n", encoding="utf-8")
    assert go(rig, text) == 1
    assert rig.runner.calls == []
    assert lines_of(rig) == [
        (
            "gate: refusing to run checks: the working tree is not clean "
            "(git status --porcelain --untracked-files=all):"
        ),
        "gate:    M f.txt",
        "gate:   ?? u.txt",
        "gate: commit your changes or stash them (git stash -u) and push again",
    ]


@pytest.mark.parametrize(("files", "shown"), [(19, 19), (20, 20), (21, 20), (60, 20)])
def test_at_most_twenty_status_lines_are_listed(rig: Rig, files: int, shown: int) -> None:
    text = prepare(rig, "branch")
    for index in range(files):
        (rig.root / f"u{index:02d}.txt").write_text("x\n", encoding="utf-8")
    assert go(rig, text) == 1
    listed = [line for line in lines_of(rig) if line.startswith("gate:   ?? ")]
    assert len(listed) == shown


def test_an_offline_switch_is_refused_before_the_checkout_is_even_looked_at(rig: Rig) -> None:
    feature = ahead(rig)
    rig.git("checkout", "-q", "main")
    rig.gate.environ = {"SEMGREP_OFFLINE": "1"}
    assert go(rig, push_line("refs/heads/feature", feature, "refs/heads/main")) == 1
    assert lines_of(rig) == [
        (
            "gate: refusing to run security: SEMGREP_OFFLINE is set; "
            "offline switches weaken the scans, unset it"
        )
    ]
    assert rig.runner.calls == []


def test_an_offline_switch_does_not_matter_for_a_push_without_scans(rig: Rig) -> None:
    text = prepare(rig, "branch")
    rig.gate.environ = {"SEMGREP_OFFLINE": "1", "TRIVY_OFFLINE": "1"}
    assert go(rig, text) == 0
    assert rig.runner.labels == PUSH_LABELS


def test_a_push_while_another_gate_runs_is_refused_with_the_holder(rig: Rig) -> None:
    text = prepare(rig, "branch")
    with GateLock(rig.gate.lock_path, "pid 42, run release, started 2026-10-15T09:00:00Z"):
        assert go(rig, text) == 1
    assert rig.runner.calls == []
    assert lines_of(rig) == [
        (
            f"gate: another gate run holds {rig.gate.lock_path} "
            "(pid 42, run release, started 2026-10-15T09:00:00Z); wait for it to finish"
        )
    ]


def test_two_refs_with_different_trees_cannot_both_be_checked_from_one_checkout(rig: Rig) -> None:
    main_sha = sha_of(rig)
    feature = ahead(rig)
    text = push_line("refs/heads/feature", feature, "refs/heads/feature") + push_line(
        "refs/heads/main", main_sha, "refs/heads/main"
    )
    assert go(rig, text) == 1
    assert rig.runner.calls == []
    assert lines_of(rig)[1].startswith(f"gate:   refs/heads/main ({main_sha[:12]}) needs ")
    assert lines_of(rig)[2] == "gate: check it out (git checkout main) and push again"


def test_a_stamped_second_tree_does_not_get_in_the_way(rig: Rig) -> None:
    main_sha = sha_of(rig)
    feature = ahead(rig)
    rig.stamp_all(CHECK_ORDER, rig.tree("main"))
    text = push_line("refs/heads/feature", feature, "refs/heads/feature") + push_line(
        "refs/heads/main", main_sha, "refs/heads/main"
    )
    assert go(rig, text) == 0
    assert rig.runner.labels == PUSH_LABELS


def test_a_malformed_line_and_an_unknown_commit_raise_for_the_caller_to_report(rig: Rig) -> None:
    with pytest.raises(ValueError, match="malformed pre-push line"):
        go(rig, "refs/heads/x only-two-fields\n")
    unknown = push_line("refs/heads/x", "1" * 40, "refs/heads/x")
    with pytest.raises(GitError, match="failed"):
        go(rig, unknown)


# --------------------------------------------------------------------------- dry run


def test_a_dry_run_prints_the_plan_and_fails_when_work_is_pending(rig: Rig) -> None:
    track_origin(rig)
    text = prepare(rig, "branch")
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    assert go(rig, text) == 1
    tree12 = rig.tree()[:12]
    assert lines_of(rig) == [
        "plan: commit messages of 1 new commit(s) are checked",
        f"plan: pre-push refs/heads/feature -> refs/heads/feature tier=push tree={tree12}",
        "plan:   fast RUN",
        "plan:   cov RUN",
        "plan:   memray RUN",
        "plan:   e2e RUN",
        "gate: dry run: 4 check(s) would run, nothing was run",
    ]
    assert rig.runner.calls == []
    assert rig.judge.seen == ["feat: feature work"]
    assert not rig.gate.store.base.exists()


def test_a_dry_run_passes_when_every_check_is_stamped(rig: Rig) -> None:
    text = prepare(rig, "branch")
    rig.stamp_all(PUSH_TIER, rig.tree())
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    assert go(rig, text) == 0
    assert "plan:   fast STAMPED (took 1.5s, finished 2026-10-15T12:00:00Z)" in lines_of(rig)
    assert "RUN" not in [line.split()[-1] for line in lines_of(rig) if line.startswith("plan:   ")]


def test_a_dry_run_of_a_release_push_names_its_tier_and_the_offline_refusal(rig: Rig) -> None:
    text = prepare(rig, "feature:main")
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1", "TRIVY_OFFLINE": "1"}
    assert go(rig, text) == 1
    assert "tier=release" in rig.text
    assert "refs/heads/feature -> refs/heads/main" in rig.text
    assert (
        "plan: would refuse: gate: refusing to run security: TRIVY_OFFLINE is set; "
        "offline switches weaken the scans, unset it"
    ) in lines_of(rig)
    assert "check(s) would run" in lines_of(rig)[-1]
    assert lines_of(rig)[-1] == "gate: dry run: 8 check(s) would run, nothing was run"


def test_the_dry_run_argument_overrides_the_environment(rig: Rig) -> None:
    text = prepare(rig, "branch")
    assert push.pre_push(rig.gate, "origin", text, dry_run=True) == 1
    assert rig.runner.calls == []
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    assert push.pre_push(rig.gate, "origin", text, dry_run=False) == 0
    assert rig.runner.labels == PUSH_LABELS


def test_a_dry_run_with_nothing_to_push_says_so_and_passes(rig: Rig) -> None:
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    assert go(rig, "") == 0
    assert rig.text == "gate: nothing to check, no ref is created or updated\n"
