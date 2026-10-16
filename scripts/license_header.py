# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Two-line SPDX license header on every source file.

``uv run python scripts/license_header.py`` lists the files that lack it (exit 1 when there are
any); ``--apply`` writes it. ``tests/test_license_header.py`` runs the same check on the real
tree, so a new file without the header fails the unit suite.

Covered: ``.py`` ``.sh`` ``.js`` ``.mjs`` ``.css`` ``.html`` under ``src``, ``tests`` and
``scripts``. Not covered: data and config files, docs, the hook shims and the Semgrep fixtures.
The header goes on the first two lines, or below a first line that must stay first (a shebang,
a CSS ``@charset``). The HTML templates use a Jinja comment, which renders nothing.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT: Final = Path(__file__).resolve().parent.parent
SCANNED_DIRS: Final = ("src", "tests", "scripts")
SKIPPED_PARTS: Final = frozenset({"__pycache__", "node_modules", ".venv", "mutants"})
SPDX: Final = "SPDX-License-Identifier: GPL-3.0-only"
COPYRIGHT: Final = "Copyright (C) 2026 Giovanni Manzoni"
#: The header is looked for in this many lines (a shebang line may come first).
HEADER_WINDOW: Final = 3


@dataclass(frozen=True, slots=True)
class Style:
    """How one kind of file writes a comment line; ``keep_first`` lines stay on top."""

    opening: str
    closing: str = ""
    keep_first: tuple[str, ...] = ()

    def line(self, text: str) -> str:
        return f"{self.opening}{text}{self.closing}\n"

    def header(self) -> str:
        return self.line(SPDX) + self.line(COPYRIGHT)


HASH: Final = Style("# ", keep_first=("#!",))
SLASHES: Final = Style("// ")
BLOCK: Final = Style("/* ", " */", keep_first=("@charset",))
JINJA: Final = Style("{# ", " -#}")  # `-#}` also drops the newline: the page output is unchanged

STYLES: Final = {
    ".py": HASH,
    ".sh": HASH,
    ".js": SLASHES,
    ".mjs": SLASHES,
    ".css": BLOCK,
    ".html": JINJA,
}


def style_of(name: str) -> Style | None:
    """The comment style of a file name, or ``None`` when it carries no header."""
    return STYLES.get(PurePosixPath(name).suffix)


def source_files(root: Path) -> list[Path]:
    """Every file that must carry the header, sorted."""
    return sorted(
        path
        for name in SCANNED_DIRS
        for path in (root / name).rglob("*")
        if path.is_file()
        and path.suffix in STYLES
        and not SKIPPED_PARTS & set(path.relative_to(root).parts)
    )


def has_header(text: str, style: Style) -> bool:
    top = "".join(text.splitlines(keepends=True)[:HEADER_WINDOW])
    return style.header() in top


def with_header(text: str, style: Style) -> str:
    """``text`` with the header below the first line when that line must stay first."""
    lines = text.splitlines(keepends=True)
    keep = 1 if lines and lines[0].startswith(style.keep_first) else 0
    head = lines[:keep]
    if head and not head[0].endswith("\n"):
        head[0] += "\n"
    return "".join([*head, style.header(), *lines[keep:]])


def _style(path: Path) -> Style:
    style = style_of(path.name)
    assert style is not None  # source_files() keeps only the known suffixes
    return style


def missing(root: Path) -> list[str]:
    """Relative paths (posix) of the files without the header."""
    return [
        path.relative_to(root).as_posix()
        for path in source_files(root)
        if not has_header(path.read_bytes().decode("utf-8"), _style(path))
    ]


def apply(root: Path) -> list[str]:
    """Write the header into the files that lack it; returns their relative paths."""
    changed = []
    for name in missing(root):
        path = root / name
        text = path.read_bytes().decode("utf-8")
        path.write_bytes(with_header(text, _style(path)).encode("utf-8"))
        changed.append(name)
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--apply", action="store_true", help="write the header, do not just list")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (for tests)")
    args = parser.parse_args(argv)
    names = apply(args.root) if args.apply else missing(args.root)
    for name in names:
        print(name)
    return 0 if args.apply or not names else 1


if __name__ == "__main__":
    raise SystemExit(main())
