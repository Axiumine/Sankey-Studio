# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Pre-push: commit-message checks of new commits and the helpers of scripts/githook_push.py."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from scripts import githook_push as push
from scripts.githook_git import Snapshot, run_commit_msg_hook
from scripts.githook_plan import CHECK_ORDER, PushedRef, RefPlan, Tier

from tests.githook_support import (
    REPO_ROOT,
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

PUSH_TIER = ["fast", "cov", "memray", "e2e"]


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


def branch_push(rig: Rig) -> str:
    feature = ahead(rig)
    return push_line("refs/heads/feature", feature, "refs/heads/feature")


def track_origin(rig: Rig, rev: str = "main") -> None:
    rig.git("config", "remote.origin.url", "https://example.invalid/r.git")
    rig.git("update-ref", "refs/remotes/origin/main", sha_of(rig, rev))


# --------------------------------------------------------------------------- commit messages


def test_every_new_commit_message_is_judged_and_all_bad_ones_are_reported(rig: Rig) -> None:
    track_origin(rig)
    rig.git("checkout", "-q", "-b", "feature")
    first = commit_file(rig.root, "1.txt", "1\n", "bad first")
    commit_file(rig.root, "2.txt", "2\n", "feat: good")
    third = commit_file(rig.root, "3.txt", "3\n", "bad third")
    assert go(rig, push_line("refs/heads/feature", third, "refs/heads/feature")) == 1
    assert rig.judge.seen == ["bad third", "feat: good", "bad first"]
    assert lines_of(rig) == [
        f"gate: commit message of {third[:12]} is refused by .githooks/commit-msg:",
        "gate:   refused: bad third",
        "gate:   second line",
        f"gate: commit message of {first[:12]} is refused by .githooks/commit-msg:",
        "gate:   refused: bad first",
        "gate:   second line",
    ]
    assert rig.runner.calls == []


def test_good_messages_let_the_checks_run(rig: Rig) -> None:
    track_origin(rig)
    text = branch_push(rig)
    assert go(rig, text) == 0
    assert rig.judge.seen == ["feat: feature work"]


def test_commits_the_remote_already_has_are_not_judged(rig: Rig) -> None:
    rig.git("commit", "-q", "--allow-empty", "-m", "bad old one")
    track_origin(rig, "HEAD")
    text = branch_push(rig)
    assert go(rig, text) == 0
    assert rig.judge.seen == ["feat: feature work"]


def test_a_commit_in_two_pushed_refs_is_judged_once(rig: Rig) -> None:
    track_origin(rig)
    feature = ahead(rig)
    rig.git("branch", "second", feature)
    text = push_line("refs/heads/feature", feature, "refs/heads/feature") + push_line(
        "refs/heads/second", feature, "refs/heads/second"
    )
    assert go(rig, text) == 0
    assert rig.judge.seen == ["feat: feature work"]


def test_the_known_remote_sha_limits_the_commits_to_judge(rig: Rig) -> None:
    rig.git("config", "remote.origin.url", "https://example.invalid/r.git")
    rig.git("checkout", "-q", "-b", "feature")
    old = commit_file(rig.root, "o.txt", "o\n", "bad but already pushed")
    new = commit_file(rig.root, "n.txt", "n\n", "feat: new")
    assert go(rig, push_line("refs/heads/feature", new, "refs/heads/feature", old)) == 0
    assert "bad but already pushed" not in rig.judge.seen
    assert "feat: new" in rig.judge.seen


def test_a_push_by_url_does_not_judge_the_whole_history(rig: Rig) -> None:
    rig.git("update-ref", "refs/remotes/mirror/main", sha_of(rig))
    feature = ahead(rig)
    url = "https://example.invalid/elsewhere.git"
    assert go(rig, push_line("refs/heads/feature", feature, "refs/heads/feature"), url) == 0
    assert rig.judge.seen == ["feat: feature work"]


def test_the_real_commit_msg_hook_can_refuse_a_new_commit_message(rig: Rig) -> None:
    hooks = rig.root / ".githooks"
    hooks.mkdir()
    shutil.copy(REPO_ROOT / ".githooks" / "commit-msg", hooks / "commit-msg")
    commit_file(rig.root, "x.txt", "x\n", "chore(hooks): add the commit-msg hook")
    track_origin(rig, "HEAD")
    rig.gate.check_message = run_commit_msg_hook
    feature = ahead(rig, "update some things")
    assert go(rig, push_line("refs/heads/feature", feature, "refs/heads/feature")) == 1
    lines = lines_of(rig)
    assert lines[0] == f"gate: commit message of {feature[:12]} is refused by .githooks/commit-msg:"
    assert all(line.startswith("gate:   ") for line in lines[1:])
    assert any("update some things" in line for line in lines)
    assert rig.runner.calls == []


def bad_stamped_push(rig: Rig) -> tuple[str, str]:
    """A push of a commit with a refused message whose tree already has every stamp."""
    track_origin(rig)
    rig.git("checkout", "-q", "-b", "feature")
    sha = commit_file(rig.root, "f.txt", "f\n", "bad subject")
    rig.stamp_all(PUSH_TIER, rig.tree())
    return push_line("refs/heads/feature", sha, "refs/heads/feature"), sha


@pytest.mark.parametrize("via", ["environment", "git push --dry-run"])
def test_a_dry_run_cannot_get_a_refused_message_past_the_hook(rig: Rig, via: str) -> None:
    text, sha = bad_stamped_push(rig)
    if via == "environment":
        rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    else:
        rig.gate.git_dry_run = lambda: True
    assert go(rig, text) == 1
    assert rig.judge.seen == ["bad subject"]
    assert f"gate: commit message of {sha[:12]} is refused by .githooks/commit-msg:" in lines_of(
        rig
    )
    assert "gate:   refused: bad subject" in lines_of(rig)
    assert rig.runner.calls == []


def test_a_dry_run_with_a_refused_message_still_prints_the_plan_and_the_pending_work(
    rig: Rig,
) -> None:
    track_origin(rig)
    rig.git("checkout", "-q", "-b", "feature")
    sha = commit_file(rig.root, "f.txt", "f\n", "bad subject")
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    assert go(rig, push_line("refs/heads/feature", sha, "refs/heads/feature")) == 1
    lines = lines_of(rig)
    assert lines[0] == "plan: commit messages of 1 new commit(s) are checked"
    assert lines[1].startswith(f"gate: commit message of {sha[:12]} is refused")
    assert "plan:   fast RUN" in lines
    assert lines[-1] == "gate: dry run: 4 check(s) would run, nothing was run"


def test_a_dry_run_with_good_messages_and_every_stamp_passes_after_judging_the_messages(
    rig: Rig,
) -> None:
    track_origin(rig)
    text = branch_push(rig)
    rig.stamp_all(PUSH_TIER, rig.tree())
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    assert go(rig, text) == 0
    assert rig.judge.seen == ["feat: feature work"]


# --------------------------------------------------------------------------- helpers


def planned_for(rig: Rig, text: str) -> list[push.Planned]:
    return push.plan_trees(rig.gate, text)


def test_plan_trees_attaches_the_tree_of_each_non_delete_ref(rig: Rig) -> None:
    feature = ahead(rig)
    text = (
        push_line("refs/heads/feature", feature, "refs/heads/main")
        + f"(delete) {ZERO} refs/heads/old {'b' * 40}\n"
    )
    (only,) = planned_for(rig, text)
    assert only.tree == rig.tree()
    assert only.plan.tier is Tier.RELEASE
    assert only.plan.ref.local_sha == feature


def test_collect_jobs_has_one_job_per_check_and_tree_in_run_order(rig: Rig) -> None:
    feature = ahead(rig)
    text = (
        push_line("refs/heads/feature", feature, "refs/heads/main")
        + push_line("refs/heads/feature", feature, "refs/heads/feature")
        + push_line("refs/tags/v1", feature, "refs/tags/v1")
    )
    jobs = push.collect_jobs(rig.gate, planned_for(rig, text))
    assert [job.check for job in jobs] == list(CHECK_ORDER)
    assert {job.planned.plan.ref.remote_ref for job in jobs} == {"refs/heads/main"}


def test_collect_jobs_leaves_out_what_is_stamped(rig: Rig) -> None:
    feature = ahead(rig)
    rig.stamp_all(["fast", "memray"], rig.tree())
    text = push_line("refs/heads/feature", feature, "refs/heads/feature")
    jobs = push.collect_jobs(rig.gate, planned_for(rig, text))
    assert [job.check for job in jobs] == ["cov", "e2e"]
    assert push.collect_jobs(rig.gate, []) == []


def test_collect_jobs_keeps_the_checks_of_two_trees_apart(rig: Rig) -> None:
    main_sha = sha_of(rig)
    feature = ahead(rig)
    text = push_line("refs/heads/feature", feature, "refs/heads/feature") + push_line(
        "refs/heads/other", main_sha, "refs/heads/other"
    )
    jobs = push.collect_jobs(rig.gate, planned_for(rig, text))
    assert len(jobs) == 8
    assert [job.check for job in jobs] == [name for name in PUSH_TIER for _ in range(2)]


def test_say_stamps_reports_each_stamped_check_of_a_tree_once(rig: Rig) -> None:
    feature = ahead(rig)
    rig.stamp_all(["fast", "cov"], rig.tree())
    text = push_line("refs/heads/feature", feature, "refs/heads/feature") * 2
    planned = planned_for(rig, text)
    push.say_stamps(rig.gate, planned, push.collect_jobs(rig.gate, planned))
    tree12 = rig.tree()[:12]
    assert lines_of(rig) == [
        f"gate: fast: stamp found (took 1.5s, finished 2026-10-15T12:00:00Z) for {tree12}",
        f"gate: cov: stamp found (took 1.5s, finished 2026-10-15T12:00:00Z) for {tree12}",
    ]


def test_new_commits_lists_each_commit_once_across_refs(rig: Rig) -> None:
    track_origin(rig)
    feature = ahead(rig)
    second = commit_file(rig.root, "g.txt", "g\n", "feat: second")
    text = push_line("refs/heads/feature", second, "refs/heads/feature") + push_line(
        "refs/heads/again", feature, "refs/heads/again"
    )
    assert push.new_commits(rig.gate, planned_for(rig, text), "origin") == [second, feature]


def test_check_messages_returns_zero_for_good_messages_and_one_for_any_bad_one(rig: Rig) -> None:
    good = ahead(rig)
    bad = commit_file(rig.root, "b.txt", "b\n", "bad again")
    assert push.check_messages(rig.gate, []) == 0
    assert push.check_messages(rig.gate, [good]) == 0
    assert rig.text == ""
    assert push.check_messages(rig.gate, [bad, good]) == 1
    assert (
        lines_of(rig)[0]
        == f"gate: commit message of {bad[:12]} is refused by .githooks/commit-msg:"
    )


def planned_ref(local: str, sha: str = "c" * 40) -> push.Planned:
    ref = PushedRef(local, sha, "refs/heads/x", ZERO)
    return push.Planned(RefPlan(ref, Tier.PUSH, ("fast",)), "t" * 40)


CHECKOUTS = [
    Case("refs/heads/feature", "git checkout feature", "a branch"),
    Case("refs/heads/team/topic", "git checkout team/topic", "a branch with a slash"),
    Case("refs/tags/v1", "git checkout refs/tags/v1", "a tag"),
    Case("refs/remotes/origin/x", "git checkout refs/remotes/origin/x", "a remote ref"),
    Case("HEAD", f"git checkout {'c' * 12}", "HEAD"),
    Case("abc123", f"git checkout {'c' * 12}", "a bare name"),
    Case("(delete)", f"git checkout {'c' * 12}", "no ref"),
]


@pytest.mark.parametrize("case", CHECKOUTS, ids=case_id)
def test_the_checkout_hint_depends_on_the_kind_of_local_ref(case: Case[str, str]) -> None:
    assert push.checkout_hint(planned_ref(case.given)) == case.expected


def test_worktree_refusal_is_none_for_the_pushed_commit_on_a_clean_tree(rig: Rig) -> None:
    feature = ahead(rig)
    text = push_line("refs/heads/feature", feature, "refs/heads/feature")
    jobs = push.collect_jobs(rig.gate, planned_for(rig, text))
    assert push.worktree_refusal(rig.gate, jobs) is None
    assert push.worktree_refusal(rig.gate, []) is None


def test_the_pushed_target_is_the_pushed_tree_on_a_clean_tree_and_may_always_stamp(
    rig: Rig,
) -> None:
    feature = ahead(rig)
    (item,) = planned_for(rig, push_line("refs/heads/feature", feature, "refs/heads/feature"))
    target = push.pushed_target(rig.gate, item)
    assert target.tree == item.tree == rig.tree()
    assert target.stampable
    assert target.baseline == Snapshot(item.tree, ())
    before = target.observe()
    assert before == target.baseline
    (rig.root / "n.txt").write_text("n\n", encoding="utf-8")
    assert target.observe() != before


def test_the_push_shows_progress_for_each_check_like_any_other_run(rig: Rig) -> None:
    text = branch_push(rig)
    go(rig, text)
    tree = rig.tree()
    assert "gate: fast: running" in lines_of(rig)
    assert f"gate: e2e: ok in 6.0s (stamp {rig.gate.store.path('e2e', tree)})" in lines_of(rig)
