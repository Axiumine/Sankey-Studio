# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``MongoDataSource`` on an in-memory MongoDB: rows, categories, values and skipped documents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from bson import Decimal128, ObjectId

from sankey_studio.errors import SourceError

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.sources.conftest import MongoRunner, SpecFactory


CATEGORY_WARNING = "Categories ignored (entries kept uncategorised): "


def doc(source: object, target: object, value: object = 1, **extra: Any) -> dict[str, Any]:
    return {"source": source, "target": target, "value": value, **extra}


def test_documents_become_raw_links_in_order(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([doc("a", "b", 10), doc("b", "c", 2.5), doc("a", "c", 7)])
    result = mongo_run(mongo_spec())
    assert result.rows == [("a", "b", 10.0, None), ("b", "c", 2.5, None), ("a", "c", 7.0, None)]
    assert result.diag.warnings == []
    assert result.diag.skipped == 0
    assert all(type(row[2]) is float for row in result.rows)


def test_names_are_trimmed_and_driver_types_stringified(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    oid = ObjectId("0123456789abcdef01234567")
    mongo_seed([doc("  a ", 42, 1), doc(oid, 3.5, Decimal128("2.5"))])
    rows = mongo_run(mongo_spec()).rows
    assert rows == [("a", "42", 1.0, None), (str(oid), "3.5", 2.5, None)]


def test_dotted_paths_for_every_field(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([{"m": {"from": "a", "to": "b", "n": 4, "k": "Food"}, "junk": 1}])
    spec = mongo_spec(
        source_field="m.from", target_field="m.to", value_field="m.n", category_field="m.k"
    )
    assert mongo_run(spec).rows == [("a", "b", 4.0, "Food")]


def test_without_a_value_field_each_document_counts_one(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([{"source": "a", "target": "b"}, {"source": "a", "target": "b", "value": "x"}])
    result = mongo_run(mongo_spec(value_field=None))
    assert result.rows == [("a", "b", 1.0, None), ("a", "b", 1.0, None)]
    assert result.diag.warnings == []


def test_the_find_filter_selects_documents(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([doc("a", "b", 1, kind="x"), doc("c", "d", 2, kind="y"), doc("e", "f", 3, kind="x")])
    spec = mongo_spec(filter={"kind": "x", "value": {"$gte": 2}})
    assert mongo_run(spec).rows == [("e", "f", 3.0, None)]


def test_another_database_can_be_chosen_on_the_source(
    mongo_run: MongoRunner,
    mongo_spec: SpecFactory,
    mongo_seed: Callable[..., None],
    mongo_client: Any,
) -> None:
    mongo_seed([doc("default", "db")])
    mongo_client["other"]["events"].insert_one(doc("other", "db"))
    assert mongo_run(mongo_spec()).rows == [("default", "db", 1.0, None)]
    assert mongo_run(mongo_spec(database="other")).rows == [("other", "db", 1.0, None)]


def test_an_empty_collection_yields_nothing_and_no_warning(
    mongo_run: MongoRunner, mongo_spec: SpecFactory
) -> None:
    result = mongo_run(mongo_spec())
    assert result.rows == []
    assert result.diag.warnings == []


# --------------------------------------------------------------------------- categories


def test_a_category_is_only_read_when_the_source_names_the_field(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([doc("a", "b", 1, category="Food")])
    assert mongo_run(mongo_spec()).rows == [("a", "b", 1.0, None)]
    assert mongo_run(mongo_spec(category_field="category")).rows == [("a", "b", 1.0, "Food")]


def test_documents_where_only_some_have_the_category_are_all_kept(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed(
        [
            doc("a", "b", 1, category="Food"),
            doc("a", "c", 2),
            doc("a", "d", 3, category=None),
            doc("a", "e", 4, category="  Fast   Food "),
            doc("a", "f", 5, category=""),
        ]
    )
    result = mongo_run(mongo_spec(category_field="category"))
    assert [row[3] for row in result.rows] == ["Food", None, None, "Fast Food", None]
    assert len(result.rows) == 5
    assert result.diag.skipped == 0
    assert result.diag.warnings == []


def test_a_collection_where_no_document_has_a_category_skips_nothing(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([doc("a", "b"), doc("b", "c"), doc("c", "d")])
    result = mongo_run(mongo_spec(category_field="category"))
    assert [row[3] for row in result.rows] == [None, None, None]
    assert result.diag.skipped == 0
    assert result.diag.warnings == []


def test_unusable_categories_are_none_and_reported_once(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed(
        [
            doc("a", "b", 1, category=5),
            doc("a", "c", 1, category=True),
            doc("a", "d", 1, category=["x", "y"]),
            doc("a", "e", 1, category={"k": "v"}),
            doc("a", "f", 1, category="x" * 101),
            doc("a", "g", 1, category="Uncategorized"),
            doc("a", "h", 1, category="Other"),
            doc("a", "i", 1, category="bad\x01"),
            doc("a", "j", 1, category=b"bytes"),
        ]
    )
    result = mongo_run(mongo_spec(category_field="category"))
    assert [row[3] for row in result.rows] == ["5", None, None, None, None, None, None, None, None]
    assert result.diag.skipped == 0
    assert result.diag.warnings == [
        CATEGORY_WARNING
        + "4 not a single text/number value; 1 longer than 100 characters; "
        + "1 containing control characters; 2 using the reserved names Uncategorized/Other"
    ]


def test_skipped_documents_do_not_count_towards_category_problems(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([doc("a", "b", 0, category=["bad"]), doc("a", "c", 1, category="Food")])
    result = mongo_run(mongo_spec(category_field="category"))
    assert result.rows == [("a", "c", 1.0, "Food")]
    assert result.diag.warnings == ["document 1: value field 'value' is not greater than zero"]


# --------------------------------------------------------------------------- bad documents


def test_unusable_documents_are_skipped_with_numbered_warnings(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed(
        [
            doc("a", "b", 1),
            {"target": "x", "value": 1},
            doc("a", "b", 0),
            doc("a", "b", -2),
            doc("a", "b", float("nan")),
            doc("a", "b", None),
            doc(["a"], "b", 1),
            doc("a", True, 1),
            doc("", "b", 1),
            doc("a", "x" * 201, 1),
            doc("a", "b", 3),
        ]
    )
    result = mongo_run(mongo_spec())
    assert result.rows == [("a", "b", 1.0, None), ("a", "b", 3.0, None)]
    assert result.diag.skipped == 9
    assert result.diag.warnings == [
        "document 2: source field 'source' is missing",
        "document 3: value field 'value' is not greater than zero",
        "document 4: value field 'value' is not greater than zero",
        "document 5: value field 'value' is not a finite number",
        "document 6: value field 'value' is null",
        "document 7: source field 'source' is not a single text or number value",
        "document 8: target field 'target' is not a single text or number value",
        "document 9: source field 'source' is empty",
        "document 10: target field 'target' is longer than 200 characters",
    ]


def test_numeric_strings_are_read_and_reported_once(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([doc("a", "b", "2.5"), doc("a", "c", 3), doc("a", "d", " 4 ")])
    result = mongo_run(mongo_spec())
    assert [row[2] for row in result.rows] == [2.5, 3.0, 4.0]
    assert result.diag.warnings == ["Read 2 text value(s) as numbers"]
    assert result.diag.skipped == 0


def test_strict_mode_stops_at_the_first_bad_document(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([doc("a", "b", 1), doc("a", "b", 0), doc("a", "c", 1)])
    with pytest.raises(SourceError) as info:
        mongo_run(mongo_spec(), strict=True)
    assert info.value.message == "document 2: value field 'value' is not greater than zero"


def test_strict_mode_accepts_clean_data(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed([doc("a", "b", 1)])
    assert mongo_run(mongo_spec(), strict=True).rows == [("a", "b", 1.0, None)]


# --------------------------------------------------------------------------- aggregate


def test_aggregate_output_documents_are_the_flows(
    mongo_run: MongoRunner, mongo_spec: SpecFactory, mongo_seed: Callable[..., None]
) -> None:
    mongo_seed(
        [
            {"src": "a", "dst": "b", "n": 1, "keep": True},
            {"src": "a", "dst": "b", "n": 4, "keep": True},
            {"src": "x", "dst": "y", "n": 9, "keep": False},
        ]
    )
    pipeline = [
        {"$match": {"keep": True}},
        {"$group": {"_id": {"s": "$src", "t": "$dst"}, "total": {"$sum": "$n"}}},
        {"$project": {"_id": 0, "source": "$_id.s", "target": "$_id.t", "value": "$total"}},
    ]
    result = mongo_run(mongo_spec(mode="aggregate", pipeline=pipeline))
    assert result.rows == [("a", "b", 5.0, None)]
    assert result.diag.warnings == []
