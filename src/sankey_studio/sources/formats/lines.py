# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Bounded line reading: a hostile file cannot make us hold a huge line in memory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sankey_studio.errors import SourceError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO

#: Longest data line parsed (characters, newline excluded); longer lines are skipped.
LINE_MAX = 4096
BOM = "\ufeff"
#: Line breaks as the universal-newline decoder sees them (CRLF is one break).
_BREAK_RE = re.compile(rb"\r\n|\r|\n")


@dataclass(frozen=True, slots=True)
class Line:
    """One physical line. ``text`` keeps its newline; an overlong line is cut to the limit."""

    number: int
    text: str
    overlong: bool


def decode_error(label: str, line: int, encoding: str) -> SourceError:
    """The error for data that does not decode; ``line`` is where the failing block starts.

    The decoder works on blocks, so the bad byte can sit on a later line: the message says so.
    """
    where = f"{label}:{line}"
    return SourceError(f"{where}: cannot decode the data as {encoding} (at or after this line)")


def located_decode_error(
    label: str, line: int, exc: UnicodeDecodeError, encoding: str
) -> SourceError:
    """Like ``decode_error``, but names the real line when the failing block can be scanned.

    That is the case when ``encoding`` writes ``\\n`` and ``\\r`` as the single bytes they are in
    ASCII (utf-8, cp1252, latin-1, ...: not utf-16/32): the line breaks before the bad byte are
    then counted from ``line``, the line where the block starts.
    """
    if not "\n\r".encode(encoding).endswith(b"\n\r"):
        return decode_error(label, line, encoding)
    breaks = len(_BREAK_RE.findall(exc.object[: exc.start]))
    return SourceError(f"{label}:{line + breaks}: cannot decode the data as {encoding}")


class LineReader:
    """Reads lines of at most ``limit`` characters from a text stream.

    An overlong line is flagged and the rest of it is drained in small chunks, so memory stays
    bounded however long the line is. A leading BOM is dropped before the budget is applied
    (the first line may hold ``limit`` characters after it). ``number`` is the number of the last
    line read. A decode error becomes a ``SourceError`` naming the line (``label:line``): the
    real one when the encoding lets the failing block be scanned, else "at or after" the line
    where the block starts.
    """

    def __init__(self, stream: TextIO, limit: int, label: str) -> None:
        self._stream = stream
        self._limit = limit
        self._label = label
        self.number = 0

    def lines(self) -> Iterator[Line]:
        while raw := self._readline(self._limit + 1, self.number + 1):
            self.number += 1
            if self.number == 1:
                raw = self._without_bom(raw)
            if raw.endswith("\n") or len(raw) <= self._limit:
                yield Line(self.number, raw, overlong=False)
                continue
            self._drain()
            yield Line(self.number, raw[: self._limit], overlong=True)

    def _without_bom(self, raw: str) -> str:
        """``raw`` (the first line) without its BOM, topped up to the whole budget."""
        if not raw.startswith(BOM):
            return raw
        raw = raw.removeprefix(BOM)
        if len(raw) == self._limit and not raw.endswith("\n"):  # the BOM took a slot of the read
            raw += self._readline(1, self.number)
        return raw

    def _drain(self) -> None:
        """Discard the rest of the current line."""
        chunk = self._readline(self._limit, self.number)
        while chunk and not chunk.endswith("\n"):
            chunk = self._readline(self._limit, self.number)

    def _readline(self, size: int, line: int) -> str:
        """Up to ``size`` characters of line ``line`` (the one being read)."""
        try:
            return self._stream.readline(size)
        except UnicodeDecodeError as exc:
            raise located_decode_error(self._label, line, exc, self._stream.encoding) from None
