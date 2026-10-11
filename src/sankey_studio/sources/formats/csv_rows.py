"""Delimited text (csv/tsv): header optional, columns by name or 0-based index, category column."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.lines import LINE_MAX, LineReader
from sankey_studio.sources.formats.sniff import sniff_delimiter
from sankey_studio.sources.formats.values import Row

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO

    from sankey_studio.models import RawLink
    from sankey_studio.sources.formats.job import ParseJob

#: Hostile input: one field may not exceed a line. Process-wide, set once at import.
csv.field_size_limit(LINE_MAX)

#: One record (it may span lines through a quoted field) may not take more than this many
#: characters: a hostile file cannot make the reader build one record of millions of cells.
RECORD_MAX_CHARS = 65_536

#: Header names used when no column is given, and the positions used without a header.
DEFAULT_COLUMNS = (("source", 0), ("target", 1), ("value", 2))
CATEGORY_HEADER = "category"
TAB = "\t"


def _key(name: str) -> str:
    return name.strip().casefold()


class _Header:
    """The header row (or its absence) and column look-ups against it."""

    def __init__(self, label: str, cells: list[str] | None) -> None:
        self._label = label
        self._index: dict[str, int] | None = None
        if cells is not None:
            self._index = {}
            for position, cell in enumerate(cells):
                self._index.setdefault(_key(cell), position)

    def find(self, name: str) -> int:
        """Position of the column called ``name`` (case-insensitive); ``SourceError`` if absent."""
        if self._index is None:
            raise SourceError(f"{self._label}: column '{name}' needs a header row")
        position = self._index.get(_key(name))
        if position is None:
            raise SourceError(f"{self._label}: column '{name}' is not in the header")
        return position

    def required(self, ref: str | int | None, default: tuple[str, int]) -> int:
        """Source/target/value: the given column, else the default name (or position)."""
        if isinstance(ref, int):
            return ref
        if ref is not None:
            return self.find(ref)
        name, position = default
        return position if self._index is None else self.find(name)

    def category(self, ref: str | int | None, *, detect: bool) -> int | None:
        """The category column: explicit wins; else a 'category' header when ``detect``."""
        if isinstance(ref, int):
            return ref
        if ref is not None:
            return self.find(ref)
        if detect and self._index is not None:
            return self._index.get(CATEGORY_HEADER)
        return None


@dataclass(frozen=True, slots=True)
class Columns:
    """Where each field sits in a record (``category`` is ``None`` when there is none)."""

    source: int
    target: int
    value: int
    category: int | None

    def row(self, number: int, record: list[str]) -> Row:
        """A short record gives ``None`` cells: fatal for source/target/value, not for category."""
        return Row(
            number,
            _cell(record, self.source),
            _cell(record, self.target),
            _cell(record, self.value),
            None if self.category is None else _cell(record, self.category),
        )


def _cell(record: list[str], index: int) -> str | None:
    return record[index] if index < len(record) else None


def resolve_columns(job: ParseJob, cells: list[str] | None) -> Columns:
    """Map the spec's column references onto the header ``cells`` (``None`` = no header)."""
    spec = job.spec
    header = _Header(job.label, cells)
    source, target, value = DEFAULT_COLUMNS
    return Columns(
        header.required(spec.source_column, source),
        header.required(spec.target_column, target),
        header.required(spec.value_column, value),
        header.category(spec.category_column, detect=spec.detect_category),
    )


def _delimiter(job: ParseJob) -> str:
    """An explicit delimiter is honoured verbatim; else tab for tsv, else sniffed."""
    if job.spec.delimiter is not None:
        return job.spec.delimiter
    return TAB if job.fmt == "tsv" else sniff_delimiter(job.sample)


class _RecordBudget:
    """Feeds lines to ``csv.reader`` and bounds what one record may consume.

    ``csv.reader`` pulls a line at a time and returns when a record is complete, so counting the
    characters fed since the last ``reset`` bounds the record before its cells are built.
    """

    def __init__(self, job: ParseJob, lines: LineReader) -> None:
        self._job = job
        self._lines = lines
        self._used = 0
        self._first: int | None = None

    def reset(self) -> None:
        """A record is complete: the next line starts a new one."""
        self._used = 0
        self._first = None

    def feed(self) -> Iterator[str]:
        for line in self._job.usable(self._lines):
            if self._first is None:
                self._first = line.number
            self._used += len(line.text)
            if self._used > RECORD_MAX_CHARS:
                raise SourceError(
                    f"{self._job.label}:{self._first}: "
                    f"a record is longer than {RECORD_MAX_CHARS} characters"
                )
            yield line.text


def _records(job: ParseJob, lines: LineReader) -> Iterator[tuple[int, list[str]]]:
    """Non-blank records with the number of the last physical line they used."""
    budget = _RecordBudget(job, lines)
    reader = csv.reader(budget.feed(), delimiter=_delimiter(job))
    try:
        for record in reader:
            budget.reset()
            if any(cell.strip() for cell in record):
                yield lines.number, record
    except csv.Error as exc:
        raise SourceError(f"{job.label}:{lines.number}: invalid CSV data ({exc})") from None


def csv_links(job: ParseJob, stream: TextIO) -> Iterator[RawLink]:
    lines = LineReader(stream, LINE_MAX, job.label)
    columns = None if job.spec.has_header else resolve_columns(job, None)
    for number, record in _records(job, lines):
        if columns is None:
            columns = resolve_columns(job, record)
            continue
        link = job.link(columns.row(number, record))
        if link is not None:
            yield link
