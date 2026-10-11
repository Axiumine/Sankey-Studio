"""JSON entries: one array of ``{source, target, value[, category]}`` objects, or NDJSON.

Never ``json.load``: objects are decoded one at a time with ``JSONDecoder.raw_decode`` from a
bounded buffer, so a 25 MB array costs one object of memory. One entry may not exceed
``MAX_OBJECT_CHARS``; deep nesting and absurd integers become ``SourceError``.

An element of a well-formed array that is not an object (``null``, a number, a string, a nested
array) is a row problem: skipped with a warning, or a ``SourceError`` in strict mode. A malformed
array, and any non-object in NDJSON, is a ``SourceError`` either way.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.lines import BOM, decode_error
from sankey_studio.sources.formats.values import Row

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO

    from sankey_studio.models import RawLink
    from sankey_studio.sources.formats.job import ParseJob

CHUNK_CHARS = 65_536
#: One decoded object (a link) may not take more buffer than this.
MAX_OBJECT_CHARS = 1_048_576
_DECODER = json.JSONDecoder()
_NON_SPACE_RE = re.compile(r"[^ \t\r\n]")
#: What is left after a number that could still be the start of a longer one (``1e`` + ``5``).
_NUMBER_TAIL_RE = re.compile(r"[.eE+-]*\Z")
#: ``_decode_at_cursor`` result: the buffer ends inside the value (``None`` is a JSON ``null``).
_MORE = object()
_NOT_AN_OBJECT = "each entry must be a JSON object"
_OBJECT_START = frozenset("{")
#: The first character of any JSON value (``NaN``, ``Infinity`` and ``-Infinity`` included).
_VALUE_START = frozenset('{["-0123456789tfnNI')


class _Scanner:
    """A cursor over a text stream that keeps only the undecoded tail in memory."""

    def __init__(self, stream: TextIO, label: str) -> None:
        self._stream = stream
        self._label = label
        self._buf = ""
        self._pos = 0
        self._eof = False
        self._first = True
        self._line = 1  # line number of ``_buf[_pos]``

    def error(self, message: str, at: int | None = None) -> SourceError:
        line = self._line + self._buf.count("\n", self._pos, self._pos if at is None else at)
        return SourceError(f"{self._label}:{line}: {message}")

    def _fill(self) -> bool:
        """Read one more chunk (dropping the consumed prefix). False at end of input."""
        self._buf = self._buf[self._pos :]
        self._pos = 0
        try:
            chunk = self._stream.read(CHUNK_CHARS)
        except UnicodeDecodeError:
            line = self._line + self._buf.count("\n")  # the failing block continues the buffer
            raise decode_error(self._label, line, self._stream.encoding) from None
        if self._first:
            chunk, self._first = chunk.removeprefix(BOM), False
        self._eof = not chunk
        self._buf += chunk
        return bool(chunk)

    def _consume(self, count: int) -> None:
        self._line += self._buf.count("\n", self._pos, self._pos + count)
        self._pos += count

    def skip_space(self) -> bool:
        """Skip JSON whitespace. False when only the end of input is left."""
        while True:
            found = _NON_SPACE_RE.search(self._buf, self._pos)
            if found is not None:
                self._consume(found.start() - self._pos)
                return True
            self._consume(len(self._buf) - self._pos)
            if not self._fill():
                return False

    def peek(self) -> str:
        return self._buf[self._pos : self._pos + 1]

    def take(self, char: str) -> bool:
        """Consume ``char`` when it is next (call ``skip_space`` first)."""
        if self.peek() != char:
            return False
        self._consume(1)
        return True

    def _can_grow(self) -> bool:
        """Whether reading on could still change the outcome (input left, entry budget left)."""
        return not self._eof and len(self._buf) - self._pos < MAX_OBJECT_CHARS

    def _number_may_go_on(self, value: object, end: int) -> bool:
        """A number at the end of the buffer may go on in the next chunk (``12|34``, ``1e|5``)."""
        return (
            isinstance(value, int | float)
            and _NUMBER_TAIL_RE.match(self._buf, end) is not None
            and self._can_grow()
        )

    def _decode_at_cursor(self) -> object:
        """The value at the cursor, or ``_MORE`` when the buffer ends inside it."""
        value: object
        try:
            value, end = _DECODER.raw_decode(self._buf, self._pos)
        except json.JSONDecodeError as exc:
            if self._can_grow():
                return _MORE
            raise self.error(f"invalid JSON ({exc.msg})", exc.pos) from None
        except RecursionError:
            raise self.error("JSON is nested too deeply") from None
        except ValueError:
            raise self.error("JSON holds a number that is too large") from None
        if self._number_may_go_on(value, end):
            return _MORE
        self._consume(end - self._pos)
        return value

    def entry(self, starts: frozenset[str]) -> tuple[int, object]:
        """The JSON value at the cursor and the line it starts on.

        The value must begin with one of ``starts`` (call ``skip_space`` first), else the entry
        is not an object: a ``SourceError`` for structure the loader cannot step over.
        """
        if self.peek() not in starts:
            raise self.error(_NOT_AN_OBJECT)
        line = self._line
        while (value := self._decode_at_cursor()) is _MORE:
            self._fill()  # incomplete: read on; a decoder error at the end of input is final
        return line, value


def _array_entries(scan: _Scanner) -> Iterator[tuple[int, object]]:
    """The elements of the array at the cursor (any JSON value; the caller judges them)."""
    scan.take("[")
    first = True
    while True:
        if not scan.skip_space():
            raise scan.error("the JSON array is not closed")
        if scan.take("]"):
            break
        if not first and not scan.take(","):
            raise scan.error("expected ',' or ']' between entries")
        first = False
        if not scan.skip_space():
            raise scan.error("the JSON array is not closed")
        yield scan.entry(_VALUE_START)
    if scan.skip_space():
        raise scan.error("unexpected data after the JSON array")


def _line_entries(scan: _Scanner) -> Iterator[tuple[int, object]]:
    """The objects of an NDJSON text: anything else is a ``SourceError``."""
    while scan.skip_space():
        yield scan.entry(_OBJECT_START)


def json_links(job: ParseJob, stream: TextIO) -> Iterator[RawLink]:
    scan = _Scanner(stream, job.label)
    if not scan.skip_space():
        return
    entries = _array_entries(scan) if scan.peek() == "[" else _line_entries(scan)
    for line, obj in entries:
        if not isinstance(obj, dict):  # only an array element can get here
            job.problem(line, _NOT_AN_OBJECT)
            continue
        row = Row(line, obj.get("source"), obj.get("target"), obj.get("value"), obj.get("category"))
        link = job.link(row)
        if link is not None:
            yield link
