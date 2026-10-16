# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``mongo_extract``: dotted paths, the server-side projection, and whole-document extraction."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, NamedTuple

import pytest

from sankey_studio.models import MongoSource
from sankey_studio.sources.mongo_extract import (
    MISSING,
    FieldMap,
    RowParts,
    extract_row,
    get_path,
)

# --------------------------------------------------------------------------- get_path


class PathCase(NamedTuple):
    doc: dict[str, Any]
    path: str
    expected: object


PATH_CASES = {
    "top level": PathCase({"a": 1}, "a", 1),
    "nested": PathCase({"a": {"b": {"c": 5}}}, "a.b.c", 5),
    "a sub-document": PathCase({"a": {"b": 1}}, "a", {"b": 1}),
    "zero is a value": PathCase({"a": 0}, "a", 0),
    "null is a value, not missing": PathCase({"a": None}, "a", None),
    "empty string is a value": PathCase({"a": ""}, "a", ""),
    "absent top level": PathCase({"a": 1}, "b", MISSING),
    "absent nested": PathCase({"a": {"b": 1}}, "a.c", MISSING),
    "absent parent": PathCase({"a": 1}, "x.y", MISSING),
    "scalar on the way": PathCase({"a": 1}, "a.b", MISSING),
    "null on the way": PathCase({"a": None}, "a.b", MISSING),
    "arrays are not traversed": PathCase({"a": [{"b": 1}]}, "a.b", MISSING),
    "array index is not a key": PathCase({"a": [5]}, "a.0", MISSING),
    "digit keys are keys": PathCase({"a": {"0": 5}}, "a.0", 5),
    "any mapping is walked": PathCase({"a": MappingProxyType({"b": 7})}, "a.b", 7),
}


@pytest.mark.parametrize("case", PATH_CASES.values(), ids=PATH_CASES)
def test_get_path(case: PathCase) -> None:
    assert get_path(case.doc, case.path) == case.expected
    if case.expected is MISSING:
        assert get_path(case.doc, case.path) is MISSING


def test_get_path_walks_a_mapping_root() -> None:
    assert get_path(MappingProxyType({"a": {"b": 3}}), "a.b") == 3


# --------------------------------------------------------------------------- projection


class ProjectionCase(NamedTuple):
    fields: tuple[str, str, str | None, str | None]
    expected: dict[str, int]


PROJECTIONS = {
    "defaults": ProjectionCase(
        ("source", "target", "value", None), {"source": 1, "target": 1, "value": 1, "_id": 0}
    ),
    "no value field": ProjectionCase(
        ("source", "target", None, None), {"source": 1, "target": 1, "_id": 0}
    ),
    "with category": ProjectionCase(
        ("s", "t", "v", "c"), {"s": 1, "t": 1, "v": 1, "c": 1, "_id": 0}
    ),
    "dotted paths": ProjectionCase(
        ("a.from", "a.to", "m.v", "m.c"),
        {"a.from": 1, "a.to": 1, "m.v": 1, "m.c": 1, "_id": 0},
    ),
    "a parent hides its children": ProjectionCase(
        ("a", "a.b", "v", None), {"a": 1, "v": 1, "_id": 0}
    ),
    "a child below a later parent": ProjectionCase(
        ("a.b.c", "a.b", "a", "a.z"), {"a": 1, "_id": 0}
    ),
    "a name that merely starts like another": ProjectionCase(
        ("ab", "a", "v", None), {"a": 1, "ab": 1, "v": 1, "_id": 0}
    ),
    "one field used twice": ProjectionCase(("x", "x", "v", None), {"x": 1, "v": 1, "_id": 0}),
    "the _id field itself": ProjectionCase(("_id", "t", "v", None), {"_id": 1, "t": 1, "v": 1}),
    "below _id": ProjectionCase(
        ("_id.from", "_id.to", "v", None), {"_id.from": 1, "_id.to": 1, "v": 1}
    ),
    "a field that only starts with _id": ProjectionCase(
        ("_idx", "t", "v", None), {"_idx": 1, "t": 1, "v": 1, "_id": 0}
    ),
}


@pytest.mark.parametrize("case", PROJECTIONS.values(), ids=PROJECTIONS)
def test_projection(case: ProjectionCase) -> None:
    projection = FieldMap(*case.fields).projection()
    assert projection == case.expected
    assert all(type(flag) is int for flag in projection.values())


def test_field_map_comes_from_the_spec() -> None:
    spec = MongoSource(
        connection="test",
        collection="events",
        source_field="a.s",
        target_field="a.t",
        value_field=None,
        category_field="a.c",
    )
    assert FieldMap.from_spec(spec) == FieldMap("a.s", "a.t", None, "a.c")
    default = FieldMap.from_spec(MongoSource(connection="test", collection="events"))
    assert default == FieldMap("source", "target", "value", None)


# --------------------------------------------------------------------------- extract_row

FIELDS = FieldMap("source", "target", "value", "category")


def row(doc: dict[str, Any], fields: FieldMap = FIELDS) -> RowParts | str:
    return extract_row(doc, fields)


def test_a_good_document_becomes_row_parts() -> None:
    doc = {"source": " a ", "target": "b", "value": 2, "category": "Food"}
    assert row(doc) == RowParts("a", "b", 2.0, "Food", text_value=False)


def test_the_category_is_passed_on_raw_for_the_cleaner_to_judge() -> None:
    base = {"source": "a", "target": "b", "value": 1}
    assert row({**base, "category": ["x"]}) == RowParts("a", "b", 1.0, ["x"], text_value=False)
    assert row({**base, "category": None}) == RowParts("a", "b", 1.0, None, text_value=False)
    assert row(base) == RowParts("a", "b", 1.0, None, text_value=False)
    assert row({**base, "category": 5}) == RowParts("a", "b", 1.0, 5, text_value=False)


def test_a_category_field_that_is_not_configured_is_not_read() -> None:
    fields = FieldMap("source", "target", "value", None)
    doc = {"source": "a", "target": "b", "value": 1, "category": "Food"}
    assert row(doc, fields) == RowParts("a", "b", 1.0, None, text_value=False)


def test_a_numeric_string_value_is_flagged() -> None:
    doc = {"source": "a", "target": "b", "value": "2.5"}
    assert row(doc) == RowParts("a", "b", 2.5, None, text_value=True)


def test_without_a_value_field_every_document_counts_one() -> None:
    fields = FieldMap("source", "target", None, None)
    junk = {"source": "a", "target": "b", "value": "not a number"}
    assert row(junk, fields) == RowParts("a", "b", 1.0, None, text_value=False)
    assert row({"source": "a", "target": "b"}, fields) == RowParts(
        "a", "b", 1.0, None, text_value=False
    )


def test_dotted_paths_are_followed() -> None:
    fields = FieldMap("m.from", "m.to", "m.n", "m.k")
    doc = {"m": {"from": "a", "to": "b", "n": 3, "k": "Food"}}
    assert row(doc, fields) == RowParts("a", "b", 3.0, "Food", text_value=False)


class ProblemCase(NamedTuple):
    doc: dict[str, Any]
    fields: FieldMap
    message: str


PROBLEMS = {
    "missing source": ProblemCase(
        {"target": "b", "value": 1}, FIELDS, "source field 'source' is missing"
    ),
    "null target": ProblemCase(
        {"source": "a", "target": None, "value": 1}, FIELDS, "target field 'target' is null"
    ),
    "list source": ProblemCase(
        {"source": ["a"], "target": "b", "value": 1},
        FIELDS,
        "source field 'source' is not a single text or number value",
    ),
    "empty target": ProblemCase(
        {"source": "a", "target": " ", "value": 1}, FIELDS, "target field 'target' is empty"
    ),
    "missing value": ProblemCase(
        {"source": "a", "target": "b"}, FIELDS, "value field 'value' is missing"
    ),
    "zero value": ProblemCase(
        {"source": "a", "target": "b", "value": 0},
        FIELDS,
        "value field 'value' is not greater than zero",
    ),
    "text value": ProblemCase(
        {"source": "a", "target": "b", "value": "many"},
        FIELDS,
        "value field 'value' is not a number",
    ),
    "the source is judged before the target": ProblemCase(
        {"source": None, "target": None, "value": None}, FIELDS, "source field 'source' is null"
    ),
    "the target is judged before the value": ProblemCase(
        {"source": "a", "target": None, "value": None}, FIELDS, "target field 'target' is null"
    ),
    "the configured path is named": ProblemCase(
        {"m": {"to": "b"}, "n": 1},
        FieldMap("m.from", "m.to", "n", None),
        "source field 'm.from' is missing",
    ),
}


@pytest.mark.parametrize("case", PROBLEMS.values(), ids=PROBLEMS)
def test_a_bad_document_returns_the_reason(case: ProblemCase) -> None:
    assert row(case.doc, case.fields) == case.message


def test_the_reason_never_echoes_document_data() -> None:
    secret = "hunter2-secret-name"
    message = row({"source": secret * 30, "target": "b", "value": 1})
    assert message == "source field 'source' is longer than 200 characters"
    message = row({"source": "a", "target": "b", "value": secret})
    assert message == "value field 'value' is not a number"
