# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Running checks: the Gate context, one CheckRun, the Mongo session, ``ensure_checks``."""

from __future__ import annotations

import os
import shlex
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, NamedTuple, TextIO

from scripts import githook_messages as msg
from scripts.githook_git import run_commit_msg_hook
from scripts.githook_junit import check_reports
from scripts.githook_parent import invoked_by_dry_run_push
from scripts.githook_plan import (
    CHECKS,
    MONGO_ENV,
    MONGO_URI,
    PREFLIGHT_ORDER,
    PREFLIGHTS,
    Check,
    Step,
    stamp_key,
)
from scripts.githook_runner import Command, Runner, build_child_env
from scripts.githook_stamps import GateBusyError, GateLock, Stamp, StampStore, StepTiming

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from scripts.githook_git import Repo, Snapshot

MONGO_WAIT_SECONDS = 60
OFFLINE_SUFFIX = "_OFFLINE"
DRY_RUN_ENV = "SANKEY_GATE_DRY_RUN"


def utc_now() -> datetime:
    return datetime.now(UTC)


def seconds(value: float) -> str:
    return f"{value:.1f}s"


@dataclass
class Gate:
    """Everything a run needs, with the clock, the runner and the output injectable."""

    repo: Repo
    runner: Runner
    out: TextIO
    environ: Mapping[str, str]
    clock: Callable[[], datetime] = utc_now
    tick: Callable[[], float] = time.monotonic
    home: Path = field(default_factory=Path.home)
    label: str = "gate"
    check_message: Callable[[Repo, str], tuple[int, str]] = run_commit_msg_hook
    git_dry_run: Callable[[], bool] = invoked_by_dry_run_push
    _scoped: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    @property
    def store(self) -> StampStore:
        return StampStore(self.repo.common_dir / "hook-stamps")

    @property
    def log_dir(self) -> Path:
        return self.repo.common_dir / "hook-logs"

    @property
    def lock_path(self) -> Path:
        return self.repo.common_dir / "hook-gate.lock"

    @property
    def dry_run(self) -> bool:
        return self.environ.get(DRY_RUN_ENV) == "1"

    @cached_property
    def base_env(self) -> dict[str, str]:
        return build_child_env(self.environ, self.repo.local_env_vars(), self.home)

    def child_env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        return {**self.base_env, **(extra or {})}

    def say(self, line: str) -> None:
        self.out.write(line + "\n")
        self.out.flush()

    def today(self) -> date:
        return self.clock().astimezone(UTC).date()

    def scoped(self, tree: str) -> str:
        """The key of ``tree`` without the files no check reads (asked of git once per tree)."""
        if tree not in self._scoped:
            self._scoped[tree] = self.repo.scoped_tree(tree)
        return self._scoped[tree]

    def key_of(self, check: Check, tree: str) -> str:
        return stamp_key(check, self.scoped(tree), self.today())

    def key_for(self, name: str, tree: str) -> str:
        return self.key_of(CHECKS[name], tree)

    def stamp_of(self, name: str, tree: str) -> Stamp | None:
        return self.store.read(name, self.key_for(name, tree))

    def lock(self) -> GateLock:
        started = self.clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return GateLock(self.lock_path, f"pid {os.getpid()}, {self.label}, started {started}")

    def run_tool(self, argv: Sequence[str], log: BinaryIO) -> int:
        """Run a helper command (Mongo up, down, ping) through the runner."""
        command = Command(tuple(argv), self.repo.root, self.child_env())
        return self.runner.run(command, log, self.out)


class Target(NamedTuple):
    """The tree a run vouches for and how to observe the state it must not change.

    ``baseline`` is the state the caller verified when it chose ``tree``. A check starts only if
    the state it observes first is still that one, so a stamp for ``tree`` is never written for a
    check that ran on something else (HEAD moved, a file saved) between two checks of one run.
    """

    tree: str
    observe: Callable[[], Snapshot]
    stampable: bool = True
    why_not_stamped: str = ""
    force: bool = False
    baseline: Snapshot | None = None


class Outcome(NamedTuple):
    """``code`` 0 means every check is stamped; otherwise ``check`` failed with that code.

    ``ran`` is False when the gate refused to start ``check`` (an offline switch, a busy lock):
    nothing failed, the check never ran.
    """

    code: int
    check: str = ""
    ran: bool = True


def ping_argv(wait: int) -> tuple[str, ...]:
    return (
        "uv",
        "run",
        "python",
        "scripts/mongo_wait.py",
        "--uri",
        MONGO_URI,
        "--timeout",
        str(wait),
    )


@contextmanager
def mongo_session(gate: Gate, log: BinaryIO) -> Iterator[bool]:
    """Yield whether the project Mongo answers; stop it afterwards only if this call started it.

    A Mongo that does not answer the first ping may still be a container the user started a
    moment ago. ``make mongo-absent`` (docker itself says no project container is running) is the
    only thing that lets the gate start the Mongo, and so stop it again; anything else (a
    container that is booting, Docker not answering) is waited for and left alone.
    """
    if gate.run_tool(ping_argv(0), log) == 0:
        gate.say("gate: mongo: already running on 127.0.0.1:27117, left running")
        yield True
        return
    if gate.run_tool(("make", "mongo-absent"), log) != 0:
        gate.say(msg.MONGO_NOT_OURS.format(seconds=MONGO_WAIT_SECONDS))
        yield gate.run_tool(ping_argv(MONGO_WAIT_SECONDS), log) == 0
        return
    try:
        started = gate.run_tool(("make", "mongo-up"), log) == 0
        yield started and gate.run_tool(ping_argv(MONGO_WAIT_SECONDS), log) == 0
    finally:
        gate.run_tool(("make", "mongo-down"), log)


class CheckRun:
    """One execution of one check on one tree; writes the stamp only after a clean pass."""

    def __init__(self, gate: Gate, check: Check, target: Target) -> None:
        self.gate = gate
        self.check = check
        self.target = target
        self.key = gate.key_of(check, target.tree)
        self.log_path = gate.log_dir / f"{check.name}.log"
        self.junit_root = gate.log_dir / f"{check.name}.junit"
        self.timings: list[StepTiming] = []

    def execute(self) -> int:
        """Run every step; return 0 after a pass (stamped when allowed), else the failing code."""
        gate = self.gate
        name = self.check.name
        before = self.target.observe()
        if self.target.baseline is not None and before != self.target.baseline:
            gate.say(msg.MOVED.format(check=name))
            return 1
        self._prepare()
        started = gate.tick()
        with self.log_path.open("wb") as log:
            gate.say(f"gate: {name}: running")
            code = self._run_all(log)
        elapsed = gate.tick() - started
        if code != 0:
            gate.say(msg.FAILED.format(check=name, code=code, log=self.log_path))
            return code
        if self.target.observe() != before:
            gate.say(msg.CHANGED.format(check=name, log=self.log_path))
            return 1
        return self._finish(elapsed)

    def _prepare(self) -> None:
        """Make the log and stamp directories usable before the check starts (OSError if not)."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.target.stampable:
            self.gate.store.prepare(self.check.name)
        if self.junit_root.is_dir():
            for stale in self.junit_root.rglob("*.xml"):
                stale.unlink()

    def _run_all(self, log: BinaryIO) -> int:
        if not self.check.mongo:
            return self._run_steps(log, {})
        with mongo_session(self.gate, log) as ready:
            if not ready:
                self.gate.say(msg.MONGO_DOWN.format(check=self.check.name))
                return 1
            return self._run_steps(log, {MONGO_ENV: MONGO_URI})

    def _run_steps(self, log: BinaryIO, extra: Mapping[str, str]) -> int:
        env = self.gate.child_env(extra)
        for index, step in enumerate(self.check.steps):
            code = self._run_step(index, step, env, log)
            if code != 0:
                return code
        return 0

    def _run_step(self, index: int, step: Step, env: Mapping[str, str], log: BinaryIO) -> int:
        argv = list(step.argv)
        report_dir = self.junit_root / f"step{index}" if step.junit else None
        if report_dir is not None:
            report_dir.mkdir(parents=True, exist_ok=True)
            argv.append(f"JUNIT={report_dir / 'report.xml'}")
        if not step.uv_locked:
            env = {k: v for k, v in env.items() if k != "UV_LOCKED"}
        header = f"$ {shlex.join(argv)}\n"
        log.write(header.encode())
        self.gate.out.write(header)
        started = self.gate.tick()
        command = Command(tuple(argv), self.gate.repo.root, env)
        code = self.gate.runner.run(command, log, self.gate.out)
        self.timings.append(StepTiming(step.argv, code, self.gate.tick() - started))
        if code != 0 or report_dir is None:
            return code
        return self._verify(report_dir, step)

    def _verify(self, report_dir: Path, step: Step) -> int:
        verdict = check_reports(report_dir, step.allow_skips)
        for problem in verdict.problems:
            self.gate.say(msg.JUNIT.format(check=self.check.name, problem=problem))
        return 0 if verdict.ok else 1

    def _finish(self, elapsed: float) -> int:
        gate = self.gate
        name = self.check.name
        if not self.target.stampable:
            reason = self.target.why_not_stamped
            gate.say(f"gate: {name}: ok in {seconds(elapsed)} (not stamped: {reason})")
            return 0
        finished = gate.clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        stamp = Stamp(name, self.key, self.target.tree, finished, elapsed, tuple(self.timings))
        path = gate.store.write(stamp)
        gate.say(f"gate: {name}: ok in {seconds(elapsed)} (stamp {path})")
        return 0


def missing_checks(gate: Gate, names: Sequence[str], target: Target) -> list[str]:
    """The checks of ``names`` without a stamp for the target's tree (all of them if forced)."""
    return [n for n in names if target.force or gate.stamp_of(n, target.tree) is None]


def describe_stamp(stamp: Stamp) -> str:
    return f"took {seconds(stamp.duration_s)}, finished {stamp.finished_utc}"


def offline_variable(environ: Mapping[str, str]) -> str | None:
    """The first ``*_OFFLINE`` variable that is switched on, if any."""
    names = sorted(
        k for k, v in environ.items() if k.endswith(OFFLINE_SUFFIX) and v not in {"", "0"}
    )
    return names[0] if names else None


def offline_refusal(gate: Gate, todo: Sequence[str]) -> str | None:
    """Refusal text when a scan would run with an offline switch on; None when all is well."""
    name = offline_variable(gate.environ)
    guarded = [c for c in todo if CHECKS[c].offline_guard]
    if name is None or not guarded:
        return None
    return msg.OFFLINE.format(check=guarded[0], name=name)


def preflight_names(names: Sequence[str]) -> list[str]:
    """The probes the checks in ``names`` need, each once, in the fixed order of ``PREFLIGHTS``."""
    wanted = {probe for name in names for probe in CHECKS[name].needs}
    return [probe for probe in PREFLIGHT_ORDER if probe in wanted]


def run_preflight(gate: Gate, names: Sequence[str], target: Target) -> tuple[int, str]:
    """Run the probes of ``names`` before any long check.

    Returns ``(0, "")``, else the failing exit code and the probe.

    A probe says something about this machine and not about the tree, so it is never stamped.
    """
    probes = preflight_names(names)
    if probes:
        gate.say(f"gate: preflight: {', '.join(probes)} (seconds, before any long check)")
    machine = target._replace(stampable=False, why_not_stamped="a probe of this machine")
    for probe in probes:
        code = CheckRun(gate, PREFLIGHTS[probe], machine).execute()
        if code != 0:
            return code, probe
    return 0, ""


def ensure_checks(gate: Gate, names: Sequence[str], target: Target) -> Outcome:
    """Run the checks without a stamp for ``target`` one at a time; stop at the first failure."""
    todo = missing_checks(gate, names, target)
    for name in names:
        found = None if name in todo else gate.stamp_of(name, target.tree)
        if found is not None:
            gate.say(f"gate: {name}: stamp found ({describe_stamp(found)})")
    if not todo:
        return Outcome(0)
    refusal = offline_refusal(gate, todo)
    if refusal is not None:
        gate.say(refusal)
        return Outcome(1, todo[0], ran=False)
    try:
        with gate.lock():
            return run_todo(gate, todo, target)
    except GateBusyError as busy:
        gate.say(msg.BUSY.format(lock=gate.lock_path, holder=busy))
        return Outcome(1, todo[0], ran=False)


def run_todo(gate: Gate, todo: Sequence[str], target: Target) -> Outcome:
    code, probe = run_preflight(gate, todo, target)
    if code != 0:
        return Outcome(code, probe)
    for name in todo:
        if not target.force and gate.stamp_of(name, target.tree) is not None:
            gate.say(f"gate: {name}: stamped meanwhile, skipped")
            continue
        code = CheckRun(gate, CHECKS[name], target).execute()
        if code != 0:
            return Outcome(code, name)
    return Outcome(0)
