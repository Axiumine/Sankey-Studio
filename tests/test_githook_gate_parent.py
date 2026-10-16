# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``git push --dry-run`` detection (scripts/githook_parent.py) and what pre-push does with it."""

from __future__ import annotations

import io
import os
import sys
from typing import TYPE_CHECKING

import pytest
from scripts import githook_gate as cli
from scripts import githook_messages as msg
from scripts import githook_parent as parent
from scripts import githook_push as push
from scripts.githook_exec import Gate

from tests.githook_support import Case, Rig, case_id, commit_file, make_rig, push_line

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

PUSH_TIER = ["fast", "cov", "memray", "e2e"]


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


# --------------------------------------------------------------------------- the command line

PUSH_ARGUMENTS = [
    Case(["git", "push"], [], "plain"),
    Case(["git", "push", "-n", "origin"], ["-n", "origin"], "arguments are returned"),
    Case(["/usr/lib/git-core/git", "push"], [], "full path of git"),
    Case(["git", "-C", "/x", "push", "--dry-run"], ["--dry-run"], "-C takes a value"),
    Case(["git", "-c", "push", "push"], [], "-c takes a value, even one named push"),
    Case(["git", "--no-pager", "push", "-n"], ["-n"], "a flag of git itself"),
    Case(["git", "--git-dir", "x", "push"], [], "--git-dir takes a value"),
    Case(["git", "commit", "-m", "push"], None, "another subcommand"),
    Case(["git", "status"], None, "status"),
    Case(["git"], None, "no subcommand"),
    Case(["git", "-C"], None, "a value option at the end"),
    Case(["bash", ".githooks/pre-push"], None, "the hook shim"),
    Case(["uv", "run", "python", "push"], None, "not git"),
    Case(["gitk", "push"], None, "a tool whose name starts with git"),
    Case([], None, "empty"),
]


@pytest.mark.parametrize("case", PUSH_ARGUMENTS, ids=case_id)
def test_the_arguments_of_git_push_are_found_in_a_command_line(
    case: Case[list[str], list[str] | None],
) -> None:
    assert parent.push_arguments(case.given) == case.expected


DRY_RUN_ARGUMENTS = [
    Case([], False, "no arguments"),
    Case(["origin", "main"], False, "only a remote and a branch"),
    Case(["-n"], True, "-n"),
    Case(["--dry-run"], True, "--dry-run"),
    Case(["--dry"], True, "an abbreviation"),
    Case(["--dr"], True, "the shortest unambiguous abbreviation"),
    Case(["--d"], False, "ambiguous with --delete, git refuses it"),
    Case(["--delete", "origin", "x"], False, "--delete"),
    Case(["--dryer"], False, "not a prefix of --dry-run"),
    Case(["--dry-run=1"], True, "a value is ignored"),
    Case(["-fn"], True, "grouped short flags, n last"),
    Case(["-nf"], True, "grouped short flags, n first"),
    Case(["-vn", "origin"], True, "grouped short flags with a remote"),
    Case(["-f"], False, "-f"),
    Case(["-u", "origin", "main"], False, "-u"),
    Case(["--no-dry-run"], False, "--no-dry-run alone"),
    Case(["--dry-run", "--no-dry-run"], False, "the last long option wins"),
    Case(["--dry-run", "--no-dry"], False, "an abbreviation of --no-dry-run wins"),
    Case(["--dry-run", "--no-dr"], False, "the shortest abbreviation of --no-dry-run"),
    Case(["--dry-run", "--no-d"], True, "too short, it is another option"),
    Case(["--no-dry-run", "-n"], True, "a later -n wins"),
    Case(["-n", "--no-dry-run"], False, "a later --no-dry-run wins"),
    Case(["--dry-run", "-f"], True, "another flag does not undo it"),
    Case(["--dry-run", "--force"], True, "another long flag does not undo it"),
    Case(["-o", "-n"], False, "the value of -o"),
    Case(["-on"], False, "an attached value of -o"),
    Case(["-onothing"], False, "an attached value of -o that holds an n"),
    Case(["-no", "x"], True, "-n then -o with its value apart"),
    Case(["--push-option", "-n"], False, "the value of --push-option"),
    Case(["--push-option=n"], False, "an attached --push-option"),
    Case(["--repo", "x", "-n"], True, "--repo takes a value, -n follows"),
    Case(["--receive-pack", "-n"], False, "the value of --receive-pack"),
    Case(["--exec", "-n"], False, "the value of --exec"),
    Case(["--", "-n"], False, "after -- everything is a refspec"),
    Case(["origin", "--", "--dry-run"], False, "a refspec after --"),
    Case(["-"], False, "a lone dash"),
]


@pytest.mark.parametrize("case", DRY_RUN_ARGUMENTS, ids=case_id)
def test_a_dry_run_is_recognised_as_git_push_reads_its_arguments(
    case: Case[list[str], bool],
) -> None:
    assert parent.asks_for_dry_run(case.given) is case.expected


SHORT_FLAGS = [
    Case("n", (True, False), "n"),
    Case("", (False, False), "nothing"),
    Case("fv", (False, False), "other letters"),
    Case("o", (False, True), "o takes the next argument"),
    Case("on", (False, False), "o with an attached value"),
    Case("no", (True, True), "n, then o with the value apart"),
    Case("fno", (True, True), "n in the middle"),
]


@pytest.mark.parametrize("case", SHORT_FLAGS, ids=case_id)
def test_grouped_short_flags_give_the_dry_run_and_whether_a_value_follows(
    case: Case[str, tuple[bool, bool]],
) -> None:
    assert parent.short_flags(case.given) == case.expected


LONG_FLAGS = [
    Case(("--dry-run", False), True, "--dry-run"),
    Case(("--dr", False), True, "shortest abbreviation"),
    Case(("--d", False), False, "one letter too short"),
    Case(("--d", True), True, "too short keeps the state"),
    Case(("--no-dry-run", True), False, "--no-dry-run"),
    Case(("--no-dr", True), False, "shortest abbreviation of the negation"),
    Case(("--no-d", True), True, "one letter too short keeps the state"),
    Case(("--force", True), True, "another option keeps True"),
    Case(("--force", False), False, "another option keeps False"),
    Case(("--dry-run=1", False), True, "a value after ="),
    Case(("--dryer", True), True, "not a prefix"),
]


@pytest.mark.parametrize("case", LONG_FLAGS, ids=case_id)
def test_a_long_option_moves_the_dry_run_state_only_when_it_is_the_dry_run_option(
    case: Case[tuple[str, bool], bool],
) -> None:
    arg, current = case.given
    assert parent.long_flag(arg, current) is case.expected


# --------------------------------------------------------------------------- the process tree


def write_process(root: Path, pid: int, ppid: int, argv: Sequence[str]) -> None:
    """One /proc entry: a ``cmdline`` of NUL-terminated words and a ``stat`` with an odd name."""
    folder = root / str(pid)
    folder.mkdir(parents=True)
    words = b"".join(word.encode() + b"\0" for word in argv)
    (folder / "cmdline").write_bytes(words)
    (folder / "stat").write_text(f"{pid} (odd ) name) S {ppid} {pid} 1 0 -1 0\n", encoding="utf-8")


def write_chain(root: Path, argvs: Sequence[Sequence[str]]) -> int:
    """Processes 100, 101, ... each the parent of the one before; the last one is a child of 1.

    Returns the pid of the first one (the innermost).
    """
    for index, argv in enumerate(argvs):
        last = index == len(argvs) - 1
        write_process(root, 100 + index, 1 if last else 101 + index, argv)
    return 100


HOOK_CHAIN = [["python", "-m", "scripts.githook_gate", "pre-push"], ["uv", "run"], ["bash", "x"]]


def test_the_nearest_git_push_above_the_hook_decides(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    chain = [*HOOK_CHAIN, ["git", "push", "--dry-run", "origin"], ["zsh"]]
    start = write_chain(root, chain)
    assert parent.invoked_by_dry_run_push(start, root) is True


def test_a_real_push_is_not_a_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    start = write_chain(root, [*HOOK_CHAIN, ["git", "push", "origin", "main"], ["zsh"]])
    assert parent.invoked_by_dry_run_push(start, root) is False


def test_a_dry_run_further_up_does_not_make_an_inner_real_push_a_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    start = write_chain(root, [*HOOK_CHAIN, ["git", "push"], ["git", "push", "-n"]])
    assert parent.invoked_by_dry_run_push(start, root) is False


def test_no_git_push_among_the_ancestors_is_no_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    start = write_chain(root, [*HOOK_CHAIN, ["git", "commit", "-n"], ["make", "gate-push"]])
    assert parent.invoked_by_dry_run_push(start, root) is False


@pytest.mark.parametrize(
    ("depth", "found"), [(parent.MAX_DEPTH, True), (parent.MAX_DEPTH + 1, False)]
)
def test_only_the_nearest_ancestors_are_searched(tmp_path: Path, depth: int, found: bool) -> None:
    root = tmp_path / "proc"
    chain = [["sh"]] * (depth - 1) + [["git", "push", "-n"], ["zsh"]]
    start = write_chain(root, chain)
    assert parent.invoked_by_dry_run_push(start, root) is found


def test_the_search_stops_at_process_one(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    write_process(root, 100, 1, ["sh"])
    write_process(root, 1, 0, ["git", "push", "-n"])
    assert parent.invoked_by_dry_run_push(100, root) is False
    assert parent.invoked_by_dry_run_push(1, root) is False


def test_a_vanished_process_or_a_missing_proc_is_no_dry_run(tmp_path: Path) -> None:
    assert parent.invoked_by_dry_run_push(4242, tmp_path / "nothing") is False
    root = tmp_path / "proc"
    root.mkdir()
    assert parent.invoked_by_dry_run_push(4242, root) is False


@pytest.mark.parametrize("stat_text", ["", "garbage", "5 (x) S", "5 (x) S notapid 1"])
def test_an_unreadable_stat_ends_the_search(tmp_path: Path, stat_text: str) -> None:
    root = tmp_path / "proc"
    write_process(root, 100, 101, ["sh"])
    (root / "100" / "stat").write_text(stat_text, encoding="utf-8")
    write_process(root, 101, 1, ["git", "push", "-n"])
    assert parent.parent_of(100, root) is None
    assert parent.invoked_by_dry_run_push(100, root) is False


def test_the_parent_is_read_after_the_last_bracket_of_the_name(tmp_path: Path) -> None:
    write_process(tmp_path, 100, 77, ["sh"])
    assert parent.parent_of(100, tmp_path) == 77
    assert parent.parent_of(5, tmp_path) is None


def test_a_command_line_is_split_on_nul_and_empty_words_are_dropped(tmp_path: Path) -> None:
    write_process(tmp_path, 7, 1, ["git", "push", "", "x"])
    assert parent.read_cmdline(7, tmp_path) == ["git", "push", "x"]
    (tmp_path / "7" / "cmdline").write_bytes(b"git\0caf\xe9\0")
    assert parent.read_cmdline(7, tmp_path) == ["git", "caf�"]
    assert parent.read_cmdline(8, tmp_path) == []


def test_by_default_the_search_starts_at_our_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "proc"
    write_chain(root, [["uv"], ["git", "push", "--dry-run"], ["zsh"]])
    monkeypatch.setattr(os, "getppid", lambda: 100)
    assert parent.invoked_by_dry_run_push(proc=root) is True
    monkeypatch.setattr(os, "getppid", lambda: 102)
    assert parent.invoked_by_dry_run_push(proc=root) is False


def test_the_default_proc_directory_is_the_linux_one() -> None:
    assert str(parent.PROC) == "/proc"


def test_the_real_proc_layout_is_the_one_the_parser_expects() -> None:
    expected = os.getppid() if sys.platform == "linux" else None
    assert parent.parent_of(os.getpid(), parent.PROC) == expected
    assert bool(parent.read_cmdline(os.getpid(), parent.PROC)) is (sys.platform == "linux")


# --------------------------------------------------------------------------- pre-push


def feature_push(rig: Rig) -> str:
    """stdin of a push of a new commit on ``feature``; HEAD ends on that commit."""
    rig.git("checkout", "-q", "-b", "feature")
    sha = commit_file(rig.root, "f.txt", "f\n", "feat: f")
    return push_line("refs/heads/feature", sha, "refs/heads/feature")


def test_the_gate_asks_git_push_dry_run_detection_by_default(tmp_path: Path) -> None:
    unused = make_rig(tmp_path)
    gate = Gate(unused.repo, unused.runner, io.StringIO(), {})
    assert gate.git_dry_run is parent.invoked_by_dry_run_push


def test_a_git_push_dry_run_prints_the_plan_runs_nothing_and_fails_with_work_pending(
    rig: Rig,
) -> None:
    text = feature_push(rig)
    rig.gate.git_dry_run = lambda: True
    assert push.pre_push(rig.gate, "origin", text) == 1
    lines = rig.text.splitlines()
    assert lines[0] == "gate: git push --dry-run: nothing is run and nothing is pushed"
    assert lines[0] == msg.PUSH_DRY_RUN
    assert lines[1].startswith("plan: commit messages of ")
    assert lines[-1] == "gate: dry run: 4 check(s) would run, nothing was run"
    assert rig.runner.calls == []
    assert rig.judge.seen[0] == "feat: f"
    assert not rig.gate.store.base.exists()
    assert not rig.gate.lock_path.exists()


def test_a_git_push_dry_run_passes_when_every_check_is_stamped(rig: Rig) -> None:
    text = feature_push(rig)
    rig.stamp_all(PUSH_TIER, rig.tree())
    rig.gate.git_dry_run = lambda: True
    assert push.pre_push(rig.gate, "origin", text) == 0
    assert rig.text.splitlines()[0] == msg.PUSH_DRY_RUN
    assert rig.runner.calls == []


def test_a_real_push_runs_the_checks_as_before(rig: Rig) -> None:
    text = feature_push(rig)
    assert push.pre_push(rig.gate, "origin", text) == 0
    assert rig.runner.labels == ["lint", "typecheck", "caps", "cov", "memray", "e2e"]
    assert msg.PUSH_DRY_RUN not in rig.text


def test_the_detection_is_asked_only_when_nothing_else_decided(rig: Rig) -> None:
    asked: list[int] = []

    def ask() -> bool:
        asked.append(1)
        return False

    rig.gate.git_dry_run = ask
    assert push.is_dry_run(rig.gate, True) is True
    assert push.is_dry_run(rig.gate, False) is False
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    assert push.is_dry_run(rig.gate, None) is True
    assert asked == []
    rig.gate.environ = {}
    assert push.is_dry_run(rig.gate, None) is False
    assert asked == [1]


def test_a_push_without_refs_does_not_look_for_a_dry_run(rig: Rig) -> None:
    rig.gate.git_dry_run = lambda: pytest.fail("must not be asked")
    assert push.pre_push(rig.gate, "origin", "") == 0
    assert rig.text == "gate: nothing to check, no ref is created or updated\n"


def test_the_command_line_pre_push_honours_the_detection(rig: Rig) -> None:
    text = feature_push(rig)
    rig.gate.git_dry_run = lambda: True
    assert cli.main(["pre-push", "origin"], gate=rig.gate, stdin=io.StringIO(text)) == 1
    assert rig.runner.calls == []
    assert msg.PUSH_DRY_RUN in rig.text


def test_plan_pre_push_never_asks_and_always_exits_zero(rig: Rig) -> None:
    text = feature_push(rig)
    rig.gate.git_dry_run = lambda: pytest.fail("must not be asked")
    assert cli.main(["plan", "pre-push"], gate=rig.gate, stdin=io.StringIO(text)) == 0
    assert msg.PUSH_DRY_RUN not in rig.text
    assert rig.runner.calls == []
