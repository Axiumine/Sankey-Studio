# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Pre-commit check 1.1 - code caps, measured on the AST, ratcheted against a baseline.

Caps (a value ABOVE the cap is a violation):

* file      500 lines
* function   50 lines (decorators included)
* class     300 lines (decorators included)
* params      4 per function (``self``/``cls`` of a method are not counted)
* nesting     4 levels of if/for/while/try/with/match inside one function

Ratchet: violations already listed in ``.code-caps-baseline.json`` are tolerated as long as they
do not GROW. A new violation, or a grown one, fails the check (exit 1) and blocks the commit.

    python3 scripts/check_code_caps.py                   # check the whole repo
    python3 scripts/check_code_caps.py --init            # create the baseline (first run only)
    python3 scripts/check_code_caps.py --update-baseline # ratchet DOWN; never adds a violation

Standard library only, so any ``python3`` can run it.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CAPS: dict[str, int] = {"file": 500, "function": 50, "class": 300, "params": 4, "nesting": 4}
BASELINE_NAME = ".code-caps-baseline.json"
BASELINE_VERSION = 1
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".gitnexus",
        ".claude",
        ".idea",
        "mutants",
        "node_modules",
        "build",
        "dist",
        "reports",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".memray",
        ".tox",
    }
)
BLOCK_NODES: tuple[type[ast.stmt], ...] = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Match,
    *((ast.TryStar,) if hasattr(ast, "TryStar") else ()),
)
DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
METHOD_FIRST_ARGS = frozenset({"self", "cls"})


@dataclass(frozen=True, slots=True)
class Measure:
    """One cap violation: where it is, what was measured."""

    path: str
    line: int
    kind: str
    name: str
    value: int

    @property
    def key(self) -> str:
        return f"{self.path}::{self.kind}::{self.name}"

    def describe(self) -> str:
        what = "file" if self.kind == "file" else f"{self.kind} '{self.name}'"
        unit = " lines" if self.kind in {"file", "function", "class"} else ""
        return f"{self.path}:{self.line}: {what} = {self.value}{unit} (cap {CAPS[self.kind]})"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Result of comparing current violations with the baseline."""

    new: tuple[Measure, ...]
    grown: tuple[tuple[Measure, int], ...]
    improved: tuple[tuple[str, int, int], ...]
    fixed: tuple[str, ...]

    @property
    def failed(self) -> bool:
        return bool(self.new or self.grown)


# --------------------------------------------------------------------------- AST measures


def span(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> tuple[int, int]:
    """First line (decorators included) and number of lines of a def/class."""
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    end = node.end_lineno if node.end_lineno is not None else node.lineno
    return start, end - start + 1


def count_params(node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_method: bool) -> int:
    """Parameters of ``node``; the leading ``self``/``cls`` of a method is free."""
    args = node.args
    names = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    if is_method and names and names[0].arg in METHOD_FIRST_ARGS:
        names = names[1:]
    return len(names) + (args.vararg is not None) + (args.kwarg is not None)


def child_blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """Statement lists directly owned by a block statement."""
    if isinstance(stmt, ast.Match):
        return [case.body for case in stmt.cases]
    blocks: list[list[ast.stmt]] = []
    for field in ("body", "orelse", "finalbody"):
        value = getattr(stmt, field, None)
        if isinstance(value, list) and value:
            blocks.append(value)
    blocks.extend(handler.body for handler in getattr(stmt, "handlers", []))
    return blocks


def is_elif(parent: ast.stmt, child: ast.stmt) -> bool:
    """An ``elif`` is an ``If`` in ``orelse`` written at the parent's own column."""
    return (
        isinstance(parent, ast.If)
        and isinstance(child, ast.If)
        and child.col_offset == parent.col_offset
    )


def nesting_depth(stmts: list[ast.stmt], depth: int = 0) -> int:
    """Deepest block nesting below ``stmts``; nested defs/classes are measured on their own."""
    best = depth
    for stmt in stmts:
        if isinstance(stmt, DEF_NODES) or not isinstance(stmt, BLOCK_NODES):
            continue
        for block in child_blocks(stmt):
            same_level = len(block) == 1 and is_elif(stmt, block[0])
            inner = nesting_depth(block, depth if same_level else depth + 1)
            best = max(best, inner, depth + 1)
    return best


# ast.NodeVisitor dispatches on the node class name, so the visit_* names are fixed.
# noinspection PyPep8Naming
class CapsVisitor(ast.NodeVisitor):
    """Collects violations of one module, tracking the qualified name of every def."""

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.found: list[Measure] = []
        self._scope: list[str] = []
        self._in_class: list[bool] = []

    def _record(self, line: int, kind: str, name: str, value: int) -> None:
        if value > CAPS[kind]:
            self.found.append(Measure(self.rel_path, line, kind, name, value))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        start, length = span(node)
        qualname = ".".join([*self._scope, node.name])
        self._record(start, "class", qualname, length)
        self._descend(node, node.name, is_class=True)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        start, length = span(node)
        qualname = ".".join([*self._scope, node.name])
        is_method = bool(self._in_class and self._in_class[-1])
        self._record(start, "function", qualname, length)
        self._record(start, "params", qualname, count_params(node, is_method=is_method))
        self._record(start, "nesting", qualname, nesting_depth(node.body))
        self._descend(node, node.name, is_class=False)

    def _descend(self, node: ast.AST, name: str, *, is_class: bool) -> None:
        self._scope.append(name)
        self._in_class.append(is_class)
        self.generic_visit(node)
        self._in_class.pop()
        self._scope.pop()


def dedupe_names(found: list[Measure]) -> list[Measure]:
    """Make keys unique when a qualname repeats (conditional redefinition): ``name#2``."""
    seen: dict[str, int] = {}
    result: list[Measure] = []
    for item in found:
        count = seen.get(item.key, 0) + 1
        seen[item.key] = count
        if count == 1:
            result.append(item)
        else:
            result.append(
                Measure(item.path, item.line, item.kind, f"{item.name}#{count}", item.value)
            )
    return result


def measure_source(source: str, rel_path: str) -> list[Measure]:
    """All violations in one module's source text. Raises ``SyntaxError`` on bad code."""
    found: list[Measure] = []
    lines = len(source.splitlines())
    if lines > CAPS["file"]:
        found.append(Measure(rel_path, 1, "file", "-", lines))
    visitor = CapsVisitor(rel_path)
    visitor.visit(ast.parse(source, filename=rel_path))
    return dedupe_names([*found, *visitor.found])


# --------------------------------------------------------------------------- repo walk


def git_python_files(root: Path) -> list[Path] | None:
    """Tracked + untracked-but-not-ignored ``*.py`` files, or ``None`` outside a git repo."""
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.py"]
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no user input
            cmd, cwd=root, capture_output=True, check=False
        )
    except OSError:
        return None
    if done.returncode != 0:
        return None
    names = [n for n in done.stdout.decode("utf-8", "surrogateescape").split("\0") if n]
    return [root / n for n in names]


def walk_python_files(root: Path) -> list[Path]:
    return [p for p in sorted(root.rglob("*.py")) if p.is_file()]


def python_files(root: Path) -> list[Path]:
    """Every repo ``*.py`` file outside the excluded directories, in a stable order."""
    files = git_python_files(root)
    if files is None:
        files = walk_python_files(root)
    kept = [
        p
        for p in files
        if p.is_file() and not EXCLUDED_DIRS.intersection(p.relative_to(root).parts[:-1])
    ]
    return sorted(kept)


def measure_repo(root: Path) -> list[Measure]:
    """Violations across the whole repository. Raises ``SyntaxError`` naming the file."""
    found: list[Measure] = []
    for path in python_files(root):
        rel = path.relative_to(root).as_posix()
        found.extend(measure_source(path.read_text(encoding="utf-8"), rel))
    return found


# --------------------------------------------------------------------------- baseline ratchet


def load_baseline(path: Path) -> dict[str, int]:
    """``{key: value}`` from the baseline file; ``{}`` if missing. ``ValueError`` if corrupt."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    violations = data.get("violations") if isinstance(data, dict) else None
    if not isinstance(violations, dict) or not all(
        isinstance(k, str) and isinstance(v, int) for k, v in violations.items()
    ):
        raise ValueError(f"{path.name} is not a valid code-caps baseline")
    return dict(violations)


def write_baseline(path: Path, violations: dict[str, int]) -> None:
    payload = {
        "version": BASELINE_VERSION,
        "caps": CAPS,
        "violations": dict(sorted(violations.items())),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def compare(current: list[Measure], baseline: dict[str, int]) -> Verdict:
    """Classify current violations against the baseline."""
    new: list[Measure] = []
    grown: list[tuple[Measure, int]] = []
    improved: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for item in current:
        seen.add(item.key)
        allowed = baseline.get(item.key)
        if allowed is None:
            new.append(item)
        elif item.value > allowed:
            grown.append((item, allowed))
        elif item.value < allowed:
            improved.append((item.key, allowed, item.value))
    fixed = sorted(key for key in baseline if key not in seen)
    return Verdict(tuple(new), tuple(grown), tuple(improved), tuple(fixed))


def ratcheted(current: list[Measure], baseline: dict[str, int]) -> dict[str, int]:
    """Baseline lowered to the current values; fixed entries dropped; nothing is ever added."""
    now = {item.key: item.value for item in current}
    return {key: min(old, now[key]) for key, old in baseline.items() if key in now}


# --------------------------------------------------------------------------- CLI


def report(verdict: Verdict) -> None:
    for item in verdict.new:
        print(f"NEW   {item.describe()}", file=sys.stderr)
    for item, old in verdict.grown:
        print(f"GREW  {item.describe()} (baseline {old})", file=sys.stderr)
    for key, old, now in verdict.improved:
        print(f"better: {key} {old} -> {now} (run --update-baseline to lock it in)")
    for key in verdict.fixed:
        print(f"fixed: {key} (run --update-baseline to drop it)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--init", action="store_true", help="write the baseline from today's violations"
    )
    parser.add_argument(
        "--force", action="store_true", help="with --init: overwrite an existing baseline"
    )
    parser.add_argument("--update-baseline", action="store_true", help="ratchet the baseline down")
    return parser


def run_init(root: Path, current: list[Measure], *, force: bool) -> int:
    target = root / BASELINE_NAME
    if target.exists() and not force:
        print(f"{BASELINE_NAME} exists: use --force to overwrite", file=sys.stderr)
        return 2
    write_baseline(target, {item.key: item.value for item in current})
    print(f"wrote {BASELINE_NAME} with {len(current)} tolerated violation(s)")
    return 0


def run_update(root: Path, current: list[Measure]) -> int:
    target = root / BASELINE_NAME
    baseline = load_baseline(target)
    verdict = compare(current, baseline)
    if verdict.failed:
        report(verdict)
        print("refusing to update: fix new/grown violations first", file=sys.stderr)
        return 1
    write_baseline(target, ratcheted(current, baseline))
    print(f"{BASELINE_NAME} updated")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root: Path = args.root
    try:
        current = measure_repo(root)
        if args.init:
            return run_init(root, current, force=args.force)
        if args.update_baseline:
            return run_update(root, current)
        verdict = compare(current, load_baseline(root / BASELINE_NAME))
    except (SyntaxError, ValueError, OSError) as exc:
        print(f"code caps: {exc}", file=sys.stderr)
        return 2
    report(verdict)
    if verdict.failed:
        print("code caps FAILED: new or grown violations (see above)", file=sys.stderr)
        return 1
    print(f"code caps ok ({len(current)} tolerated violation(s) in the baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
