# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``skip_space`` across a refill that comes after earlier tokens were consumed.

The consumed prefix of the buffer is dropped by the refill, so the newlines in the whitespace
that is left must be counted once, from the cursor on: neither the consumed prefix again nor
the whitespace twice, or every later line number shifts.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest

from sankey_studio.sources.formats import json_rows
from sankey_studio.sources.formats.json_rows import _Scanner
from tests.sources.text_support import inline

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext

#: Line 1 ``a``, line 2 ``b``, line 3 blank, line 4 ``c``.
TEXT = "a\nb\n\n  c"
#: Entries that sit on lines 3 and 6 behind blank lines; the second one is not an object.
ARRAY = '[\n\n{"source":"a","target":"b","value":1},\n\n\n  5\n]'


def test_the_rest_of_a_buffer_is_counted_from_the_cursor_not_from_the_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(json_rows, "CHUNK_CHARS", 6)  # the first chunk ends inside the gap
    scan = _Scanner(io.StringIO(TEXT), "inline")
    assert scan.skip_space() is True
    assert scan.take("a") is True
    assert scan.skip_space() is True
    assert scan.take("b") is True
    assert (scan._buf, scan._pos, scan._line) == ("a\nb\n\n ", 3, 2)  # "\n\n " is all that is left
    assert scan.skip_space() is True  # no non-blank character in the buffer: it is refilled
    assert (scan._buf, scan._pos, scan._line) == (" c", 1, 4)  # the second chunk, one blank in
    assert scan.peek() == "c"
    assert str(scan.error("stop")) == "inline:4: stop"


def test_blanks_left_at_the_end_of_the_input_are_counted_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(json_rows, "CHUNK_CHARS", 4)
    scan = _Scanner(io.StringIO("a\nb \n\n"), "inline")
    assert scan.skip_space() is True
    assert scan.take("a") is True
    assert scan.skip_space() is True
    assert scan.take("b") is True
    assert scan.skip_space() is False  # only blanks until the end of the input
    assert (scan._buf, scan._pos, scan._line) == ("", 0, 4)
    assert scan.error("stop").args == ("inline:4: stop",)


@pytest.mark.parametrize("chunk", range(1, len(ARRAY) + 2))
def test_every_chunk_size_reads_the_same_entries_and_lines(
    source_ctx: SourceContext, monkeypatch: pytest.MonkeyPatch, chunk: int
) -> None:
    monkeypatch.setattr(json_rows, "CHUNK_CHARS", chunk)
    out = inline(source_ctx, ARRAY, format="json")
    assert out.rows == [("a", "b", 1.0, None)]
    assert out.skipped == 1
    assert out.warnings == ["inline:6: each entry must be a JSON object"]
