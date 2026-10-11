"""``suggest_fields``: one unusable sample never hides a field, and the target name order."""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest

from sankey_studio.sources.mongo_suggest import FieldSuggestion, suggest_fields


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


# A decoy field comes first: a fallback would take it instead of the named field.
MIXED = {
    "a null name first": Case(
        [{"note": "n1", "from": None, "to": "b"}, {"note": "n2", "from": "a", "to": "b"}],
        suggestion("from", "to"),
    ),
    "an empty name first": Case(
        [{"note": "n1", "from": "", "to": "b"}, {"note": "n2", "from": "a", "to": "b"}],
        suggestion("from", "to"),
    ),
    "a boolean target first": Case(
        [{"note": "n1", "from": "a", "to": True}, {"note": "n2", "from": "a", "to": "b"}],
        suggestion("from", "to"),
    ),
    "a text amount, a zero and a good number": Case(
        [
            {"id": 7, "from": "a", "to": "b", "amount": "n/a"},
            {"id": 8, "amount": 0},
            {"id": 9, "amount": 4},
        ],
        suggestion("from", "to", "amount"),
    ),
    "a null amount first": Case(
        [{"id": 7, "from": "a", "to": "b", "qty": None}, {"id": 8, "qty": 2}],
        suggestion("from", "to", "qty"),
    ),
    "a negative amount first": Case(
        [{"id": 7, "from": "a", "to": "b", "total": -3}, {"id": 8, "total": 3}],
        suggestion("from", "to", "total"),
    ),
}


@pytest.mark.parametrize("case", MIXED.values(), ids=MIXED)
def test_a_field_is_suggested_when_any_sample_is_usable(case: Case) -> None:
    assert suggest_fields(case.docs) == case.expected


UNUSABLE = {
    "every name is null": Case(
        [{"from": None, "to": None}, {"from": None, "to": None}], suggestion()
    ),
    "every amount is text": Case(
        [{"from": "a", "to": "b", "amount": "n/a"}, {"amount": "x"}],
        suggestion("from", "to", "value"),
    ),
}


@pytest.mark.parametrize("case", UNUSABLE.values(), ids=UNUSABLE)
def test_a_named_field_without_a_usable_sample_is_not_suggested(case: Case) -> None:
    assert suggest_fields(case.docs) == case.expected


TARGET_ORDER = {
    "target before dst": Case(
        [{"dst": "d", "target": "t", "from": "f"}], suggestion("from", "target")
    ),
    "dst before to": Case([{"to": "t", "dst": "d", "from": "f"}], suggestion("from", "dst")),
    "to before dest": Case([{"dest": "d", "to": "t", "from": "f"}], suggestion("from", "to")),
    "to before destination": Case(
        [{"destination": "d", "to": "t", "from": "f"}], suggestion("from", "to")
    ),
    "dest before destination": Case(
        [{"destination": "d", "dest": "t", "from": "f"}], suggestion("from", "dest")
    ),
}


@pytest.mark.parametrize("case", TARGET_ORDER.values(), ids=TARGET_ORDER)
def test_the_target_names_are_tried_in_the_documented_order(case: Case) -> None:
    assert suggest_fields(case.docs) == case.expected
