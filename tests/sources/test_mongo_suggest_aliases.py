"""``suggest_fields``: every alias of every field is recognised by NAME, not by the fallback.

A decoy field that comes first makes the text/number fallback pick the wrong path, so a name
that is dropped from (or misspelt in) a rule shows up as the decoy.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest

from sankey_studio.sources.mongo_suggest import FieldSuggestion, suggest_fields

DECOY = "zz_decoy"


class Alias(NamedTuple):
    docs: list[dict[str, Any]]
    expected: FieldSuggestion


def source_case(name: str) -> Alias:
    docs = [{DECOY: "d", name: "a", "to": "b"}]
    return Alias(docs, FieldSuggestion(name, "to", "value", None))


def target_case(name: str) -> Alias:
    docs = [{DECOY: "d", "from": "a", name: "b"}]
    return Alias(docs, FieldSuggestion("from", name, "value", None))


def value_case(name: str) -> Alias:
    docs = [{"from": "a", "to": "b", DECOY: 9, name: 5}]
    return Alias(docs, FieldSuggestion("from", "to", name, None))


def category_case(name: str) -> Alias:
    docs = [{"from": "a", "to": "b", DECOY: "d", name: "c"}]
    return Alias(docs, FieldSuggestion("from", "to", "value", name))


ALIASES = {
    **{f"source: {n}": source_case(n) for n in ("source", "src", "from", "origin")},
    **{f"target: {n}": target_case(n) for n in ("target", "dst", "to", "dest", "destination")},
    **{
        f"value: {n}": value_case(n)
        for n in ("value", "amount", "count", "qty", "quantity", "total")
    },
    **{f"category: {n}": category_case(n) for n in ("category", "type", "kind", "group")},
}


@pytest.mark.parametrize("case", ALIASES.values(), ids=ALIASES)
def test_each_alias_is_recognised_by_name(case: Alias) -> None:
    assert suggest_fields(case.docs) == case.expected
