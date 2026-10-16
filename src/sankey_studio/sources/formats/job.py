# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Per-load parsing state shared by the format parsers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sankey_studio.sources.formats.lines import LINE_MAX
from sankey_studio.sources.formats.values import Row, RowError, clean_name, clean_value

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sankey_studio.models import RawLink, TextSource
    from sankey_studio.sources.base import CategoryCleaner, Diagnostics, SourceContext
    from sankey_studio.sources.formats.lines import Line, LineReader
    from sankey_studio.sources.formats.sniff import ParsedFormat


@dataclass(slots=True)
class ParseJob:
    """Everything a parser needs for one load (bundled: parsers take at most 4 parameters)."""

    spec: TextSource
    ctx: SourceContext
    diag: Diagnostics
    #: ONE cleaner per load; ``TextDataSource.iter_links`` calls ``finish()`` in a ``finally``.
    cleaner: CategoryCleaner
    #: 'inline' or the sources-dir relative path: the ``name`` of ``name:line: message``.
    label: str
    fmt: ParsedFormat
    #: The first characters of the text (<= 4 KB), used to sniff the delimiter.
    sample: str

    def problem(self, line: int, message: str) -> None:
        """Skip the row with a warning, or raise ``SourceError`` in strict mode."""
        self.ctx.row_problem(self.diag, f"{self.label}:{line}: {message}")

    def usable(self, lines: LineReader) -> Iterator[Line]:
        """The lines worth parsing; overlong ones are reported and dropped before any regex."""
        for line in lines.lines():
            if line.overlong:
                self.problem(line.number, f"line is longer than {LINE_MAX} characters, skipped")
                continue
            yield line

    def link(self, row: Row) -> RawLink | None:
        """Clean one row into a link, or report why not (the category never drops a row)."""
        try:
            source = clean_name(row.source, "source")
            target = clean_name(row.target, "target")
            value = clean_value(row.value)
        except RowError as exc:
            self.problem(row.line, str(exc))
            return None
        return source, target, value, self.cleaner.clean(row.category)
