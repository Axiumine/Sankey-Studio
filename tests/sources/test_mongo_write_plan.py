"""``mongo_write_plan``: the filter, update and document of an edit written back to MongoDB."""

from __future__ import annotations

from typing import Any

import pytest

from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import AddEntry, MongoSource, SetCategory
from sankey_studio.sources.mongo_write_plan import (
    ALIASES_MAX,
    Insert,
    PairUpdate,
    equality_fields,
    plan_insert,
    plan_pair_update,
    resolve_database,
)


def spec(**fields: Any) -> MongoSource:
    base: dict[str, Any] = {"connection": "test", "collection": "flows", "category_field": "cat"}
    return MongoSource.model_validate({**base, **fields})


def setcat(
    source: str = "Budget", target: str = "Food", category: str | None = "Fun"
) -> SetCategory:
    return SetCategory(op="set_category", source=source, target=target, category=category)


def add(**fields: Any) -> AddEntry:
    base: dict[str, Any] = {"op": "add_entry", "source": "Budget", "target": "Gifts", "value": 50}
    return AddEntry.model_validate({**base, **fields})


def reason_of(call: Any, *args: Any) -> str:
    with pytest.raises(SourceEditRefused) as info:
        call(*args)
    return info.value.reason


# --------------------------------------------------------------------------- database


DATABASES = {
    "the source names one": ("shop", "main", "shop"),
    "the default is used": (None, "main", "main"),
    "the source wins over the default": ("shop", None, "shop"),
}


@pytest.mark.parametrize(("own", "default", "expected"), DATABASES.values(), ids=DATABASES)
def test_the_database_is_the_sources_or_the_connections(
    own: str | None, default: str | None, expected: str
) -> None:
    assert resolve_database(spec(database=own), default) == expected


@pytest.mark.parametrize("default", [None, ""])
def test_no_database_at_all_is_an_incomplete_source(default: str | None) -> None:
    assert reason_of(resolve_database, spec(), default) == "source_incomplete"


# --------------------------------------------------------------------------- set_category


def test_a_pair_update_selects_the_pair_and_sets_the_category() -> None:
    assert plan_pair_update(spec(), setcat(), {}) == PairUpdate(
        filter={
            "$and": [
                {"source": {"$in": ["Budget"]}},
                {"target": {"$in": ["Food"]}},
            ]
        },
        update={"$set": {"cat": "Fun"}},
    )


def test_a_cleared_category_unsets_the_field() -> None:
    plan = plan_pair_update(spec(), setcat(category=None), {})
    assert plan.update == {"$unset": {"cat": ""}}


def test_the_users_filter_is_the_first_clause_and_stays_untouched() -> None:
    source = spec(filter={"year": 2025, "kind": {"$in": ["a", "b"]}})
    plan = plan_pair_update(source, setcat(), {})
    assert plan.filter["$and"][0] == {"year": 2025, "kind": {"$in": ["a", "b"]}}
    assert len(plan.filter["$and"]) == 3
    plan.filter["$and"][0]["kind"]["$in"].append("c")  # the plan holds its own copy
    assert source.filter == {"year": 2025, "kind": {"$in": ["a", "b"]}}


def test_the_mapped_fields_are_the_sources_own_dotted_paths() -> None:
    source = spec(source_field="meta.from", target_field="meta.to", category_field="meta.cat")
    plan = plan_pair_update(source, setcat(), {})
    assert plan.filter == {
        "$and": [{"meta.from": {"$in": ["Budget"]}}, {"meta.to": {"$in": ["Food"]}}]
    }
    assert plan.update == {"$set": {"meta.cat": "Fun"}}


def test_every_merged_spelling_of_a_node_is_matched() -> None:
    alias = {"Bud": "Budget", "B.": "Budget", "Meals": "Food", "Other": "Elsewhere"}
    plan = plan_pair_update(spec(), setcat(), alias)
    assert plan.filter == {
        "$and": [
            {"source": {"$in": ["B.", "Bud", "Budget"]}},
            {"target": {"$in": ["Food", "Meals"]}},
        ]
    }


def test_an_alias_spelling_in_the_edit_resolves_to_the_same_documents() -> None:
    alias = {"Bud": "Budget"}
    assert plan_pair_update(spec(), setcat(source="Bud"), alias) == plan_pair_update(
        spec(), setcat(source="Budget"), alias
    )


def aliases_for(name: str, count: int) -> dict[str, str]:
    return {f"{name}-{index}": name for index in range(count)}


@pytest.mark.parametrize("side", ["source", "target"])
def test_the_alias_limit_is_200_names_including_the_canonical_one(side: str) -> None:
    assert ALIASES_MAX == 200
    edit = setcat()
    name = getattr(edit, side)
    at_limit = plan_pair_update(spec(), edit, aliases_for(name, ALIASES_MAX - 1))
    assert len(at_limit.filter["$and"][0 if side == "source" else 1][side]["$in"]) == 200
    assert reason_of(plan_pair_update, spec(), edit, aliases_for(name, ALIASES_MAX)) == (
        "too_many_aliases"
    )


def test_the_aliases_of_other_nodes_do_not_count() -> None:
    alias = {**aliases_for("Elsewhere", 300), "Bud": "Budget"}
    plan = plan_pair_update(spec(), setcat(), alias)
    assert plan.filter["$and"][0] == {"source": {"$in": ["Bud", "Budget"]}}


SET_REFUSALS = {
    "aggregate": ({"mode": "aggregate", "pipeline": [{"$match": {}}]}, "aggregate_mode"),
    "no category field": ({"category_field": None}, "no_category_field"),
    "category is the source": ({"category_field": "source"}, "field_conflict"),
    "category is the target": ({"category_field": "target"}, "field_conflict"),
    "category inside the source": (
        {"source_field": "meta", "category_field": "meta.cat"},
        "field_conflict",
    ),
    "source inside the category": (
        {"category_field": "meta", "source_field": "meta.from"},
        "field_conflict",
    ),
    "category in the filter": ({"filter": {"cat": "x"}}, "field_conflict"),
    "category in an $and of the filter": (
        {"filter": {"$and": [{"year": 1}, {"cat": {"$ne": "x"}}]}},
        "field_conflict",
    ),
    "category inside a filter field": (
        {"filter": {"cat.sub": 1}},
        "field_conflict",
    ),
    "filter field inside the category": (
        {"category_field": "meta.cat", "filter": {"meta": {"$exists": True}}},
        "field_conflict",
    ),
    "category is the value": (
        {"value_field": "amount", "category_field": "amount"},
        "field_conflict",
    ),
    "category is the default value field": ({"category_field": "value"}, "field_conflict"),
    "category inside the value": (
        {"value_field": "amount", "category_field": "amount.x"},
        "field_conflict",
    ),
    "value inside the category": (
        {"value_field": "amount.v", "category_field": "amount"},
        "field_conflict",
    ),
    "category is _id": ({"category_field": "_id"}, "field_conflict"),
    "source is _id": ({"source_field": "_id"}, "field_conflict"),
    "target inside _id": ({"target_field": "_id.k"}, "field_conflict"),
}


@pytest.mark.parametrize(("fields", "reason"), SET_REFUSALS.values(), ids=SET_REFUSALS)
def test_a_pair_update_refusals(fields: dict[str, Any], reason: str) -> None:
    assert reason_of(plan_pair_update, spec(**fields), setcat(), {}) == reason


SET_ACCEPTED = {
    "names that merely share a prefix": {"source_field": "meta", "category_field": "metadata"},
    "siblings under one parent": {
        "source_field": "m.from",
        "target_field": "m.to",
        "category_field": "m.c",
    },
    "an operator-only filter field": {"filter": {"$or": [{"year": 1}, {"year": 2}]}},
    "no value field": {"value_field": None, "category_field": "cat"},
    "an id lookalike": {"category_field": "_idx"},
    "a nested _id is another field": {"category_field": "a._id"},
}


@pytest.mark.parametrize("fields", SET_ACCEPTED.values(), ids=SET_ACCEPTED)
def test_a_pair_update_that_is_not_a_conflict(fields: dict[str, Any]) -> None:
    assert isinstance(plan_pair_update(spec(**fields), setcat(), {}), PairUpdate)


def test_the_mode_is_checked_before_the_category_field() -> None:
    both = spec(mode="aggregate", pipeline=[{"$match": {}}], category_field=None)
    assert reason_of(plan_pair_update, both, setcat(), {}) == "aggregate_mode"


UNSAFE_PAIRS = {
    "a node that reads as a server variable": (setcat(source="$$USER_ROLES"), "unsafe_value"),
    "a formula as the category": (setcat(category="=1+1"), "unsafe_value"),
    "a plus sign as the category": (setcat(category="+1"), "unsafe_value"),
    "a variable name in the target": (setcat(target="$$SEARCH_META"), "unsafe_value"),
}


@pytest.mark.parametrize(("edit", "reason"), UNSAFE_PAIRS.values(), ids=UNSAFE_PAIRS)
def test_unsafe_text_in_a_pair_update_stays_in_the_graph(edit: SetCategory, reason: str) -> None:
    assert reason_of(plan_pair_update, spec(), edit, {}) == reason


def test_a_filter_too_large_for_the_guard_is_unsafe() -> None:
    long = "n" * 190
    alias = {f"{side}{long}{index:03d}": side for side in "ST" for index in range(ALIASES_MAX - 1)}
    edit = setcat(source="S", target="T")
    assert reason_of(plan_pair_update, spec(), edit, alias) == "unsafe_value"


# --------------------------------------------------------------------------- equality filters

EQUALITY = {
    "empty": ({}, {}),
    "scalars": (
        {"year": 2025, "kind": "a", "ok": True, "gone": None, "ratio": 0.5},
        {"year": 2025, "kind": "a", "ok": True, "gone": None, "ratio": 0.5},
    ),
    "explicit $eq": ({"year": {"$eq": 2025}}, {"year": 2025}),
    "dotted": ({"meta.year": 2025}, {"meta.year": 2025}),
}


@pytest.mark.parametrize(("flt", "expected"), EQUALITY.values(), ids=EQUALITY)
def test_equality_fields(flt: dict[str, Any], expected: dict[str, Any]) -> None:
    assert equality_fields(flt) == expected


NOT_EQUALITY = {
    "a range": {"year": {"$gt": 1}},
    "$eq with a neighbour": {"year": {"$eq": 1, "$ne": 2}},
    "$ne": {"year": {"$ne": 1}},
    "$in": {"year": {"$in": [1]}},
    "an array": {"tags": [1]},
    "a sub-document": {"a": {"b": 1}},
    "$eq of a document": {"a": {"$eq": {"b": 1}}},
    "$eq of an array": {"a": {"$eq": [1]}},
    "$or": {"$or": [{"a": 1}]},
    "$and": {"$and": [{"a": 1}]},
    "$expr": {"$expr": {"$eq": ["$a", 1]}},
    "a fine field next to an operator": {"a": 1, "$or": []},
}


@pytest.mark.parametrize("flt", NOT_EQUALITY.values(), ids=NOT_EQUALITY)
def test_anything_but_equality_is_refused(flt: dict[str, Any]) -> None:
    assert reason_of(equality_fields, flt) == "filter_not_equality"


# --------------------------------------------------------------------------- add_entry


def test_the_design_example_builds_the_nested_document() -> None:
    source = spec(
        source_field="meta.from",
        target_field="meta.to",
        value_field="amount",
        category_field="cat",
        filter={"year": 2025},
    )
    assert plan_insert(source, add(category="Fun")) == Insert(
        {"meta": {"from": "Budget", "to": "Gifts"}, "amount": 50, "cat": "Fun", "year": 2025}
    )


def test_a_flat_document_without_a_category() -> None:
    plan = plan_insert(spec(), add())
    assert plan.document == {"source": "Budget", "target": "Gifts", "value": 50}


def test_an_unset_category_is_left_out_even_when_the_field_is_mapped() -> None:
    assert "cat" not in plan_insert(spec(), add(category=None)).document


def test_an_explicit_equality_filter_is_merged() -> None:
    source = spec(filter={"year": {"$eq": 2025}, "meta.team": "a", "live": True, "x": None})
    document = plan_insert(source, add()).document
    assert document == {
        "source": "Budget",
        "target": "Gifts",
        "value": 50,
        "year": 2025,
        "meta": {"team": "a"},
        "live": True,
        "x": None,
    }


VALUES = {
    "integral": (50.0, 50, int),
    "fractional": (12.5, 12.5, float),
    "tiny": (1e-07, 1e-07, float),
    "largest exact integer": (float(2**53 - 1), 2**53 - 1, int),
    "first inexact integer": (float(2**53), float(2**53), float),
    "huge": (1e300, 1e300, float),
}


@pytest.mark.parametrize(("value", "expected", "kind"), VALUES.values(), ids=VALUES)
def test_an_integral_value_is_stored_as_an_integer(
    value: float, expected: float, kind: type
) -> None:
    stored = plan_insert(spec(), add(value=value)).document["value"]
    assert stored == expected
    assert type(stored) is kind


INSERT_REFUSALS = {
    "aggregate": ({"mode": "aggregate", "pipeline": [{"$match": {}}]}, {}, "aggregate_mode"),
    "no value field": ({"value_field": None}, {}, "no_value_field"),
    "category without a field": (
        {"category_field": None},
        {"category": "Fun"},
        "no_category_field",
    ),
    "range filter": ({"filter": {"year": {"$gt": 1}}}, {}, "filter_not_equality"),
    "or filter": ({"filter": {"$or": [{"a": 1}]}}, {}, "filter_not_equality"),
    "filter field is the value": ({"filter": {"value": 1}}, {}, "field_conflict"),
    "filter field is the source": ({"filter": {"source": "x"}}, {}, "field_conflict"),
    "filter inside the target": ({"target_field": "m", "filter": {"m.x": 1}}, {}, "field_conflict"),
    "filter field is the category": (
        {"filter": {"cat": "x"}},
        {"category": "Fun"},
        "field_conflict",
    ),
    "source equals target": ({"target_field": "source"}, {}, "field_conflict"),
    "source inside value": ({"value_field": "source.v"}, {}, "field_conflict"),
    "filter fields nest": ({"filter": {"a": 1, "a.b": 2}}, {}, "field_conflict"),
    "id in the filter": ({"filter": {"_id": 5}}, {}, "field_conflict"),
    "id as a mapped field": ({"source_field": "_id"}, {}, "field_conflict"),
    "formula in the source": ({}, {"source": "=cmd"}, "unsafe_value"),
    "formula in the category": ({}, {"category": "@x"}, "unsafe_value"),
    "formula in a filter value": ({"filter": {"note": "-1"}}, {}, "unsafe_value"),
    "long filter value": ({"filter": {"note": "x" * 1001}}, {}, "unsafe_value"),
    "nan in the filter": ({"filter": {"ratio": float("nan")}}, {}, "unsafe_value"),
    "array index in the filter": ({"filter": {"a.0": 1}}, {}, "unsafe_value"),
    "operator-looking field": ({"filter": {"a$b": 1}}, {}, "unsafe_value"),
    "too deep": ({"source_field": "a.b.c.d.e"}, {}, "unsafe_value"),
}


@pytest.mark.parametrize(
    ("fields", "edit", "reason"), INSERT_REFUSALS.values(), ids=INSERT_REFUSALS
)
def test_an_insert_refusals(fields: dict[str, Any], edit: dict[str, Any], reason: str) -> None:
    assert reason_of(plan_insert, spec(**fields), add(**edit)) == reason


def test_the_checks_run_in_a_fixed_order() -> None:
    several = spec(
        mode="aggregate", pipeline=[{"$match": {}}], value_field=None, filter={"a": {"$gt": 1}}
    )
    assert reason_of(plan_insert, several, add()) == "aggregate_mode"
    no_value = spec(value_field=None, category_field=None, filter={"a": {"$gt": 1}})
    assert reason_of(plan_insert, no_value, add(category="Fun")) == "no_value_field"
    no_category = spec(category_field=None, filter={"a": {"$gt": 1}})
    assert reason_of(plan_insert, no_category, add(category="Fun")) == "no_category_field"
    assert reason_of(plan_insert, no_category, add()) == "filter_not_equality"
