# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""JSON hostile and large inputs: chunk boundaries, the per-object cap, nesting and big numbers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.json_rows import CHUNK_CHARS, MAX_OBJECT_CHARS
from tests.sources.text_support import in_small_stack, inline, of_file, put

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext


def test_limits() -> None:
    assert CHUNK_CHARS == 65_536
    assert MAX_OBJECT_CHARS == 1_048_576


def objects(count: int) -> list[dict[str, object]]:
    return [{"source": f"s{i}", "target": f"t{i}", "value": i + 1} for i in range(count)]


def test_a_large_array_is_decoded_across_many_chunks(source_ctx: SourceContext) -> None:
    items = objects(6000)
    text = json.dumps(items, indent=1)
    assert len(text) > 4 * CHUNK_CHARS
    out = inline(source_ctx, text, format="json")
    assert out.rows == [(f"s{i}", f"t{i}", i + 1.0, None) for i in range(6000)]
    assert out.warnings == []


def test_a_large_ndjson_is_decoded_across_many_chunks(source_ctx: SourceContext) -> None:
    items = objects(6000)
    text = "\n".join(json.dumps(item) for item in items)
    assert len(text) > CHUNK_CHARS
    out = inline(source_ctx, text, format="json")
    assert [row[0] for row in out.rows] == [f"s{i}" for i in range(6000)]


def test_line_numbers_stay_right_across_chunks(source_ctx: SourceContext) -> None:
    items = objects(6000)
    items[5000] = {"source": "bad", "target": "t", "value": "x"}
    text = "\n".join(json.dumps(item) for item in items)
    out = inline(source_ctx, text, format="json")
    assert out.warnings == ["inline:5001: value must be a positive number"]


@pytest.mark.parametrize("shift", range(5))
def test_every_split_point_of_an_object_across_the_chunk_edge_decodes(
    source_ctx: SourceContext, shift: int
) -> None:
    pad = '{"source":"a","target":"b","value":1,"pad":"' + "x" * (CHUNK_CHARS - 60 + shift) + '"}'
    out = inline(source_ctx, f"{pad}\n{pad}\n", format="json")
    assert out.rows == [("a", "b", 1.0, None), ("a", "b", 1.0, None)]


def with_pad(size: int) -> str:
    """An object of exactly ``size`` characters."""
    head = '{"source":"a","target":"b","value":1,"pad":"'
    return head + "x" * (size - len(head) - 2) + '"}'


class Cap(NamedTuple):
    size: int
    fits: bool


@pytest.mark.parametrize(
    "case",
    [
        Cap(MAX_OBJECT_CHARS - 1, True),
        Cap(MAX_OBJECT_CHARS, True),
        Cap(MAX_OBJECT_CHARS + 1, False),
    ],
    ids=["cap-1", "cap", "cap+1"],
)
def test_one_object_may_take_at_most_one_mebichar(source_ctx: SourceContext, case: Cap) -> None:
    text = with_pad(case.size)
    assert len(text) == case.size
    if case.fits:
        assert inline(source_ctx, text, format="json").rows == [("a", "b", 1.0, None)]
        return
    with pytest.raises(SourceError) as info:
        inline(source_ctx, text, format="json")
    assert str(info.value) == "inline:1: invalid JSON (Expecting ',' delimiter)"


def test_the_cap_counts_from_the_start_of_the_object(source_ctx: SourceContext) -> None:
    small = '{"source":"a","target":"b","value":1}\n'
    out = inline(source_ctx, small * 3 + with_pad(MAX_OBJECT_CHARS), format="json")
    assert len(out.rows) == 4


def test_deeply_nested_json_is_a_source_error(source_ctx: SourceContext) -> None:
    text = '{"source": ' + "[" * 100_000 + "]" * 100_000 + "}"
    with pytest.raises(SourceError) as info:
        in_small_stack(lambda: inline(source_ctx, text, format="json"))
    assert str(info.value) == "inline:1: JSON is nested too deeply"


def test_nesting_inside_a_line_is_reported_on_that_line(source_ctx: SourceContext) -> None:
    text = '{"source":"a","target":"b","value":1}\n{"x": ' + "[" * 100_000 + "}"
    with pytest.raises(SourceError, match=r"^inline:2: JSON is nested too deeply$"):
        in_small_stack(lambda: inline(source_ctx, text, format="json"))


def test_an_absurdly_long_integer_is_a_source_error(source_ctx: SourceContext) -> None:
    text = '{"source":"a","target":"b","value":1' + "0" * 5000 + "}"
    with pytest.raises(SourceError) as info:
        inline(source_ctx, text, format="json")
    assert str(info.value) == "inline:1: JSON holds a number that is too large"


def test_a_big_but_legal_integer_is_a_value_problem_not_a_crash(source_ctx: SourceContext) -> None:
    text = '{"source":"a","target":"b","value":1' + "0" * 400 + "}"
    out = inline(source_ctx, text, format="json")
    assert out.rows == []
    assert out.warnings == ["inline:1: value must be a positive number"]


def test_a_decode_error_in_a_json_file_names_the_line(source_ctx: SourceContext) -> None:
    put(source_ctx, "bad.json", b'[{"source":"a","target":"b","value":1}, {"source":"\xff"}]')
    with pytest.raises(SourceError) as info:
        of_file(source_ctx, "bad.json", format="json")
    assert str(info.value) == (
        "bad.json:1: cannot decode the data as utf-8 (at or after this line)"
    )


def test_a_decode_error_deep_in_a_json_file_names_a_line_at_or_before_it(
    source_ctx: SourceContext,
) -> None:
    rows = b'{"source":"a","target":"b","value":1}\n' * 3000  # past the first chunk
    put(source_ctx, "late.ndjson", rows + b'{"source":"\xff"}\n')
    with pytest.raises(SourceError) as info:
        of_file(source_ctx, "late.ndjson", format="json")
    message = str(info.value)
    assert message.startswith("late.ndjson:")
    assert message.endswith(": cannot decode the data as utf-8 (at or after this line)")
    line = int(message.split(":")[1])
    assert 1000 < line <= 3001  # a lower bound of the real line, 3001


def test_a_bom_at_the_start_of_a_later_chunk_is_data(source_ctx: SourceContext) -> None:
    opening = '{"source":"ab'
    text = "[" + " " * (CHUNK_CHARS - 1 - len(opening)) + opening
    assert len(text) == CHUNK_CHARS  # the next character opens the second chunk
    text += '\ufeffcd","target":"t","value":1}]'
    assert text[CHUNK_CHARS] == "\ufeff"
    out = inline(source_ctx, text, format="json")
    assert out.rows == [("ab\ufeffcd", "t", 1.0, None)]


def test_a_bom_is_only_dropped_at_the_start(source_ctx: SourceContext) -> None:
    rows = [{"source": "\ufeffa", "target": "b", "value": 1}]
    out = inline(source_ctx, "\ufeff" + json.dumps(rows, ensure_ascii=False), format="json")
    assert out.rows == [("\ufeffa", "b", 1.0, None)]
