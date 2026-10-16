# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""SankeyMATIC-style text: ``Source [12.5] Target`` and ``Source [12.5] Target | category``.

Blank lines and ``//`` comment lines are ignored. A name that contains ``[``, ``]`` or ``|`` is
written in double quotes (a doubled quote inside is a literal quote). The scanner walks the line
once, left to right; no regex ever runs on user text of unbounded length (lines are capped by
``LINE_MAX`` before they get here).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from sankey_studio.sources.formats.lines import LINE_MAX, LineReader
from sankey_studio.sources.formats.values import Row, RowError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO

    from sankey_studio.models import RawLink
    from sankey_studio.sources.formats.job import ParseJob

COMMENT = "//"
#: A bare name runs up to the next of these.
_NAME_STOPS = "[]|"


class Entry(NamedTuple):
    """The four parts of one line, still as text."""

    source: str
    target: str
    value: str
    category: str | None


class _Scanner:
    """A cursor over one line."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0

    def skip_space(self) -> None:
        while self._text[self._pos : self._pos + 1].isspace():
            self._pos += 1

    def peek(self) -> str:
        return self._text[self._pos : self._pos + 1]

    def take(self, char: str) -> bool:
        """Consume ``char`` (after blanks) when it is next."""
        self.skip_space()
        if self.peek() != char:
            return False
        self._pos += 1
        return True

    def name(self) -> str:
        """A quoted or bare name (blanks around it dropped)."""
        self.skip_space()
        if self.peek() == '"':
            return self._quoted()
        stops = (self._text.find(char, self._pos) for char in _NAME_STOPS)
        end = min((stop for stop in stops if stop >= 0), default=len(self._text))
        name = self._text[self._pos : end].strip()
        self._pos = end
        return name

    def _quoted(self) -> str:
        parts: list[str] = []
        start = self._pos + 1
        while True:
            end = self._text.find('"', start)
            if end == -1:
                raise RowError("a quoted name is missing its closing quote")
            parts.append(self._text[start:end])
            if self._text[end + 1 : end + 2] != '"':
                self._pos = end + 1
                return "".join(parts)
            parts.append('"')
            start = end + 2

    def until(self, char: str) -> str:
        """Text up to ``char`` (consumed)."""
        end = self._text.find(char, self._pos)
        if end < 0:
            raise RowError(f"missing '{char}'")
        text = self._text[self._pos : end]
        self._pos = end + 1
        return text

    def rest(self) -> str:
        text = self._text[self._pos :]
        self._pos = len(self._text)
        return text.strip()

    def at_end(self) -> bool:
        return self._pos >= len(self._text)


def split_entry(text: str) -> Entry:
    """Split one entry line; ``RowError`` says what is malformed."""
    scan = _Scanner(text)
    source = scan.name()
    if not scan.take("["):
        raise RowError("expected '[value]' after the source name")
    value = scan.until("]")
    target = scan.name()
    category: str | None = None
    if scan.take("|"):
        category = scan.rest() or None
    if not scan.at_end():
        raise RowError("unexpected text after the target name (quote names that contain brackets)")
    return Entry(source, target, value, category)


def sankeymatic_links(job: ParseJob, stream: TextIO) -> Iterator[RawLink]:
    lines = LineReader(stream, LINE_MAX, job.label)
    for line in job.usable(lines):
        text = line.text.strip()
        if not text or text.startswith(COMMENT):
            continue
        try:
            entry = split_entry(text)
        except RowError as exc:
            job.problem(line.number, str(exc))
            continue
        link = job.link(Row(line.number, entry.source, entry.target, entry.value, entry.category))
        if link is not None:
            yield link
