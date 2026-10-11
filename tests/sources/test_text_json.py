"""JSON entries: an array of objects, NDJSON, value/name types, categories and structure errors."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceError
from tests.sources.idtools import safe_id
from tests.sources.text_support import inline

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.sources.base import SourceContext

    Ctx = Callable[..., SourceContext]


def entry(source: Any, target: Any, value: Any, **extra: Any) -> dict[str, Any]:
    return {"source": source, "target": target, "value": value, **extra}


def test_an_array_of_objects(source_ctx: SourceContext) -> None:
    text = json.dumps([entry("a", "b", 1), entry("b", "c", 2.5, category="Food")])
    out = inline(source_ctx, text)
    assert out.rows == [("a", "b", 1.0, None), ("b", "c", 2.5, "Food")]
    assert out.warnings == []


class Shape(NamedTuple):
    text: str
    rows: list[tuple[str, str, float, str | None]]


R1 = ("a", "b", 1.0, None)
R2 = ("c", "d", 2.0, None)
SHAPES = [
    Shape(
        '[{"source":"a","target":"b","value":1},{"source":"c","target":"d","value":2}]', [R1, R2]
    ),
    Shape(
        '[\n  {"source":"a","target":"b","value":1},\n  {"source":"c","target":"d","value":2}\n]\n',
        [R1, R2],
    ),
    Shape(
        '[ {"source":"a","target":"b","value":1} , {"source":"c","target":"d","value":2} ]',
        [R1, R2],
    ),
    Shape(
        '{"source":"a","target":"b","value":1}\n{"source":"c","target":"d","value":2}\n', [R1, R2]
    ),
    Shape('{"source":"a","target":"b","value":1}{"source":"c","target":"d","value":2}', [R1, R2]),
    Shape(
        '\n\n{"source":"a","target":"b","value":1}\n\n\n{"source":"c","target":"d","value":2}',
        [R1, R2],
    ),
    Shape(
        '{"source":"a","target":"b","value":1}\r\n{"source":"c","target":"d","value":2}\r\n',
        [R1, R2],
    ),
    Shape('\ufeff[{"source":"a","target":"b","value":1}]', [R1]),
    Shape('{"source":"a","target":"b","value":1}', [R1]),
    Shape("[]", []),
    Shape(" [ ] ", []),
    Shape("", []),
    Shape(" \n\t ", []),
]


@pytest.mark.parametrize("case", SHAPES, ids=[str(i) for i in range(len(SHAPES))])
def test_json_shapes(source_ctx: SourceContext, case: Shape) -> None:
    out = inline(source_ctx, case.text, format="json")
    assert out.rows == case.rows
    assert out.warnings == []


class Cell(NamedTuple):
    obj: dict[str, Any]
    row: tuple[str, str, float, str | None]


CELLS = [
    Cell(entry("a", "b", "1,234.5"), ("a", "b", 1234.5, None)),
    Cell(entry("a", "b", " 7 "), ("a", "b", 7.0, None)),
    Cell(entry(2024, 2025, 3), ("2024", "2025", 3.0, None)),
    Cell(entry("a", "b", 1, extra="ignored", other=[1, 2]), ("a", "b", 1.0, None)),
    Cell(entry("a", "b", 1, category=None), ("a", "b", 1.0, None)),
    Cell(entry("a", "b", 1, category=""), ("a", "b", 1.0, None)),
    Cell(entry("a", "b", 1, category="  Fast   Food "), ("a", "b", 1.0, "Fast Food")),
    Cell(entry("a", "b", 1, category=5), ("a", "b", 1.0, "5")),
    Cell(entry("  a  ", "b\u00e9", 1), ("a", "b\u00e9", 1.0, None)),
    Cell(entry("\u00e9", "b", 1), ("\u00e9", "b", 1.0, None)),
]


@pytest.mark.parametrize("case", CELLS, ids=[str(i) for i in range(len(CELLS))])
def test_json_values_and_names(source_ctx: SourceContext, case: Cell) -> None:
    out = inline(source_ctx, json.dumps([case.obj]), format="json")
    assert out.rows == [case.row]
    assert out.warnings == []


class BadRow(NamedTuple):
    obj: dict[str, Any]
    message: str


BAD_ROWS = [
    BadRow({"target": "b", "value": 1}, "source is missing"),
    BadRow({"source": "a", "value": 1}, "target is missing"),
    BadRow({"source": "a", "target": "b"}, "value is missing"),
    BadRow(entry(None, "b", 1), "source is missing"),
    BadRow(entry("a", "b", None), "value is missing"),
    BadRow(entry(True, "b", 1), "source is not text"),
    BadRow(entry("a", ["b"], 1), "target is not text"),
    BadRow(entry({"x": 1}, "b", 1), "source is not text"),
    BadRow(entry(1.5, "b", 1), "source is not text"),
    BadRow(entry("", "b", 1), "source is empty"),
    BadRow(entry("a", "  ", 1), "target is empty"),
    BadRow(entry("a", "b", ""), "value is empty"),
    BadRow(entry("a", "b", "x"), "value must be a positive number"),
    BadRow(entry("a", "b", 0), "value must be a positive number"),
    BadRow(entry("a", "b", -2), "value must be a positive number"),
    BadRow(entry("a", "b", True), "value must be a positive number"),
    BadRow(entry("a", "b", [1]), "value must be a positive number"),
    BadRow(entry("a", "b", {"v": 1}), "value must be a positive number"),
    BadRow(entry("x" * 201, "b", 1), "source is longer than 200 characters"),
    BadRow(entry("a", "b\u0000c", 1), "target contains a NUL character"),
    BadRow(entry("\ud800", "b", 1), "source contains an invalid character"),
]


@pytest.mark.parametrize("case", BAD_ROWS, ids=[c.message + str(i) for i, c in enumerate(BAD_ROWS)])
def test_a_bad_object_is_skipped_with_a_numbered_warning(
    source_ctx: SourceContext, case: BadRow
) -> None:
    text = "\n".join(json.dumps(o) for o in (entry("a", "b", 1), case.obj, entry("c", "d", 2)))
    out = inline(source_ctx, text, format="json")
    assert out.rows == [R1, R2]
    assert out.warnings == [f"inline:2: {case.message}"]
    assert out.skipped == 1


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_literals_are_refused(source_ctx: SourceContext, literal: str) -> None:
    text = (
        f'{{"source":"a","target":"b","value":{literal}}}\n{{"source":"c","target":"d","value":2}}'
    )
    out = inline(source_ctx, text, format="json")
    assert out.rows == [R2]
    assert out.warnings == ["inline:1: value must be a positive number"]


def test_the_line_of_a_problem_is_the_line_where_the_object_starts(
    source_ctx: SourceContext,
) -> None:
    text = (
        "[\n"
        '  {"source": "a", "target": "b", "value": 1},\n'
        "  {\n"
        '    "source": "c",\n'
        '    "value": 2\n'
        "  },\n"
        '  {"source": "d", "target": "e", "value": 3}\n'
        "]\n"
    )
    out = inline(source_ctx, text, format="json")
    assert out.rows == [("a", "b", 1.0, None), ("d", "e", 3.0, None)]
    assert out.warnings == ["inline:3: target is missing"]


def test_a_bad_object_raises_in_strict_mode(make_source_ctx: Ctx) -> None:
    text = json.dumps([entry("a", "b", 1), entry("c", "d", "no")])
    with pytest.raises(SourceError) as info:
        inline(make_source_ctx(strict=True), text, format="json")
    assert str(info.value) == "inline:1: value must be a positive number"


def test_categories_are_aggregated_into_one_warning(source_ctx: SourceContext) -> None:
    objs = [
        entry("a", "b", 1, category=["x"]),
        entry("a", "c", 1, category={"k": 1}),
        entry("a", "d", 1, category=True),
        entry("a", "e", 1, category="Other"),
        entry("a", "f", 1, category="Food"),
    ]
    out = inline(source_ctx, json.dumps(objs), format="json")
    assert [row[3] for row in out.rows] == [None, None, None, None, "Food"]
    assert out.skipped == 0
    assert out.warnings == [
        (
            "Categories ignored (entries kept uncategorised): 3 not a single text/number value; "
            "1 using the reserved names Uncategorized/Other"
        )
    ]


class Structure(NamedTuple):
    text: str
    message: str


STRUCTURE = [
    Structure("123", "inline:1: each entry must be a JSON object"),
    Structure('"abc"', "inline:1: each entry must be a JSON object"),
    Structure("null", "inline:1: each entry must be a JSON object"),
    Structure(
        '[{"source":"a","target":"b","value":1},]', "inline:1: each entry must be a JSON object"
    ),
    Structure('[,{"source":"a"}]', "inline:1: each entry must be a JSON object"),
    Structure(
        '{"source":"a","target":"b","value":1}\n,\n', "inline:2: each entry must be a JSON object"
    ),
    Structure(
        '{"source":"a","target":"b","value":1}\n42', "inline:2: each entry must be a JSON object"
    ),
    Structure(  # NDJSON stays strict: only an element of an ARRAY can be skipped
        '{"source":"a","target":"b","value":1}\n[1]', "inline:2: each entry must be a JSON object"
    ),
    Structure(
        '{"source":"a","target":"b","value":1}\nnull', "inline:2: each entry must be a JSON object"
    ),
    Structure(
        '[{"source":"a","target":"b","value":1}{"source":"c"}]',
        "inline:1: expected ',' or ']' between entries",
    ),
    Structure("[", "inline:1: the JSON array is not closed"),
    Structure("[\n\n", "inline:3: the JSON array is not closed"),
    Structure('[{"source":"a","target":"b","value":1}', "inline:1: the JSON array is not closed"),
    Structure('[{"source":"a","target":"b","value":1},', "inline:1: the JSON array is not closed"),
    Structure(
        '[{"source":"a","target":"b","value":1}] x',
        "inline:1: unexpected data after the JSON array",
    ),
    Structure(
        '[{"source":"a","target":"b","value":1}]\n[]',
        "inline:2: unexpected data after the JSON array",
    ),
    Structure('{"source": ', "inline:1: invalid JSON (Expecting value)"),
    Structure('{"source": "a",\n "target": }', "inline:2: invalid JSON (Expecting value)"),
    Structure('{"source": "a"', "inline:1: invalid JSON (Expecting ',' delimiter)"),
    Structure('[{"source": }]', "inline:1: invalid JSON (Expecting value)"),
]


@pytest.mark.parametrize("case", STRUCTURE, ids=[safe_id(repr(c.text)[:30]) for c in STRUCTURE])
def test_structure_errors_are_source_errors_naming_the_line(
    source_ctx: SourceContext, case: Structure
) -> None:
    with pytest.raises(SourceError) as info:
        inline(source_ctx, case.text, format="json")
    assert str(info.value) == case.message


def test_good_rows_before_the_error_are_delivered_first(source_ctx: SourceContext) -> None:
    from sankey_studio.models import TextSource
    from sankey_studio.sources import open_source
    from sankey_studio.sources.base import Diagnostics

    spec = TextSource(content='{"source":"a","target":"b","value":1}\n{"source": ', format="json")
    rows = open_source(spec, source_ctx).iter_links(Diagnostics())
    assert next(rows) == R1
    with pytest.raises(SourceError, match=r"^inline:2: invalid JSON"):
        next(rows)
