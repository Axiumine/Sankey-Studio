# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The pre-push flow: messages of new commits, stamps per pushed tree, inline runs of the rest.

For every pushed ref that is not a deletion the required checks come from the REMOTE ref name
(``scripts/githook_plan.py``). Each check is looked up by the tree of the pushed commit (an
annotated tag is peeled). Missing checks run here, one at a time, but only when the working tree
is exactly the pushed commit: HEAD's tree equals the pushed tree and
``git status --porcelain --untracked-files=all`` is empty. Otherwise the hook refuses before it
runs anything and says what to do. Each check starts only if that is still the state (``Target``
baseline), and a job that passed must have left its stamp.

A dry run applies ``.githooks/commit-msg`` to the new commits too (it is read-only), so it exits 0
only when the real hook would.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts import githook_messages as msg
from scripts.githook_exec import (
    CheckRun,
    Gate,
    Target,
    describe_stamp,
    offline_refusal,
    preflight_names,
    run_preflight,
)
from scripts.githook_flows import dry_run_exit
from scripts.githook_git import Snapshot
from scripts.githook_plan import CHECK_ORDER, CHECKS, RefPlan, parse_push_lines, plan_push
from scripts.githook_stamps import GateBusyError

if TYPE_CHECKING:
    from collections.abc import Sequence

SHORT = 12
LISTED_STATUS_LINES = 20


@dataclass(frozen=True, slots=True)
class Planned:
    """A pushed ref with the tree of the commit it points to."""

    plan: RefPlan
    tree: str


@dataclass(frozen=True, slots=True)
class Job:
    """One check to run on one tree, on behalf of the first ref that needs it."""

    check: str
    planned: Planned


def plan_trees(gate: Gate, text: str) -> list[Planned]:
    """Parse the hook's stdin and attach each non-delete ref's tree."""
    plans = plan_push(parse_push_lines(text))
    return [Planned(p, gate.repo.commit_tree(p.ref.local_sha)) for p in plans]


def collect_jobs(gate: Gate, planned: Sequence[Planned]) -> list[Job]:
    """The checks without a stamp, de-duplicated by (check, stamp key), in run order."""
    jobs: list[Job] = []
    seen: set[tuple[str, str]] = set()
    for item in planned:
        for name in item.plan.checks:
            key = (name, gate.key_for(name, item.tree))
            if key not in seen and gate.stamp_of(name, item.tree) is None:
                jobs.append(Job(name, item))
            seen.add(key)
    return sorted(jobs, key=lambda job: CHECK_ORDER.index(job.check))


def say_stamps(gate: Gate, planned: Sequence[Planned], jobs: Sequence[Job]) -> None:
    """One line per check that is already stamped (a pushed tree is reported once per check)."""
    todo = {(job.check, job.planned.tree) for job in jobs}
    seen: set[tuple[str, str]] = set()
    for item in planned:
        for name in item.plan.checks:
            stamp = gate.stamp_of(name, item.tree)
            if (name, item.tree) in todo or (name, item.tree) in seen or stamp is None:
                continue
            seen.add((name, item.tree))
            gate.say(f"gate: {name}: stamp found ({describe_stamp(stamp)}) for {item.tree[:SHORT]}")


def new_commits(gate: Gate, planned: Sequence[Planned], remote: str) -> list[str]:
    """Commits of the pushed refs that are not on the remote yet, each once."""
    seen: dict[str, None] = {}
    for item in planned:
        ref = item.plan.ref
        for sha in gate.repo.new_commits(ref.local_sha, remote, ref.remote_sha):
            seen.setdefault(sha)
    return list(seen)


def check_messages(gate: Gate, shas: Sequence[str]) -> int:
    """Apply ``.githooks/commit-msg`` to each new commit; 1 when any message is refused."""
    bad = 0
    for sha in shas:
        code, output = gate.check_message(gate.repo, gate.repo.message(sha))
        if code != 0:
            bad = 1
            indented = "\n".join(f"gate:   {line}" for line in output.splitlines())
            gate.say(msg.MESSAGE_BAD.format(sha=sha[:SHORT], output=indented))
    return bad


def checkout_hint(item: Planned) -> str:
    ref = item.plan.ref
    if ref.local_ref.startswith("refs/heads/"):
        return f"git checkout {ref.local_ref.removeprefix('refs/heads/')}"
    if ref.local_ref.startswith("refs/"):
        return f"git checkout {ref.local_ref}"
    return f"git checkout {ref.local_sha[:SHORT]}"


def worktree_refusal(gate: Gate, jobs: Sequence[Job]) -> str | None:
    """Why checks cannot run here: HEAD is not the pushed commit, or the tree is not clean."""
    head = gate.repo.head_tree()
    for job in jobs:
        item = job.planned
        if item.tree != head:
            names = ", ".join(j.check for j in jobs if j.planned.tree == item.tree)
            return msg.NOT_CHECKED_OUT.format(
                ref=item.plan.ref.local_ref,
                sha=item.plan.ref.local_sha[:SHORT],
                checks=names,
                tree=item.tree[:SHORT],
                head=head[:SHORT],
                checkout=checkout_hint(item),
            )
    status = gate.repo.status()
    if status:
        shown = [f"gate:   {line}" for line in status[:LISTED_STATUS_LINES]]
        return msg.DIRTY_TREE.format(lines="\n".join(shown))
    return None


def pushed_target(gate: Gate, item: Planned) -> Target:
    """The pushed tree on a clean working tree; a check starts only if that is still the state."""
    repo = gate.repo
    return Target(
        item.tree,
        lambda: Snapshot(repo.head_tree(), repo.status()),
        baseline=Snapshot(item.tree, ()),
    )


def run_job(gate: Gate, job: Job) -> int:
    """One job on the pushed tree: the check's exit code, or 1 when it passed without a stamp."""
    run = CheckRun(gate, CHECKS[job.check], pushed_target(gate, job.planned))
    code = run.execute()
    if code == 0 and gate.store.read(job.check, run.key) is None:
        gate.say(msg.NOT_STAMPED.format(check=job.check, tree=job.planned.tree[:SHORT]))
        return 1
    return code


def run_jobs(gate: Gate, jobs: Sequence[Job]) -> int:
    """Run the jobs under the gate lock, stopping at the first failure."""
    try:
        with gate.lock():
            code, probe = run_preflight(
                gate, [job.check for job in jobs], pushed_target(gate, jobs[0].planned)
            )
            if code != 0:
                gate.say(msg.PREFLIGHT_REFUSED.format(probe=probe, code=code))
                return 1
            for job in jobs:
                if gate.stamp_of(job.check, job.planned.tree) is not None:
                    gate.say(f"gate: {job.check}: stamped meanwhile, skipped")
                    continue
                code = run_job(gate, job)
                if code != 0:
                    gate.say(msg.PUSH_REFUSED.format(check=job.check, code=code))
                    return 1
    except GateBusyError as busy:
        gate.say(msg.BUSY.format(lock=gate.lock_path, holder=busy))
        return 1
    return 0


def print_push_plan(gate: Gate, planned: Sequence[Planned], jobs: Sequence[Job]) -> None:
    for item in planned:
        ref = item.plan.ref
        gate.say(
            f"plan: pre-push {ref.local_ref} -> {ref.remote_ref} tier={item.plan.tier.value} "
            f"tree={item.tree[:SHORT]}"
        )
        for name in item.plan.checks:
            stamp = gate.stamp_of(name, item.tree)
            state = "RUN" if stamp is None else f"STAMPED ({describe_stamp(stamp)})"
            gate.say(f"plan:   {name} {state}")
    probes = preflight_names([job.check for job in jobs])
    if probes:
        gate.say(f"plan: preflight {', '.join(probes)} (before the first check)")
    refusal = offline_refusal(gate, [job.check for job in jobs])
    if refusal is not None:
        gate.say(f"plan: would refuse: {refusal}")


def is_dry_run(gate: Gate, override: bool | None) -> bool:
    """Dry run: ``override`` if given, else SANKEY_GATE_DRY_RUN=1 or a ``git push --dry-run``."""
    if override is not None:
        return override
    if gate.dry_run:
        return True
    if gate.git_dry_run():
        gate.say(msg.PUSH_DRY_RUN)
        return True
    return False


def pre_push(gate: Gate, remote: str, text: str, *, dry_run: bool | None = None) -> int:
    """The pre-push hook. ``dry_run`` overrides SANKEY_GATE_DRY_RUN (used by ``plan pre-push``)."""
    planned = plan_trees(gate, text)
    if not planned:
        gate.say("gate: nothing to check, no ref is created or updated")
        return 0
    dry = is_dry_run(gate, dry_run)
    commits = new_commits(gate, planned, remote)
    if dry:
        gate.say(f"plan: commit messages of {len(commits)} new commit(s) are checked")
    refused = check_messages(gate, commits)
    if refused and not dry:
        return 1
    jobs = collect_jobs(gate, planned)
    if dry:
        print_push_plan(gate, planned, jobs)
        return dry_run_exit(gate, [job.check for job in jobs]) or refused
    say_stamps(gate, planned, jobs)
    return push_jobs(gate, jobs)


def push_jobs(gate: Gate, jobs: Sequence[Job]) -> int:
    if not jobs:
        gate.say("gate: every required check has a stamp for the pushed tree(s)")
        return 0
    refusal = offline_refusal(gate, [job.check for job in jobs]) or worktree_refusal(gate, jobs)
    if refusal is not None:
        gate.say(refusal)
        return 1
    return run_jobs(gate, jobs)
