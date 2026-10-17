# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Check that requirements.txt is what ``uv export`` writes from uv.lock (runtime packages only).

    uv run python scripts/check_requirements.py            # fail when the file is out of date
    uv run python scripts/check_requirements.py --write    # rewrite it (``make requirements``)

GitHub's dependency graph does not read uv.lock, so Dependabot sees no Python package. The file is a
generated copy of the locked runtime packages, with hashes, that GitHub does read. Comment lines are
left out of the comparison, so a newer uv that words its header differently does not fail the check.

Exit status: 0 in step (or written), 1 out of date or missing, 2 uv failed.
"""

from __future__ import annotations

import argparse
import difflib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

ROOT: Final = Path(__file__).resolve().parent.parent
TARGET_NAME: Final = "requirements.txt"
EXPORT_ARGS: Final = (
    "export",
    "--locked",
    "--no-dev",
    "--no-emit-project",
    "--format",
    "requirements-txt",
)
DIFF_LINES: Final = 40

type Runner = Callable[..., subprocess.CompletedProcess[str]]


class ExportError(Exception):
    """``uv export`` could not run or failed."""


def run_export(root: Path, runner: Runner = subprocess.run) -> str:
    """The text ``uv export`` writes for the runtime packages locked in ``root``/uv.lock."""
    uv = shutil.which("uv")
    if uv is None:
        msg = "uv is not on PATH"
        raise ExportError(msg)
    done = runner([uv, *EXPORT_ARGS], cwd=root, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        msg = done.stderr.strip() or f"uv exited with status {done.returncode}"
        raise ExportError(msg)
    return done.stdout


def significant(text: str) -> list[str]:
    """The lines that matter: no blank lines and no comments (the header, the ``# via`` notes)."""
    return [
        ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    ]


def drift(expected: str, actual: str) -> list[str]:
    """A unified diff from the committed file to the export; empty when they agree."""
    return list(
        difflib.unified_diff(
            significant(actual), significant(expected), TARGET_NAME, "uv export", lineterm="", n=1
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--write", action="store_true", help="rewrite requirements.txt")
    return parser


def report_drift(changes: list[str]) -> None:
    """Print the first lines of the diff and how to fix it."""
    print(f"{TARGET_NAME} is out of date with uv.lock:", file=sys.stderr)
    for line in changes[:DIFF_LINES]:
        print(line, file=sys.stderr)
    if len(changes) > DIFF_LINES:
        print(f"... {len(changes) - DIFF_LINES} more lines", file=sys.stderr)
    print(f"Run `make requirements` and commit {TARGET_NAME} with uv.lock.", file=sys.stderr)


def main(
    argv: Sequence[str] | None = None, root: Path = ROOT, runner: Runner = subprocess.run
) -> int:
    args = build_parser().parse_args(argv)
    try:
        expected = run_export(root, runner)
    except ExportError as err:
        print(f"{TARGET_NAME}: uv export failed: {err}", file=sys.stderr)
        return 2
    target = root / TARGET_NAME
    if args.write:
        target.write_text(expected, encoding="utf-8")
        print(f"{TARGET_NAME} written from uv.lock")
        return 0
    if not target.is_file():
        print(f"{TARGET_NAME} is missing. Run `make requirements`.", file=sys.stderr)
        return 1
    changes = drift(expected, target.read_text(encoding="utf-8"))
    if changes:
        report_drift(changes)
        return 1
    print(f"{TARGET_NAME} is in step with uv.lock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
