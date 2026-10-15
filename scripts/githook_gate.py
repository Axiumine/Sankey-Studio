"""Git-hook gate: the logic behind .githooks/pre-commit, pre-merge-commit and pre-push.

    uv run --no-project --python 3.14 python -m scripts.githook_gate <command> [args]

Commands:

* ``pre-commit`` / ``pre-merge-commit``  run the ``fast`` check on the index tree
* ``pre-push [remote [url]]``  read git's ref lines on stdin; check the commit messages of the new
  commits, then run every check without a stamp for the pushed trees (see githook_push.py)
* ``run <check|tier>... [--force]``  run those checks on HEAD's tree (what ``make gate-*`` calls)
* ``plan <check|tier|pre-commit|pre-merge-commit|pre-push [remote]>``  print what would run
* ``hooks-check``  verify core.hooksPath and the hook file modes

Exit status: 0 all required checks are stamped or passed; 1 refused or a check failed (a failing
git call or an OS error on the stamp, log or lock files is a refusal: ``gate: refusing: ...``);
2 bad arguments; 128 + N a signal stopped the run. Any other failure of the gate itself (an
uncaught exception) also exits non-zero, so a hook can never pass by crashing.

Environment: ``SANKEY_GATE_DRY_RUN=1`` prints the plan and runs nothing; the exit status is then
0 only when nothing would have to run, so it cannot be used to get past a hook. A ``pre-push``
that ``git push --dry-run`` (or ``-n``) started behaves the same way; the gate finds out from the
command lines of its ancestors (see githook_parent.py).
Standard library only; every check runs through the Makefile (``make <target>``).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from scripts import githook_messages as msg
from scripts.githook_exec import Gate
from scripts.githook_flows import (
    commit_hook,
    hooks_check,
    plan_commit,
    plan_names,
    run_names,
)
from scripts.githook_git import GitError, Repo
from scripts.githook_push import pre_push
from scripts.githook_runner import GateInterruptedError, SubprocessRunner, install_gate_signals

if TYPE_CHECKING:
    from collections.abc import Sequence

COMMIT_HOOKS: Final = ("pre-commit", "pre-merge-commit")
DEFAULT_REMOTE: Final = "origin"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="githook_gate", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for hook in COMMIT_HOOKS:
        commands.add_parser(hook)
    push = commands.add_parser("pre-push")
    push.add_argument("remote", nargs="?", default=DEFAULT_REMOTE)
    push.add_argument("url", nargs="?", default="")
    run = commands.add_parser("run")
    run.add_argument("names", nargs="+")
    run.add_argument("--force", action="store_true", help="run even when a stamp exists")
    plan = commands.add_parser("plan")
    plan.add_argument("names", nargs="+")
    commands.add_parser("hooks-check")
    return parser


def plan_subject(gate: Gate, names: Sequence[str], stdin: TextIO) -> int:
    """``plan``: a hook name (reads stdin for pre-push) or checks/tiers; always exits 0."""
    first, rest = names[0], names[1:]
    if first in COMMIT_HOOKS:
        return plan_commit(gate, first)
    if first == "pre-push":
        remote = rest[0] if rest else DEFAULT_REMOTE
        pre_push(gate, remote, stdin.read(), dry_run=True)
        return 0
    return plan_names(gate, names)


def dispatch(gate: Gate, args: argparse.Namespace, stdin: TextIO) -> int:
    match args.command:
        case "pre-commit" | "pre-merge-commit":
            return commit_hook(gate, args.command)
        case "pre-push":
            return pre_push(gate, args.remote, stdin.read())
        case "run":
            return run_names(gate, args.names, force=args.force)
        case "plan":
            return plan_subject(gate, args.names, stdin)
        case _:
            return hooks_check(gate)


def make_gate(command: str) -> Gate:
    """The real gate: this repository, real processes; plan and hooks-check talk on stdout."""
    repo = Repo.discover(Path.cwd(), os.environ)
    out = sys.stdout if command in {"plan", "hooks-check"} else sys.stderr
    return Gate(repo, SubprocessRunner(), out, dict(os.environ), label=command)


def main(
    argv: Sequence[str] | None = None, *, gate: Gate | None = None, stdin: TextIO | None = None
) -> int:
    """Entry point; ``gate`` and ``stdin`` let tests inject a fake runner and ref lines."""
    args = build_parser().parse_args(argv)
    try:
        return dispatch(gate or make_gate(args.command), args, stdin or sys.stdin)
    except GateInterruptedError as stop:
        sys.stderr.write(msg.INTERRUPTED.format(signum=stop.code - 128) + "\n")
        return stop.code
    except (GitError, ValueError, OSError) as error:
        sys.stderr.write(msg.INTERNAL.format(error=error) + "\n")
        return 1


if __name__ == "__main__":
    install_gate_signals()
    sys.exit(main())
