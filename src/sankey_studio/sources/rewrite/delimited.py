# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""csv/tsv adapter: records become items, a touched record is re-emitted with ``csv.writer``.

Record boundaries, overlong-line skipping and the record budget come from the REAL reader
(``formats.csv_rows.iter_records``), and the columns from ``resolve_columns``, so named columns,
indexes, ``has_header=false`` and the positional fourth category column all work. Untouched
records stay byte for byte; a touched one keeps its cell values but its quoting may be normalised.
The CSV formula guard is an export rule and is never applied to stored data.
"""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from sankey_studio.errors import SourceEditRefused, SourceError
from sankey_studio.models import TextSource
from sankey_studio.sources.formats.csv_rows import (
    CATEGORY_HEADER,
    CATEGORY_POSITION,
    delimiter_of,
    iter_records,
    resolve_columns,
)
from sankey_studio.sources.formats.lines import LINE_MAX, LineReader
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

    from sankey_studio.sources.formats.csv_rows import Columns, Record
    from sankey_studio.sources.formats.job import ParseJob
    from sankey_studio.sources.rewrite.model import NewRow, RewriteJob


def cell_at(cells: Sequence[str], index: int) -> str | None:
    """Cell ``index`` of a record, ``None`` beyond a short record (like ``Columns.row``)."""
    return cells[index] if index < len(cells) else None


def emit(cells: Sequence[str], delimiter: str, eol: str) -> str:
    """One record as text. The line break is added by hand: ``csv.writer`` quotes a cell that
    holds ``\\r`` or ``\\n`` whatever the terminator, and an empty one keeps a missing final
    break missing."""
    out = io.StringIO()
    csv.writer(out, delimiter=delimiter, lineterminator="", quoting=csv.QUOTE_MINIMAL).writerow(
        cells
    )
    chunk = out.getvalue() + eol
    check_line_length(chunk)
    return chunk


def with_pin(spec: TextSource, **pins: object) -> TextSource:
    """``spec`` plus pinned fields, rebuilt through validation (specs are values)."""
    return TextSource.model_validate({**spec.model_dump(), **pins})


class DelimitedDoc:
    """A csv/tsv text as items."""

    def __init__(self, job: RewriteJob, parse: ParseJob) -> None:
        self.spec = job.spec
        self.reformatted = False
        self._alias = job.alias
        self._parse = parse
        self._delimiter = delimiter_of(parse)
        self._bom, body = peel_bom(job.text)
        self._eol = dominant_eol(body)
        #: ``None`` until the header record is read (and for a text without one).
        self._columns: Columns | None = (
            None if job.spec.has_header else resolve_columns(parse, None)
        )
        self._header: list[str] | None = None
        self._header_at = -1
        self.items = self._scan(body)

    def _scan(self, body: str) -> list[Item]:
        physical = split_physical(body)
        reader = LineReader(io.StringIO(body, newline=None), LINE_MAX, self._parse.label)
        items: list[Item] = []
        following = 1
        for record in iter_records(self._parse, reader):
            items.extend(Item(line) for line in physical[following - 1 : record.first - 1])
            chunk = "".join(physical[record.first - 1 : record.last])
            items.append(self._item_of(record, chunk, len(items)))
            following = record.last + 1
        items.extend(Item(line) for line in physical[following - 1 :])
        return items

    def _item_of(self, record: Record, chunk: str, position: int) -> Item:
        if self._columns is None:  # the header record
            self._columns = resolve_columns(self._parse, record.cells)
            self._header, self._header_at = list(record.cells), position
            return Item(chunk)
        if any(len(without_eol(line)) > LINE_MAX for line in split_physical(chunk)):
            return Item(chunk)  # the reader drops that line: re-emitting would delete it
        cols, cells = self._columns, record.cells
        row = (cell_at(cells, cols.source), cell_at(cells, cols.target), cell_at(cells, cols.value))
        pair = data_pair(*row, self._alias)
        return Item(chunk) if pair is None else Item(chunk, pair, list(cells))

    @property
    def columns(self) -> Columns:
        """The resolved columns; a text without a header record has none to edit."""
        if self._columns is None:
            raise SourceEditRefused("unreadable")
        return self._columns

    # ------------------------------------------------------------------ TextDoc

    def with_category_column(self, items: list[Item]) -> list[Item]:
        cols = self.columns
        if cols.category is not None:
            return items
        if self._header is None:
            return self._pin_headerless(cols, items)
        index = len(self._header)
        header = [*self._header, CATEGORY_HEADER]
        chunk = emit(header, self._delimiter, eol_of(items[self._header_at].chunk))
        items = [*items]
        items[self._header_at] = Item(chunk)
        if not self.spec.detect_category:  # auto-detection is off: name the new column
            taken = any(cell.strip().casefold() == CATEGORY_HEADER for cell in self._header)
            self.spec = with_pin(self.spec, category_column=index if taken else CATEGORY_HEADER)
        self._header = header
        self._columns = replace(cols, category=index)
        return items

    def _pin_headerless(self, cols: Columns, items: list[Item]) -> list[Item]:
        picks = {cols.source, cols.target, cols.value}
        index = max(picks) + 1 if CATEGORY_POSITION in picks else CATEGORY_POSITION
        self.spec = with_pin(self.spec, category_column=index)
        self._columns = replace(cols, category=index)
        return items

    def terminated(self, items: list[Item]) -> list[Item]:
        if not items or eol_of(items[-1].chunk):
            return items
        last = items[-1]
        return [*items[:-1], Item(last.chunk + self._eol, last.pair, last.payload)]

    def appended(self, items: list[Item], row: NewRow) -> list[Item]:
        cols = self.columns
        indexes = [cols.source, cols.target, cols.value]
        if row.category is not None and cols.category is not None:
            indexes.append(cols.category)
        width = max(len(self._header or ()), *(index + 1 for index in indexes))
        cells = [""] * width
        cells[cols.source], cells[cols.target] = row.source, row.target
        cells[cols.value] = number_text(row.value)
        if row.category is not None and cols.category is not None:
            cells[cols.category] = row.category
        chunk = emit(cells, self._delimiter, self._eol)
        return [*items, Item(chunk, (row.source, row.target), cells)]

    def recategorised(self, item: Item, category: str | None) -> Item:
        cols = self.columns
        cells = list(cast("list[str]", item.payload))  # only records are data items
        index = cols.category
        if index is None or (cell_at(cells, index) or "") == (category or ""):
            return item
        cells += [""] * (index + 1 - len(cells))
        cells[index] = category or ""
        chunk = emit(cells, self._delimiter, eol_of(item.chunk))
        return Item(chunk, item.pair, cells)

    def render(self, items: Sequence[Item]) -> str:
        return self._bom + "".join(item.chunk for item in items)


def build_delimited(job: RewriteJob, parse: ParseJob) -> DelimitedDoc:
    """The document of ``job.text``; a text the reader cannot load cannot be edited."""
    try:
        return DelimitedDoc(job, parse)
    except SourceError:
        raise SourceEditRefused("unreadable") from None
