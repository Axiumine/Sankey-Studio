"""``LineReader`` corner cases around the BOM top-up and the drain of an overlong line."""

from __future__ import annotations

import io

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.lines import BOM, Line, LineReader


def lines_of(text: str, limit: int) -> list[Line]:
    return list(LineReader(io.StringIO(text), limit, "t").lines())


def test_a_bom_line_filling_the_budget_with_its_newline_keeps_the_next_line_whole() -> None:
    # after the BOM the line is exactly 5 characters, newline included: nothing to top up
    out = lines_of(BOM + "1234\nnext\n", limit=5)
    assert out == [Line(1, "1234\n", overlong=False), Line(2, "next\n", overlong=False)]


def test_a_bom_line_one_short_of_the_budget_keeps_the_next_line_whole() -> None:
    out = lines_of(BOM + "123\nnext\n", limit=5)
    assert out == [Line(1, "123\n", overlong=False), Line(2, "next\n", overlong=False)]


def test_a_decode_error_in_the_first_read_of_a_drain_names_the_overlong_line() -> None:
    # the first read takes the whole 8192-byte block; the drain needs the next one
    wrapper = io.TextIOWrapper(io.BytesIO(b"x" * 8192 + b"\xff\n"), "utf-8", errors="strict")
    with pytest.raises(SourceError) as info:
        list(LineReader(wrapper, 8191, "d").lines())
    assert str(info.value) == "d:1: cannot decode the data as utf-8"
