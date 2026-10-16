# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The two-line SPDX header: how each file type gets it, and that the real tree has it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts.license_header import ROOT, apply, has_header, main, missing, style_of, with_header

if TYPE_CHECKING:
    from pathlib import Path

SPDX = "SPDX-License-Identifier: GPL-3.0-only"
OWNER = "Copyright (C) 2026 Giovanni Manzoni"
HASH_HEAD = f"# {SPDX}\n# {OWNER}\n"
SLASH_HEAD = f"// {SPDX}\n// {OWNER}\n"
CSS_HEAD = f"/* {SPDX} */\n/* {OWNER} */\n"
JINJA_HEAD = f"{{# {SPDX} -#}}\n{{# {OWNER} -#}}\n"

#: (file name, text before, text after)
WRITTEN = [
    ("a.py", "import os\n", f"{HASH_HEAD}import os\n"),
    ("a.py", '"""Doc."""\n', f'{HASH_HEAD}"""Doc."""\n'),
    ("a.py", "", HASH_HEAD),
    ("tool.py", "#!/usr/bin/python\nimport os\n", f"#!/usr/bin/python\n{HASH_HEAD}import os\n"),
    ("run.sh", "#!/bin/sh\nset -e\n", f"#!/bin/sh\n{HASH_HEAD}set -e\n"),
    ("run.sh", "#!/bin/sh", f"#!/bin/sh\n{HASH_HEAD}"),
    ("a.js", "export {};\n", f"{SLASH_HEAD}export {{}};\n"),
    ("a.mjs", "// note\n", f"{SLASH_HEAD}// note\n"),
    ("a.css", "a { }\n", f"{CSS_HEAD}a {{ }}\n"),
    ("a.css", '@charset "utf-8";\na { }\n', f'@charset "utf-8";\n{CSS_HEAD}a {{ }}\n'),
    ("a.html", "<!doctype html>\n", f"{JINJA_HEAD}<!doctype html>\n"),
]


@pytest.mark.parametrize(("name", "before", "after"), WRITTEN)
def test_the_header_is_written_once_for_each_file_type(
    name: str, before: str, after: str, tmp_path: Path
) -> None:
    path = tmp_path / "src" / name
    path.parent.mkdir()
    path.write_bytes(before.encode())
    assert missing(tmp_path) == [f"src/{name}"]
    assert apply(tmp_path) == [f"src/{name}"]
    assert path.read_bytes().decode() == after
    assert missing(tmp_path) == []
    assert apply(tmp_path) == []  # idempotent
    assert path.read_bytes().decode() == after


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.py", True),
        ("deep/a.sh", True),
        ("a.js", True),
        ("a.mjs", True),
        ("a.css", True),
        ("a.html", True),
        ("a.md", False),
        ("a.json", False),
        ("Makefile", False),
        ("a.py.bak", False),
    ],
)
def test_only_source_suffixes_carry_a_header(name: str, expected: bool) -> None:
    assert (style_of(name) is not None) is expected


def test_the_header_is_looked_for_in_the_first_three_lines_only() -> None:
    style = style_of("a.py")
    assert style is not None
    assert has_header(f"{HASH_HEAD}x = 1\n", style)
    assert has_header(f"#!/bin/sh\n{HASH_HEAD}", style)  # a shebang may come first
    assert not has_header(f"\n\n\n{HASH_HEAD}", style)  # the 4th line is too late
    assert not has_header(f"# {SPDX}\nx = 1\n# {OWNER}\n", style)  # the two lines go together
    assert not has_header("", style)
    assert with_header("", style) == HASH_HEAD


def test_files_that_are_not_ours_are_left_alone(tmp_path: Path) -> None:
    skipped = [
        "src/node_modules/x.js",
        "src/__pycache__/x.py",
        "tests/.venv/x.py",
        "scripts/mutants/x.py",
        "docs/x.js",
        "src/notes.md",
        "src/data.json",
        "x.py",
    ]
    for name in skipped:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    assert missing(tmp_path) == []
    assert apply(tmp_path) == []


def test_the_command_lists_then_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == "src/a.py\n"
    assert main(["--root", str(tmp_path), "--apply"]) == 0
    assert capsys.readouterr().out == "src/a.py\n"
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""
    assert (tmp_path / "src" / "a.py").read_text(encoding="utf-8") == f"{HASH_HEAD}x = 1\n"


def test_every_source_file_of_the_project_carries_the_header() -> None:
    """New file? Run ``uv run python scripts/license_header.py --apply``."""
    assert missing(ROOT) == []
