# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Source rules Semgrep 1.178 cannot check for us: it fails to parse ``except A, B, C:``."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sankey_studio.storage import base

ROOT = Path(base.__file__).resolve().parents[1]
SOURCES = sorted([*(ROOT / "storage").rglob("*.py"), ROOT / "services.py"])


def _bare_multi_excepts(path: Path) -> list[str]:
    """``except A, B, C:`` handlers (PEP 758, no parentheses) with three or more names."""
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        match node:
            case ast.ExceptHandler(type=ast.Tuple(elts=[first, _, _, *_]) as names):
                if names.col_offset == first.col_offset:  # a tuple in parentheses starts at "("
                    found.append(f"{path.name}:{node.lineno}")
    return found


def test_the_sources_under_check_are_found() -> None:
    names = {path.name for path in SOURCES}
    assert {"base.py", "bundle.py", "settings_store.py", "repo.py", "services.py"} <= names


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_three_name_except_without_parentheses(path: Path) -> None:
    assert _bare_multi_excepts(path) == []


def test_the_detector_sees_a_bare_three_name_except(tmp_path: Path) -> None:
    bare = tmp_path / "bare.py"
    bare.write_text("try:\n    pass\nexcept A, B, C:\n    pass\n")
    grouped = tmp_path / "grouped.py"
    grouped.write_text("try:\n    pass\nexcept (A, B, C):\n    pass\nexcept A, B:\n    pass\n")
    assert _bare_multi_excepts(bare) == ["bare.py:3"]
    assert _bare_multi_excepts(grouped) == []


def test_the_decode_errors_are_a_constant_tuple() -> None:
    assert (TypeError, ValueError, RecursionError) == base._DECODE_ERRORS
