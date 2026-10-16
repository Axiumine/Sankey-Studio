# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Policy: the comments and settings that weaken a quality gate are rationed and justified.

Rules (SPEC section 7, QUALITY.md sections 2 and 4), enforced over ``src``, ``tests`` and
``scripts`` by reading real comment tokens (a directive inside a string is not a directive):

* ``pragma: no cover`` - at most ``MAX_NO_COVER`` in the whole repo, each as
  ``pragma: no cover - <reason>``.
* ``pragma: no mutate`` - only ``pragma: no mutate block - <reason>`` on a ``Protocol`` class.
* ``nosemgrep`` - exactly one rule id and `` -- <reason>``; the ``sankey-no-mongo-writes`` waiver
  only under ``src/sankey_studio/storage/``; never in templates or static assets.
* ``type: ignore`` - only in tests, only with an error code (``[arg-type]``).
* ``noqa`` - rule codes and `` - <reason>``; never file-level, never bare.
* test marks - no ``skip`` / ``xfail``; ``skipif`` carries a ``reason``.
* the coverage exclusion regexes must not hide a line that merely contains three dots.

The scan of the real tree is at the bottom; every rule also has a table of accepted and refused
spellings, so a weakened checker fails here instead of letting a violation through.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pytest

MAX_NO_COVER = 5
SCANNED_DIRS = ("src", "tests", "scripts")
STORAGE_DIR = "src/sankey_studio/storage/"
MONGO_WRITE_RULE = "sankey-no-mongo-writes"
NON_TEXT_SUFFIXES = frozenset({".py", ".pyc", ".png", ".ico", ".woff", ".woff2", ".gif", ".jpg"})


def repo_root() -> Path:
    """The real repo root, also when mutmut runs these tests from ``<root>/mutants``.

    The generated copy under ``mutants/src`` is full of mutmut's own ``type: ignore`` lines, so
    the scan must look at the pristine tree one level up.
    """
    here = Path(__file__).resolve().parents[1]
    return here.parent if here.name == "mutants" else here


ROOT = repo_root()


@dataclass(frozen=True, slots=True)
class Comment:
    """One ``#`` comment: where it is, its text and the code that precedes it on the line."""

    path: str
    line: int
    text: str
    code: str

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"


def comments_of(path: str, source: str) -> list[Comment]:
    """Every comment token of ``source`` (strings that look like comments are not tokens)."""
    lines = source.splitlines()
    found = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, col = token.start
            found.append(Comment(path, row, token.string, lines[row - 1][:col]))
    return found


# --------------------------------------------------------------------------- checkers

NO_COVER = re.compile(r"#\s*pragma:\s*no cover\b")
NO_COVER_OK = re.compile(r"#\s*pragma: no cover - \S")
NO_MUTATE = re.compile(r"#\s*pragma:\s*no mutate\b")
NO_MUTATE_OK = re.compile(r"#\s*pragma: no mutate block - \S")
PROTOCOL_CLASS = re.compile(r"^\s*class \w+\([^)]*\bProtocol\b[^)]*\):\s*$")
NOSEMGREP = re.compile(r"#\s*nosemgrep\b")
NOSEMGREP_OK = re.compile(r"#\s*nosemgrep: ([A-Za-z0-9_.-]+) -- \S")
TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore\b")
TYPE_IGNORE_OK = re.compile(r"#\s*type: ignore\[[a-z][a-z-]*(?:, ?[a-z][a-z-]*)*\]")
FILE_NOQA = re.compile(r"#\s*(?:ruff|flake8):\s*noqa\b")
NOQA = re.compile(r"#\s*noqa\b")
NOQA_OK = re.compile(r"#\s*noqa: [A-Z]+[0-9]+(?:, [A-Z]+[0-9]+)* - \S")


def cover_problems(comment: Comment) -> list[str]:
    hits = NO_COVER.finditer(comment.text)
    return [
        f"{comment.where}: 'pragma: no cover' needs ' - <reason>'"
        for hit in hits
        if not NO_COVER_OK.match(comment.text, hit.start())
    ]


def mutate_problems(comment: Comment) -> list[str]:
    problems = []
    for hit in NO_MUTATE.finditer(comment.text):
        if not NO_MUTATE_OK.match(comment.text, hit.start()):
            problems.append(f"{comment.where}: use 'pragma: no mutate block - <reason>'")
        elif PROTOCOL_CLASS.match(comment.code) is None:
            problems.append(f"{comment.where}: 'no mutate' is only for a Protocol class line")
    return problems


def semgrep_problems(comment: Comment) -> list[str]:
    problems = []
    for hit in NOSEMGREP.finditer(comment.text):
        ok = NOSEMGREP_OK.match(comment.text, hit.start())
        if ok is None:
            problems.append(f"{comment.where}: 'nosemgrep: <one-rule-id> -- <reason>' required")
        elif ok.group(1) == MONGO_WRITE_RULE and not comment.path.startswith(STORAGE_DIR):
            problems.append(f"{comment.where}: {MONGO_WRITE_RULE} may be waived in storage/ only")
    return problems


def type_ignore_problems(comment: Comment) -> list[str]:
    problems = []
    for hit in TYPE_IGNORE.finditer(comment.text):
        if not comment.path.startswith("tests/"):
            problems.append(f"{comment.where}: 'type: ignore' is for tests only")
        elif not TYPE_IGNORE_OK.match(comment.text, hit.start()):
            problems.append(f"{comment.where}: 'type: ignore' needs an error code in brackets")
    return problems


def noqa_problems(comment: Comment) -> list[str]:
    problems = [f"{comment.where}: file-level noqa" for _ in FILE_NOQA.finditer(comment.text)]
    problems += [
        f"{comment.where}: 'noqa: CODE - <reason>' required"
        for hit in NOQA.finditer(comment.text)
        if not NOQA_OK.match(comment.text, hit.start())
    ]
    return problems


CHECKERS = (cover_problems, mutate_problems, semgrep_problems, type_ignore_problems, noqa_problems)


def directive_problems(path: str, source: str) -> list[str]:
    """Every rule violation in the comments of ``source`` (``path`` is relative to the root)."""
    return [
        problem
        for comment in comments_of(path, source)
        for check in CHECKERS
        for problem in check(comment)
    ]


def mark_problems(path: str, source: str) -> list[str]:
    """``mark.skip`` / ``mark.xfail`` anywhere, and ``skipif`` without a ``reason``."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and _is_mark(node, {"skip", "xfail"}):
            problems.append(f"{path}:{node.lineno}: no skip/xfail marks (use skipif + reason)")
        if isinstance(node, ast.Call) and _skipif_without_reason(node):
            problems.append(f"{path}:{node.lineno}: skipif needs reason=")
    return problems


def _skipif_without_reason(call: ast.Call) -> bool:
    return _is_mark(call.func, {"skipif"}) and "reason" not in {kw.arg for kw in call.keywords}


def _is_mark(node: ast.expr, names: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in names
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
    )


def count_no_cover(path: str, source: str) -> int:
    return sum(len(NO_COVER.findall(c.text)) for c in comments_of(path, source))


# --------------------------------------------------------------------------- the real tree


@cache
def python_sources() -> dict[str, str]:
    """``{relative posix path: text}`` for every scanned ``.py`` file."""
    files = {}
    for name in SCANNED_DIRS:
        for path in sorted((ROOT / name).rglob("*.py")):
            if "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return files


def test_the_scan_sees_the_real_tree() -> None:
    files = python_sources()
    assert {"src/sankey_studio/mongo.py", "tests/test_policy.py", "scripts/mutation_gate.py"} <= (
        files.keys()
    )
    assert not [p for p in files if {"mutants", ".venv", "__pycache__"} & set(Path(p).parts)]
    assert len(files) > 50


def test_no_cover_pragmas_are_few_and_justified() -> None:
    files = python_sources()
    assert sum(count_no_cover(path, text) for path, text in files.items()) <= MAX_NO_COVER


def test_every_suppression_comment_follows_the_policy() -> None:
    problems = [
        problem
        for path, text in python_sources().items()
        for problem in directive_problems(path, text)
    ]
    assert problems == []


def test_no_unconditional_skip_or_xfail_marks() -> None:
    problems = [
        problem for path, text in python_sources().items() for problem in mark_problems(path, text)
    ]
    assert problems == []


def test_templates_and_static_assets_carry_no_semgrep_waiver() -> None:
    assets = [
        path
        for path in sorted((ROOT / "src").rglob("*"))
        if path.is_file() and path.suffix not in NON_TEXT_SUFFIXES
    ]
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in assets
        if "nosemgrep" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == []


# --------------------------------------------------------------------------- coverage config


@cache
def coverage_config() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        tool: dict[str, Any] = tomllib.load(handle)["tool"]
    coverage: dict[str, Any] = tool["coverage"]
    return coverage


def test_coverage_is_strict_and_branch_aware() -> None:
    config = coverage_config()
    assert config["run"]["branch"] is True
    assert config["report"]["fail_under"] == 100


def test_the_ellipsis_exclusion_does_not_hide_lines_that_merely_contain_dots() -> None:
    patterns: list[str] = coverage_config()["report"]["exclude_also"]
    hidden = ['more = f"... and {n} more"', "text = 'wait...'", "x = [...]", "# ... later"]
    for line in hidden:
        assert not [p for p in patterns if re.search(p, line, re.MULTILINE)], line
    shown = ["    ...", "def f(self) -> int: ...", "class P(Protocol): ..."]
    for line in shown:
        assert [p for p in patterns if re.search(p, line, re.MULTILINE)], line


# --------------------------------------------------------------------------- the checkers

SRC = "src/sankey_studio/x.py"
TESTS = "tests/test_x.py"
STORE = "src/sankey_studio/storage/mongo_store.py"
PROTOCOL = "class Repo(Protocol):  "


@pytest.mark.parametrize(
    ("path", "line"),
    [
        (SRC, "x = 1  # pragma: no cover - unreachable: the enum is exhaustive"),
        (SRC, f"{PROTOCOL}# pragma: no mutate block - interface only"),
        (STORE, "coll.insert_one(d)  # nosemgrep: sankey-no-mongo-writes -- the graph store"),
        (SRC, "x = f()  # nosemgrep: some.rule-id -- reason, with commas"),
        (TESTS, "f(1)  # type: ignore[arg-type]"),
        (TESTS, "f(1)  # type: ignore[arg-type,return-value]"),
        (TESTS, "f(1)  # type: ignore[arg-type, misc]"),
        (SRC, "x = 1  # noqa: S104 - wildcard bind we refuse"),
        (SRC, "x = 1  # noqa: PLR2004, ARG002 - two codes, one reason"),
        (TESTS, "f(1)  # type: ignore[arg-type]  # noqa: S104 - both, each correct"),
        (SRC, "x = 'not a comment  # noqa'"),
        (SRC, "x = '# type: ignore'"),
        (SRC, "# plain comment about no cover and mutate"),
    ],
)
def test_compliant_directives_are_accepted(path: str, line: str) -> None:
    assert directive_problems(path, line + "\n") == []


@pytest.mark.parametrize(
    ("path", "line", "fragment"),
    [
        (SRC, "x = 1  # pragma: no cover", "'pragma: no cover' needs"),
        (SRC, "x = 1  # pragma: no cover -", "'pragma: no cover' needs"),
        (SRC, "x = 1  # pragma: no cover: because", "'pragma: no cover' needs"),
        (SRC, "x = 1  # pragma: no mutate", "use 'pragma: no mutate block"),
        (SRC, "x = 1  # pragma: no mutate block", "use 'pragma: no mutate block"),
        (SRC, "x = 1  # pragma: no mutate block - nope", "only for a Protocol class"),
        (SRC, "def f():  # pragma: no mutate block - nope", "only for a Protocol class"),
        (SRC, "class Plain:  # pragma: no mutate block - nope", "only for a Protocol class"),
        (SRC, "x = 1  # nosemgrep", "'nosemgrep: <one-rule-id> -- <reason>' required"),
        (SRC, "x = 1  # nosemgrep: a-rule", "'nosemgrep: <one-rule-id>"),
        (SRC, "x = 1  # nosemgrep: a-rule - reason", "'nosemgrep: <one-rule-id>"),
        (SRC, "x = 1  # nosemgrep: a-rule --", "'nosemgrep: <one-rule-id>"),
        (SRC, "x = 1  # nosemgrep: a-rule, b-rule -- reason", "'nosemgrep: <one-rule-id>"),
        (SRC, "x = 1  # nosemgrep: sankey-no-mongo-writes -- r", "may be waived in storage/ only"),
        (
            TESTS,
            "x = 1  # nosemgrep: sankey-no-mongo-writes -- r",
            "may be waived in storage/ only",
        ),
        (SRC, "x = 1  # type: ignore", "is for tests only"),
        (SRC, "x = 1  # type: ignore[arg-type]", "is for tests only"),
        ("scripts/x.py", "x = 1  # type: ignore[arg-type]", "is for tests only"),
        (TESTS, "x = 1  # type: ignore", "needs an error code"),
        (TESTS, "x = 1  # type:ignore", "needs an error code"),
        (TESTS, "x = 1  # type: ignore[]", "needs an error code"),
        (TESTS, "x = 1  # type: ignore  # because", "needs an error code"),
        (SRC, "x = 1  # noqa", "'noqa: CODE - <reason>' required"),
        (SRC, "x = 1  # noqa: S104", "'noqa: CODE - <reason>' required"),
        (SRC, "x = 1  # noqa: S104 -", "'noqa: CODE - <reason>' required"),
        (SRC, "x = 1  # noqa:S104 - reason", "'noqa: CODE - <reason>' required"),
        (SRC, "x = 1  # noqa: s104 - reason", "'noqa: CODE - <reason>' required"),
        (SRC, "x = 1  # noqa: PLR2004, - reason", "'noqa: CODE - <reason>' required"),
        (TESTS, "x = 1  # noqa: S104", "'noqa: CODE - <reason>' required"),
        (TESTS, "# ruff: noqa: ARG002 - everything", "file-level noqa"),
        (TESTS, "# ruff: noqa", "file-level noqa"),
        (SRC, "# flake8: noqa", "file-level noqa"),
    ],
)
def test_violations_are_reported_with_their_location(path: str, line: str, fragment: str) -> None:
    problems = directive_problems(path, "import os\n\n" + line + "\n")
    assert len(problems) == 1, problems
    assert problems[0].startswith(f"{path}:3: ")
    assert fragment in problems[0]


def test_two_violations_on_one_line_are_both_reported() -> None:
    source = "x = 1  # type: ignore  # noqa\n"
    problems = directive_problems(TESTS, source)
    assert [p.split(": ", 1)[1] for p in problems] == [
        "'type: ignore' needs an error code in brackets",
        "'noqa: CODE - <reason>' required",
    ]


def test_no_cover_pragmas_are_counted_per_occurrence() -> None:
    source = "a = 1  # pragma: no cover - r\nb = 2\nc = 3  # pragma: no cover - r\n"
    assert count_no_cover(SRC, source) == 2
    assert count_no_cover(SRC, "s = '# pragma: no cover'\n") == 0


@pytest.mark.parametrize(
    "source",
    [
        "@pytest.mark.skip\ndef test_a() -> None: ...",
        "@pytest.mark.skip(reason='later')\ndef test_a() -> None: ...",
        "@pytest.mark.xfail\ndef test_a() -> None: ...",
        "pytestmark = pytest.mark.xfail(strict=True)",
        "@pytest.mark.skipif(sys.platform == 'win32')\ndef test_a() -> None: ...",
        "pytestmark = pytest.mark.skipif(not CHROME)",
    ],
)
def test_forbidden_marks_are_reported(source: str) -> None:
    assert len(mark_problems(TESTS, source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "@pytest.mark.skipif(not CHROME, reason='Chrome is not installed')\ndef test_a(): ...",
        "pytestmark = pytest.mark.skipif(True, reason='x')",
        "pytest.skip('no chrome')",
        "diag.skip('row 1')",
        "@pytest.mark.slow\ndef test_a() -> None: ...",
    ],
)
def test_allowed_marks_are_accepted(source: str) -> None:
    assert mark_problems(TESTS, source) == []
