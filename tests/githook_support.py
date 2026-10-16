# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers of the git-hook gate tests: throw-away git repos, a scripted Runner, a ready Gate.

Nothing here runs a hook, docker or a real check: the Runner is a fake that records the commands
and writes JUnit reports, and every git call happens in a repository below ``tmp_path``.
"""

from __future__ import annotations

import html
import io
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, TextIO

from scripts.githook_exec import CheckRun, Gate, Target
from scripts.githook_flows import head_target
from scripts.githook_git import Repo, run_git
from scripts.githook_plan import CHECKS
from scripts.githook_stamps import Stamp

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from scripts.githook_runner import Command

REPO_ROOT = Path(__file__).resolve().parent.parent
if REPO_ROOT.name == "mutants":  # mutmut runs the tests from <root>/mutants
    REPO_ROOT = REPO_ROOT.parent
ZERO = "0" * 40
NOW = datetime(2026, 10, 15, 12, 30, tzinfo=UTC)
JUNIT_ARG = "JUNIT="
PING_SCRIPT = "scripts/mongo_wait.py"
FINISHED = "2026-10-15T12:00:00Z"


# --------------------------------------------------------------------------- tables


@dataclass(frozen=True)
class Case[G, E]:
    """One row of a parametrised table: ``given`` goes in, ``expected`` must come out."""

    given: G
    expected: E
    name: str = ""


def case_id(case: Case[Any, Any]) -> str:
    return case.name or repr(case.given)


def alive(pid: int) -> bool:
    """False once the process is gone or only a zombie waiting to be reaped (Linux /proc)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] not in {"Z", "X"}


# --------------------------------------------------------------------------- git


def git_env() -> dict[str, str]:
    """A hermetic git environment: no user config, no inherited repository variables."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "LANGUAGE"}
    env.update(
        LC_ALL="C",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.com",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.com",
    )
    return env


def git(path: Path, *args: str) -> str:
    """Run git in ``path``; stdout without the trailing newline. A failure raises."""
    done = run_git(args, path, git_env())
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr}")
    return done.stdout.strip()


def init_repo(path: Path) -> Repo:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    return Repo.discover(path, git_env())


def commit_file(
    path: Path, name: str = "a.txt", text: str = "x\n", message: str = "feat: add a file"
) -> str:
    """Write ``name``, commit everything, return the new commit sha."""
    (path / name).write_text(text, encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD")


def push_line(local_ref: str, local_sha: str, remote_ref: str, remote_sha: str = ZERO) -> str:
    """One stdin line of the pre-push hook."""
    return f"{local_ref} {local_sha} {remote_ref} {remote_sha}\n"


# --------------------------------------------------------------------------- junit


def junit_xml(tests: int = 3, skips: Sequence[str] = (), *, closed: bool = True) -> str:
    """A pytest-style JUnit report: ``tests`` passing cases plus one skipped case per reason."""
    cases = [
        f'<testcase classname="tests.test_ok" name="test_{i}" time="0.001"/>' for i in range(tests)
    ]
    for index, reason in enumerate(skips):
        message = html.escape(reason, quote=True)
        cases.append(
            f'<testcase classname="tests.test_skip" name="test_skip_{index}" time="0.0">'
            f'<skipped type="pytest.skip" message="{message}">file.py:1: {message}</skipped>'
            "</testcase>"
        )
    body = "".join(cases)
    head = '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
    suite = f'<testsuite name="pytest" tests="{tests + len(skips)}">{body}'
    return head + suite + ("</testsuite></testsuites>" if closed else "")


# --------------------------------------------------------------------------- fake runner


def label_of(argv: Sequence[str]) -> str:
    """Short name of a command: the make target, ``ping-once``/``ping-wait``, or the argv."""
    if argv[0] == "make":
        return argv[1]
    if PING_SCRIPT in argv:
        return "ping-once" if argv[-1] == "0" else "ping-wait"
    return " ".join(argv)


def report_dir_of(argv: Sequence[str]) -> Path | None:
    """The directory named by a ``JUNIT=<dir>/report.xml`` argument, if there is one."""
    for arg in argv:
        if arg.startswith(JUNIT_ARG):
            return Path(arg.removeprefix(JUNIT_ARG)).parent
    return None


@dataclass
class FakeRunner:
    """A scripted ``Runner``: records every command, writes reports, returns scripted codes.

    ``codes``, ``skips``, ``reports`` and ``effects`` are keyed by ``label_of(argv)``.
    A ``reports`` value of None means "write no report"; a string is the raw report text.
    """

    codes: dict[str, int] = field(default_factory=dict)
    skips: dict[str, tuple[str, ...]] = field(default_factory=dict)
    reports: dict[str, str | None] = field(default_factory=dict)
    effects: dict[str, Callable[[], object]] = field(default_factory=dict)
    calls: list[Command] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [label_of(call.argv) for call in self.calls]

    def commands(self, label: str) -> list[Command]:
        return [call for call in self.calls if label_of(call.argv) == label]

    def run(self, command: Command, log: BinaryIO, echo: TextIO) -> int:
        label = label_of(command.argv)
        self.calls.append(command)
        line = f"fake output of {label}\n"
        log.write(line.encode())
        echo.write(line)
        if label in self.effects:
            self.effects[label]()
        self._write_report(label, command.argv)
        return self.codes.get(label, 0)

    def _write_report(self, label: str, argv: Sequence[str]) -> None:
        folder = report_dir_of(argv)
        if folder is None:
            return
        text = self.reports.get(label, junit_xml(skips=self.skips.get(label, ())))
        if text is not None:
            assert folder.is_dir(), f"the gate must create {folder} before the step runs"
            (folder / "report.xml").write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- clock, judge, rig


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@dataclass
class Ticker:
    """A monotonic clock that moves ``step`` seconds on every reading."""

    step: float = 2.0
    value: float = 0.0

    def __call__(self) -> float:
        self.value += self.step
        return self.value


@dataclass
class Judge:
    """A stand-in for ``.githooks/commit-msg``: refuses every message that starts with ``bad``."""

    seen: list[str] = field(default_factory=list)

    def __call__(self, repo: Repo, message: str) -> tuple[int, str]:
        del repo
        self.seen.append(message.strip())
        if message.startswith("bad"):
            return 1, f"refused: {message.strip()}\nsecond line"
        return 0, ""


@dataclass
class Rig:
    """A repository with one commit on ``main`` and a Gate wired to fakes."""

    repo: Repo
    gate: Gate
    runner: FakeRunner
    out: io.StringIO
    clock: Clock
    judge: Judge

    @property
    def root(self) -> Path:
        return self.repo.root

    @property
    def text(self) -> str:
        return self.out.getvalue()

    def git(self, *args: str) -> str:
        return git(self.repo.root, *args)

    def tree(self, rev: str = "HEAD") -> str:
        return self.git("rev-parse", f"{rev}^{{tree}}")

    def stamp(self, name: str, tree: str) -> Path:
        """Write a valid stamp of check ``name`` for ``tree`` (key as the gate computes it now)."""
        key = self.gate.key_for(name, tree)
        return self.gate.store.write(Stamp(name, key, tree, FINISHED, 1.5, ()))

    def stamp_all(self, names: Sequence[str], tree: str) -> None:
        for name in names:
            self.stamp(name, tree)

    def stamped(self, name: str, tree: str) -> bool:
        return self.gate.stamp_of(name, tree) is not None


def make_rig(tmp_path: Path, environ: Mapping[str, str] | None = None) -> Rig:
    """Repository ``tmp_path/work`` (one commit) and a Gate with a fake runner, clock and judge."""
    root = tmp_path / "work"
    init_repo(root)
    commit_file(root, "a.txt", "one\n", "chore: first commit")
    repo = Repo.discover(root, git_env())
    runner, out, clock, judge = FakeRunner(), io.StringIO(), Clock(), Judge()
    env = dict(environ) if environ is not None else {"PATH": "/usr/bin:/bin"}
    gate = Gate(
        repo,
        runner,
        out,
        env,
        clock=clock,
        tick=Ticker(),
        home=tmp_path / "home",
        check_message=judge,
        git_dry_run=lambda: False,
    )
    return Rig(repo, gate, runner, out, clock, judge)


def run_check(rig: Rig, name: str, target: Target | None = None) -> int:
    """Execute one check on HEAD's tree (or ``target``); the code ``CheckRun.execute`` returns."""
    return CheckRun(rig.gate, CHECKS[name], target or head_target(rig.gate)).execute()


def log_of(rig: Rig, name: str) -> Path:
    return rig.gate.log_dir / f"{name}.log"


def all_check_names() -> tuple[str, ...]:
    return tuple(CHECKS)
