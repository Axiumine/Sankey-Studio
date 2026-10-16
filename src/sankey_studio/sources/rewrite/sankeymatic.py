# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""SankeyMATIC adapter: ``Source [value] Target[ | category]`` lines.

Lines are scanned with the parser's own ``split_entry``. Comments, blank lines, overlong lines and
lines the parser skips are RAW. A touched line is rebuilt from its parts with the original value
text; names are quoted only when the grammar needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sankey_studio.errors import SourceEditRefused
from sankey_studio.sources.formats.lines import LINE_MAX
from sankey_studio.sources.formats.sankeymatic import COMMENT, Entry, split_entry
from sankey_studio.sources.formats.values import RowError
from sankey_studio.sources.rewrite.lines import (
    check_line_length,
    dominant_eol,
    eol_of,
    peel_bom,
    split_physical,
    without_eol,
)
from sankey_studio.sources.rewrite.model import Item, data_pair, number_text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sankey_studio.sources.rewrite.model import NewRow, RewriteJob

#: A bare name cannot hold these (they end it or open a quote).
_NEEDS_QUOTES = '[]|"'


@dataclass(frozen=True, slots=True)
class Line:
    """The parts of one entry line that a rewrite keeps."""

    indent: str
    entry: Entry


def quoted(name: str) -> str:
    """``name`` as the grammar reads it back: quoted (inner quotes doubled) when it must be."""
    if "\n" in name or "\r" in name:
        raise SourceEditRefused("unrepresentable")
    plain = name == name.strip() and not name.startswith(COMMENT)
    if plain and not any(char in name for char in _NEEDS_QUOTES):
        return name
    return '"' + name.replace('"', '""') + '"'


def line_text(line: Line, eol: str) -> str:
    """The text of an entry line (the value stays as it was written)."""
    entry = line.entry
    text = f"{line.indent}{quoted(entry.source)} [{entry.value}] {quoted(entry.target)}"
    if entry.category is not None:
        text += f" | {entry.category}"
    check_line_length(text)
    return text + eol


def _entry_of(text: str) -> Entry | None:
    try:
        return split_entry(text)
    except RowError:
        return None


class SankeymaticDoc:
    """A SankeyMATIC text as items."""

    def __init__(self, job: RewriteJob) -> None:
        self.spec = job.spec
        self.reformatted = False
        self._alias = job.alias
        self._bom, body = peel_bom(job.text)
        self._eol = dominant_eol(body)
        self.items = [self._item_of(line) for line in split_physical(body)]

    def _item_of(self, physical: str) -> Item:
        text = without_eol(physical)
        stripped = text.strip()
        if len(text) > LINE_MAX or not stripped or stripped.startswith(COMMENT):
            return Item(physical)
        entry = _entry_of(stripped)
        if entry is None:
            return Item(physical)
        pair = data_pair(entry.source, entry.target, entry.value, self._alias)
        if pair is None:
            return Item(physical)
        indent = text[: len(text) - len(text.lstrip())]
        return Item(physical, pair, Line(indent, entry))

    # ------------------------------------------------------------------ TextDoc

    def with_category_column(self, items: list[Item]) -> list[Item]:
        return items  # a category is just ``| text`` at the end of the line

    def terminated(self, items: list[Item]) -> list[Item]:
        if not items or eol_of(items[-1].chunk):
            return items
        last = items[-1]
        return [*items[:-1], Item(last.chunk + self._eol, last.pair, last.payload)]

    def appended(self, items: list[Item], row: NewRow) -> list[Item]:
        entry = Entry(row.source, row.target, number_text(row.value), row.category)
        return [*items, Item(line_text(Line("", entry), self._eol), (row.source, row.target), None)]

    def recategorised(self, item: Item, category: str | None) -> Item:
        line = cast("Line", item.payload)  # only entry lines are data items
        if line.entry.category == category:
            return item
        entry = line.entry._replace(category=category)
        text = line_text(Line(line.indent, entry), eol_of(item.chunk))
        return Item(text, item.pair, Line(line.indent, entry))

    def render(self, items: Sequence[Item]) -> str:
        return self._bom + "".join(item.chunk for item in items)


def sankeymatic_text(row: NewRow, eol: str) -> str:
    """The first line of an empty SankeyMATIC text."""
    entry = Entry(row.source, row.target, number_text(row.value), row.category)
    return line_text(Line("", entry), eol)
