"""Was this hook started by ``git push --dry-run``? git does not say, so look at the ancestors.

git runs ``pre-push`` for ``git push --dry-run`` too and gives the hook no flag for it. The hook
reads the command lines of its ancestors (``/proc``, Linux only) up to the first ``git push`` and
parses that command line the way ``git push`` does (``-n``, ``--dry-run``, ``--no-dry-run``, an
unambiguous abbreviation, grouped short flags, options that take a separate value).

The answer can only err toward a dry run, and a dry run exits 0 only when nothing would have to run
(``dry_run_exit``), so a wrong guess never lets an unchecked push through. Where ``/proc`` is
missing or unreadable the answer is False and the hook behaves as it does for a real push.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

PROC: Final = Path("/proc")
MAX_DEPTH: Final = 8
#: Options of git itself (before the subcommand) that take their value as the next argument.
GIT_VALUE_OPTIONS: Final = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
)
#: Options of ``git push`` that take their value as the next argument.
PUSH_VALUE_OPTIONS: Final = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})
DRY_RUN: Final = "--dry-run"
NO_DRY_RUN: Final = "--no-dry-run"
#: Shortest abbreviations git accepts without ambiguity (``--d`` could be ``--delete``).
DRY_RUN_MIN: Final = 4
NO_DRY_RUN_MIN: Final = 7


def push_arguments(argv: Sequence[str]) -> list[str] | None:
    """The arguments after ``push`` when ``argv`` is a ``git push`` command line, else None."""
    if not argv or Path(argv[0]).name != "git":
        return None
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == "push":
            return list(argv[index + 1 :])
        if not word.startswith("-"):
            return None
        index += 2 if word in GIT_VALUE_OPTIONS else 1
    return None


def short_flags(flags: str) -> tuple[bool, bool]:
    """For the letters of ``-xyz``: (``n`` seen, the value of ``-o`` is the next argument)."""
    dry = False
    for position, letter in enumerate(flags):
        if letter == "o":
            return dry, position == len(flags) - 1
        dry = dry or letter == "n"
    return dry, False


def long_flag(arg: str, current: bool) -> bool:
    """The dry-run state after the long option ``arg`` (``current`` when it is another option)."""
    name = arg.split("=", 1)[0]
    if len(name) >= DRY_RUN_MIN and DRY_RUN.startswith(name):
        return True
    if len(name) >= NO_DRY_RUN_MIN and NO_DRY_RUN.startswith(name):
        return False
    return current


def asks_for_dry_run(args: Sequence[str]) -> bool:
    """Whether the arguments of ``git push`` end up asking for a dry run (the last word wins)."""
    dry = False
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg == "--":
            break
        elif arg in PUSH_VALUE_OPTIONS:
            skip = True
        elif arg.startswith("--"):
            dry = long_flag(arg, dry)
        elif arg.startswith("-") and arg != "-":
            asked, skip = short_flags(arg[1:])
            dry = dry or asked
    return dry


def read_cmdline(pid: int, proc: Path) -> list[str]:
    """The arguments of process ``pid`` (empty when it is gone or unreadable)."""
    try:
        raw = (proc / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def parent_of(pid: int, proc: Path) -> int | None:
    """The parent of process ``pid`` from ``stat`` (the name field may hold spaces and ``)``)."""
    try:
        text = (proc / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields = text.rpartition(")")[2].split()
    try:
        return int(fields[1])
    except IndexError, ValueError:
        return None


def invoked_by_dry_run_push(start: int | None = None, proc: Path = PROC) -> bool:
    """Whether the nearest ``git push`` above ``start`` (default: our parent) is a dry run."""
    pid = os.getppid() if start is None else start
    for _ in range(MAX_DEPTH):
        if pid <= 1:
            return False
        args = push_arguments(read_cmdline(pid, proc))
        if args is not None:
            return asks_for_dry_run(args)
        parent = parent_of(pid, proc)
        if parent is None:
            return False
        pid = parent
    return False
