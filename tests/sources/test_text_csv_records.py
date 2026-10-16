# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""csv records: one record may not swallow the file (quoted fields that span many lines)."""

from __future__ import annotations

import tracemalloc
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.csv_rows import RECORD_MAX_CHARS
from tests.sources.text_support import inline, of_file, put

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext

HEADER = "source,target,value\n"
MIB = 1024 * 1024
OK_ROW = ("ok", "fine", 1.0, None)
FIRST_ROW = ("a", "b", 1.0, None)

#: Each line of this record closes one quoted field and opens the next: one record, many lines.
OPEN = 'a,b,1,"x\n'
STEP = 'y","z\n'


def record(chars: int) -> str:
    """One csv record of exactly ``chars`` characters, newlines included, over many lines."""
    steps = (chars - len(OPEN) - 100) // len(STEP)
    pad = chars - len(OPEN) - steps * len(STEP) - len('y"\n')
    text = OPEN + STEP * steps + 'y"' + "," * pad + "\n"
    assert len(text) == chars
    return text


def test_the_record_limit() -> None:
    assert RECORD_MAX_CHARS == 65_536


class Size(NamedTuple):
    chars: int
    fits: bool


SIZES = [
    Size(RECORD_MAX_CHARS - 1, True),
    Size(RECORD_MAX_CHARS, True),
    Size(RECORD_MAX_CHARS + 1, False),
    Size(RECORD_MAX_CHARS + 100, False),
]


@pytest.mark.parametrize("case", SIZES, ids=[str(c.chars) for c in SIZES])
def test_a_record_may_use_the_limit_and_not_one_character_more(
    source_ctx: SourceContext, case: Size
) -> None:
    text = HEADER + record(case.chars) + "ok,fine,1\n"
    if case.fits:
        assert inline(source_ctx, text, format="csv").rows == [FIRST_ROW, OK_ROW]
        return
    with pytest.raises(SourceError) as info:
        inline(source_ctx, text, format="csv")
    assert str(info.value) == "inline:2: a record is longer than 65536 characters"


def test_the_error_names_the_line_where_the_record_starts(source_ctx: SourceContext) -> None:
    text = HEADER + "x,y,1\n\n" * 3 + record(RECORD_MAX_CHARS + 1)  # lines 2-7, then line 8
    with pytest.raises(SourceError) as info:
        inline(source_ctx, text, format="csv")
    assert str(info.value) == "inline:8: a record is longer than 65536 characters"


def test_a_record_that_is_too_long_is_an_error_even_in_lenient_mode(
    source_ctx: SourceContext,
) -> None:
    assert source_ctx.strict is False
    with pytest.raises(SourceError) as info:
        inline(source_ctx, record(RECORD_MAX_CHARS + 1), format="csv", has_header=False)
    assert str(info.value) == "inline:1: a record is longer than 65536 characters"


def test_the_budget_is_per_record_not_per_file(source_ctx: SourceContext) -> None:
    big = record(RECORD_MAX_CHARS - 10)
    text = HEADER + big + "x,y,2\n" + big + "\n\n" + big + "ok,fine,1\n"
    out = inline(source_ctx, text, format="csv")
    assert out.rows == [FIRST_ROW, ("x", "y", 2.0, None), FIRST_ROW, FIRST_ROW, OK_ROW]
    assert out.warnings == []


def test_blank_lines_between_records_do_not_add_up(source_ctx: SourceContext) -> None:
    rows = HEADER + ("a,b,1\n" + "\n" * 5000) * 20
    assert inline(source_ctx, rows, format="csv").rows == [FIRST_ROW] * 20


def test_an_overlong_line_inside_a_record_is_dropped_and_the_record_goes_on(
    source_ctx: SourceContext,
) -> None:
    text = HEADER + OPEN + "q" * 5000 + "\n" + 'y"\n' + "ok,fine,1\n"
    out = inline(source_ctx, text, format="csv")
    assert out.rows == [FIRST_ROW, OK_ROW]
    assert out.warnings == ["inline:3: line is longer than 4096 characters, skipped"]


def test_a_file_of_one_endless_record_costs_a_bounded_amount_of_memory(
    source_ctx: SourceContext,
) -> None:
    lines = 1_000_000  # 6 MB of lines that would be one record of 2 million cells
    put(source_ctx, "hostile.csv", HEADER + OPEN + STEP * lines)
    tracemalloc.start()
    try:
        with pytest.raises(SourceError) as info:
            of_file(source_ctx, "hostile.csv")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert str(info.value) == "hostile.csv:2: a record is longer than 65536 characters"
    assert peak < 4 * MIB


def test_the_first_record_of_the_file_may_use_the_whole_budget(source_ctx: SourceContext) -> None:
    text = record(RECORD_MAX_CHARS) + "ok,fine,1\n"
    out = inline(source_ctx, text, format="csv", has_header=False, detect_category=False)
    assert out.rows == [FIRST_ROW, OK_ROW]
