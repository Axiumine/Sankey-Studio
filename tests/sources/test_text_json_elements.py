# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""JSON arrays: a non-object element is a row problem; a malformed array is an error."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.models import TextSource
from sankey_studio.sources import open_source
from sankey_studio.sources.base import MAX_WARNINGS, Diagnostics
from tests.sources.idtools import safe_id
from tests.sources.text_support import inline

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.sources.base import SourceContext

    Ctx = Callable[..., SourceContext]

NOT_OBJECT = "each entry must be a JSON object"
A = '{"source":"a","target":"b","value":1}'
C = '{"source":"c","target":"d","value":2}'
R1 = ("a", "b", 1.0, None)
R2 = ("c", "d", 2.0, None)


def warn(line: int, message: str = NOT_OBJECT) -> str:
    return f"inline:{line}: {message}"


# Every JSON value that is not an object, as one array element.
ELEMENTS = [
    "null",
    "true",
    "false",
    "0",
    "7",
    "-3",
    "1.5",
    "-0.5",
    "1e5",
    "1E+10",
    "-1.5e-3",
    "NaN",
    "Infinity",
    "-Infinity",
    '""',
    '"text"',
    '"}, {"',
    '"]"',
    "[]",
    "[1, 2]",
    "[[[]]]",
    f"[{A}]",
    '[{"x": [1, {"y": null}]}]',
]
ELEMENT_IDS = [safe_id(element) for element in ELEMENTS]


@pytest.mark.parametrize("element", ELEMENTS, ids=ELEMENT_IDS)
def test_a_non_object_element_is_skipped_with_a_warning(
    source_ctx: SourceContext, element: str
) -> None:
    out = inline(source_ctx, f"[{A},{element},{C}]", format="json")
    assert out.rows == [R1, R2]
    assert out.warnings == [warn(1)]
    assert out.skipped == 1


@pytest.mark.parametrize("element", ELEMENTS, ids=ELEMENT_IDS)
def test_a_non_object_element_raises_in_strict_mode(make_source_ctx: Ctx, element: str) -> None:
    with pytest.raises(SourceError) as info:
        inline(make_source_ctx(strict=True), f"[{A},{element},{C}]", format="json")
    assert str(info.value) == warn(1)


class Layout(NamedTuple):
    text: str
    rows: list[tuple[str, str, float, str | None]]
    warnings: list[str]


LAYOUTS = [
    Layout(f"[null,{A},{C}]", [R1, R2], [warn(1)]),  # the first element
    Layout(f"[{A},{C},null]", [R1, R2], [warn(1)]),  # the last element
    Layout("[null]", [], [warn(1)]),  # the only element
    Layout("[1,2,3]", [], [warn(1)] * 3),  # every element
    Layout(f"[{A},null,null,{C}]", [R1, R2], [warn(1)] * 2),  # neighbours
    Layout(f'[null,{A},1,{C},"s"]', [R1, R2], [warn(1)] * 3),
    Layout(f"[ null , {A} , 5 , {C} ]", [R1, R2], [warn(1)] * 2),  # spaces around the commas
    Layout('[null,{"source":"a"},5]', [], [warn(1), warn(1, "target is missing"), warn(1)]),
    Layout("[\n\n  7\n]", [], [warn(3)]),
    Layout(
        f'[\n  null,\n  {A},\n  [\n    1,\n    2\n  ],\n  {C},\n  "x"\n]\n',
        [R1, R2],
        [warn(2), warn(4), warn(9)],  # the line where the element STARTS
    ),
]


@pytest.mark.parametrize("case", LAYOUTS, ids=[str(index) for index in range(len(LAYOUTS))])
def test_skipped_elements_are_reported_where_they_start(
    source_ctx: SourceContext, case: Layout
) -> None:
    out = inline(source_ctx, case.text, format="json")
    assert out.rows == case.rows
    assert out.warnings == case.warnings
    assert out.skipped == len(case.warnings)


class Skips(NamedTuple):
    skips: int
    shown: int  # warnings kept
    more: int  # warnings only counted


CAPS = [
    Skips(MAX_WARNINGS - 1, MAX_WARNINGS - 1, 0),
    Skips(MAX_WARNINGS, MAX_WARNINGS, 0),
    Skips(MAX_WARNINGS + 1, MAX_WARNINGS, 1),
    Skips(MAX_WARNINGS + 2, MAX_WARNINGS, 2),
]


@pytest.mark.parametrize("case", CAPS, ids=["cap-1", "cap", "cap+1", "cap+2"])
def test_skipped_elements_share_the_cap_on_reported_problems(
    source_ctx: SourceContext, case: Skips
) -> None:
    text = "[" + ",".join(["null"] * case.skips) + f",{A}]"
    out = inline(source_ctx, text, format="json")
    tail = [f"... and {case.more} more warnings"] if case.more else []
    assert out.warnings == [warn(1)] * case.shown + tail
    assert out.skipped == case.skips  # the count never stops
    assert out.rows == [R1]


def test_skipped_elements_and_bad_objects_fill_one_cap(source_ctx: SourceContext) -> None:
    text = "[" + ",".join(["null"] * 30 + ['{"source":"a"}'] * 30) + "]"
    out = inline(source_ctx, text, format="json")
    assert out.warnings == [warn(1)] * 30 + [warn(1, "target is missing")] * 20 + [
        "... and 10 more warnings"
    ]
    assert out.skipped == 60


def test_strict_mode_delivers_the_rows_before_the_bad_element(make_source_ctx: Ctx) -> None:
    spec = TextSource(content=f"[\n{A},\n{C},\nnull,\n{A}]", format="json")
    rows = open_source(spec, make_source_ctx(strict=True)).iter_links(Diagnostics())
    assert [next(rows), next(rows)] == [R1, R2]
    with pytest.raises(SourceError) as info:
        next(rows)
    assert str(info.value) == warn(4)


def test_strict_mode_stops_at_the_first_bad_element_even_when_it_is_the_first(
    make_source_ctx: Ctx,
) -> None:
    with pytest.raises(SourceError) as info:
        inline(make_source_ctx(strict=True), f"[\n\n7,{A}]", format="json")
    assert str(info.value) == warn(3)


class Malformed(NamedTuple):
    text: str
    message: str


# The fault comes before any complete non-object element: strict and lenient raise the same error.
MALFORMED = [
    Malformed(f"[{A},]", warn(1)),
    Malformed(f"[,{A}]", warn(1)),
    Malformed(f"[{A},,{C}]", warn(1)),
    Malformed(f"[{A} {C}]", warn(1, "expected ',' or ']' between entries")),
    Malformed(f"[{A}", warn(1, "the JSON array is not closed")),
    Malformed(f"[{A},\n\n", warn(3, "the JSON array is not closed")),
    Malformed(f"[{A}] x", warn(1, "unexpected data after the JSON array")),
    Malformed(f"[{A}]\n[2]", warn(2, "unexpected data after the JSON array")),
    Malformed("[nul]", warn(1, "invalid JSON (Expecting value)")),
    Malformed('["abc', warn(1, "invalid JSON (Unterminated string starting at)")),
    Malformed("[[1,2}]", warn(1, "invalid JSON (Expecting ',' delimiter)")),
    Malformed('[\n  {"source": }\n]', warn(2, "invalid JSON (Expecting value)")),
    Malformed("[abc]", warn(1)),  # not the start of any JSON value
    Malformed("[}]", warn(1)),
    Malformed("[+1]", warn(1)),
    Malformed("[.5]", warn(1)),
]


@pytest.mark.parametrize("strict", [False, True], ids=["lenient", "strict"])
@pytest.mark.parametrize("case", MALFORMED, ids=[safe_id(c.text) for c in MALFORMED])
def test_a_malformed_array_is_a_source_error_in_both_modes(
    make_source_ctx: Ctx, case: Malformed, strict: bool
) -> None:
    with pytest.raises(SourceError) as info:
        inline(make_source_ctx(strict=strict), case.text, format="json")
    assert str(info.value) == case.message


# Lenient only: strict mode already raised at the non-object element in front of the fault.
AFTER_A_SKIP = [
    Malformed("[null,]", warn(1)),  # a trailing comma after a skipped element
    Malformed("[null,,1]", warn(1)),
    Malformed("[1,\n]", warn(2)),
    Malformed(f"[{A},null,]", warn(1)),
    Malformed("[null null]", warn(1, "expected ',' or ']' between entries")),
    Malformed(f"[1 {A}]", warn(1, "expected ',' or ']' between entries")),
    Malformed("[1.5.5]", warn(1, "expected ',' or ']' between entries")),
    Malformed("[1e", warn(1, "expected ',' or ']' between entries")),
    Malformed("[null", warn(1, "the JSON array is not closed")),
    Malformed("[12345", warn(1, "the JSON array is not closed")),
    Malformed("[null,", warn(1, "the JSON array is not closed")),
    Malformed("[null,\n\n", warn(3, "the JSON array is not closed")),
    Malformed("[[1,2]", warn(1, "the JSON array is not closed")),
    Malformed("[null] x", warn(1, "unexpected data after the JSON array")),
    Malformed("[1]\n[2]", warn(2, "unexpected data after the JSON array")),
    Malformed('[\n  null,\n  {"source": }\n]', warn(3, "invalid JSON (Expecting value)")),
    Malformed('[null, "abc', warn(1, "invalid JSON (Unterminated string starting at)")),
]


@pytest.mark.parametrize("case", AFTER_A_SKIP, ids=[safe_id(c.text) for c in AFTER_A_SKIP])
def test_a_fault_after_a_skipped_element_still_fails_the_load(
    source_ctx: SourceContext, case: Malformed
) -> None:
    with pytest.raises(SourceError) as info:
        inline(source_ctx, case.text, format="json")
    assert str(info.value) == case.message
