"""``suggest_fields``: name heuristics, fallbacks and the guarantees about the result."""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest

from sankey_studio.models import MongoSource
from sankey_studio.sources.mongo_suggest import FieldSuggestion, leaf_samples, suggest_fields


class Case(NamedTuple):
    docs: list[dict[str, Any]]
    expected: FieldSuggestion


def suggestion(
    source: str = "source",
    target: str = "target",
    value: str = "value",
    category: str | None = None,
) -> FieldSuggestion:
    return FieldSuggestion(source, target, value, category)


NAMED = {
    "the product's own names": Case(
        [{"source": "a", "target": "b", "value": 5, "category": "c"}],
        suggestion("source", "target", "value", "category"),
    ),
    "from / to / amount / type": Case(
        [{"from": "a", "to": "b", "amount": 5, "type": "x"}],
        suggestion("from", "to", "amount", "type"),
    ),
    "src / dst / qty": Case([{"src": "a", "dst": "b", "qty": 2}], suggestion("src", "dst", "qty")),
    "origin / dest / count / kind": Case(
        [{"origin": "a", "dest": "b", "count": 2, "kind": "k"}],
        suggestion("origin", "dest", "count", "kind"),
    ),
    "destination / quantity / group": Case(
        [{"src": "a", "destination": "b", "quantity": 2, "group": "g"}],
        suggestion("src", "destination", "quantity", "group"),
    ),
    "total": Case([{"from": "a", "to": "b", "total": 9}], suggestion("from", "to", "total")),
    "case does not matter": Case(
        [{"From": "a", "TO": "b", "Amount": 3, "Type": "t"}],
        suggestion("From", "TO", "Amount", "Type"),
    ),
    "the first listed name wins (source over src over from)": Case(
        [{"from": "c", "src": "b", "source": "a", "to": "t"}],
        suggestion("source", "to"),
    ),
    "the first listed target name wins": Case(
        [{"from": "f", "dest": "d", "dst": "s", "target": "t"}],
        suggestion("from", "target"),
    ),
    "the first listed value name wins": Case(
        [{"total": 1, "quantity": 2, "qty": 3, "count": 4, "amount": 5, "value": 6}],
        suggestion(value="value"),
    ),
    "the first listed category name wins": Case(
        [{"from": "f", "to": "t", "group": "d", "kind": "c", "type": "b", "category": "a"}],
        suggestion("from", "to", category="category"),
    ),
    "nested paths": Case(
        [{"meta": {"from": "a", "to": "b"}, "amount": 5}],
        suggestion("meta.from", "meta.to", "amount"),
    ),
    "names beat depth": Case(
        [{"from": "a", "x": {"source": "b"}, "to": "c"}], suggestion("x.source", "to")
    ),
    "the shallowest path wins among equals": Case(
        [{"x": {"from": "deep"}, "from": "top", "to": "t"}], suggestion("from", "to")
    ),
    "the first seen wins among equals": Case(
        [{"z": {"from": "1"}, "a": {"from": "2"}, "to": "t"}], suggestion("z.from", "to")
    ),
    "three segments are the limit": Case(
        [{"a": {"b": {"from": "x"}}, "to": "t"}], suggestion("a.b.from", "to")
    ),
    "four segments are too deep": Case(
        [{"a": {"b": {"c": {"from": "x"}}}, "to": "t"}], suggestion(target="to")
    ),
    "numbers can be names": Case(
        [{"from": 1, "to": 2, "amount": 5}], suggestion("from", "to", "amount")
    ),
    "a numeric string is a usable value": Case(
        [{"from": "a", "to": "b", "amount": "12.5"}], suggestion("from", "to", "amount")
    ),
    "the samples of every document count": Case(
        [{"amount": None, "from": None}, {"amount": 4, "from": "a", "to": "b"}],
        suggestion("from", "to", "amount"),
    ),
    "a name with no usable value is skipped": Case(
        [{"count": 0, "total": 9, "from": "a", "to": "b"}], suggestion("from", "to", "total")
    ),
}


@pytest.mark.parametrize("case", NAMED.values(), ids=NAMED)
def test_named_fields(case: Case) -> None:
    assert suggest_fields(case.docs) == case.expected


FALLBACKS = {
    "no documents": Case([], suggestion()),
    "an empty document": Case([{}], suggestion()),
    "the first two text fields and the first number": Case(
        [{"a": "x", "b": "y", "n": 3}], suggestion("a", "b", "n")
    ),
    "a category by name is not taken by a fallback": Case(
        [{"kind": "k", "a": "x", "b": "y", "n": 2}], suggestion("a", "b", "n", "kind")
    ),
    "named fields are settled before fallbacks run": Case(
        [{"from": ["list"], "to": "t", "other": "o", "n": 1}], suggestion("other", "to", "n")
    ),
    "a fallback source never takes the named target": Case(
        [{"x": "x", "to": "t", "n": 1}], suggestion("x", "to", "n")
    ),
    "only one text field": Case([{"a": "x", "n": 1}], suggestion("a", "target", "n")),
    "a number that is not named but real": Case(
        [{"from": "a", "to": "b", "weird": 2.5}], suggestion("from", "to", "weird")
    ),
    "a numeric string is not a fallback value": Case(
        [{"from": "a", "to": "b", "id": "123"}], suggestion("from", "to")
    ),
    "a boolean is not a value": Case(
        [{"from": "a", "to": "b", "flag": True}], suggestion("from", "to")
    ),
    "a zero is not a value": Case([{"from": "a", "to": "b", "n": 0}], suggestion("from", "to")),
    "a named value that is not a number falls back": Case(
        [{"from": "a", "to": "b", "amount": "lots", "n": 5}], suggestion("from", "to", "n")
    ),
    "a category must be text": Case(
        [{"from": "a", "to": "b", "amount": 1, "type": 5}], suggestion("from", "to", "amount")
    ),
    "a blank category is no category": Case(
        [{"from": "a", "to": "b", "category": "  "}], suggestion("from", "to")
    ),
    "a boolean is not a name": Case(
        [{"from": True, "to": "b", "amount": 1}], suggestion("source", "to", "amount")
    ),
    "arrays are ignored": Case(
        [{"tags": ["x"], "from": "a", "to": "b", "amount": 1}], suggestion("from", "to", "amount")
    ),
    "a name inside an array is not a path": Case(
        [{"rows": [{"from": "a", "to": "b"}]}], suggestion()
    ),
    "a key with a dot is not a path": Case([{"from.x": "a", "to.y": "b"}], suggestion()),
    "a key with a space is not a path": Case(
        [{"my from": "a", "to": "b"}], suggestion(target="to")
    ),
    "a key that starts with a digit is not a path": Case(
        [{"1from": "a", "to": "b"}], suggestion(target="to")
    ),
    "an empty key is not a path": Case([{"": "a", "to": "b"}], suggestion(target="to")),
}


@pytest.mark.parametrize("case", FALLBACKS.values(), ids=FALLBACKS)
def test_fallbacks_and_defaults(case: Case) -> None:
    assert suggest_fields(case.docs) == case.expected


def test_a_field_is_never_suggested_twice() -> None:
    docs = [{"source": "a", "value": 1}]
    result = suggest_fields(docs)
    assert (result.source, result.target, result.value) == ("source", "target", "value")
    only_one = suggest_fields([{"name": "x", "value": 1}])
    assert (only_one.source, only_one.target) == ("name", "target")


ALL_DOCS = [case.docs for case in (*NAMED.values(), *FALLBACKS.values())]


@pytest.mark.parametrize("docs", ALL_DOCS)
def test_every_suggestion_is_a_valid_source_field(docs: list[dict[str, Any]]) -> None:
    result = suggest_fields(docs)
    spec = MongoSource(
        connection="test",
        collection="events",
        source_field=result.source,
        target_field=result.target,
        value_field=result.value,
        category_field=result.category,
    )
    assert spec.source_field == result.source


def test_the_suggestion_is_a_frozen_value() -> None:
    result = suggestion()
    assert result == FieldSuggestion("source", "target", "value", None)
    with pytest.raises(AttributeError):
        result.source = "x"  # type: ignore[misc]


# --------------------------------------------------------------------------- leaf_samples


def test_leaf_samples_collect_scalars_by_path_in_first_seen_order() -> None:
    docs = [
        {"b": 1, "a": {"x": "p", "list": [1, 2]}},
        {"a": {"x": "q", "y": None}, "c": 2.5, "bad key": 1},
    ]
    leaves = leaf_samples(docs)
    assert leaves == {"b": [1], "a.x": ["p", "q"], "a.y": [None], "c": [2.5]}
    assert list(leaves) == ["b", "a.x", "a.y", "c"]


def test_leaf_samples_stop_at_three_segments() -> None:
    docs = [{"a": {"b": {"c": 1, "d": {"e": 2}}}}]
    assert leaf_samples(docs) == {"a.b.c": [1]}
