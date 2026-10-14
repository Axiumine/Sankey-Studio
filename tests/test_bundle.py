"""``RenderBundle`` / ``BundleStats``: field set, JSON shape and the donut consistency rules."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from sankey_studio.bundle import BundleStats, RenderBundle
from sankey_studio.render.legend import LegendItem
from sankey_studio.render.tables import CategoryRow, EntryRow, NodeRow

DONUT: dict[str, Any] = {"data": [], "layout": {}}


def stats(**fields: Any) -> BundleStats:
    values: dict[str, Any] = {
        "nodes": 2,
        "links": 1,
        "drawn_links": 1,
        "total_in": 3.5,
        "total_out": 2.5,
        "layers": 2,
        "category_count": 0,
    }
    return BundleStats(**{**values, **fields})


def bundle(**fields: Any) -> RenderBundle:
    values: dict[str, Any] = {
        "figure": {"data": [], "layout": {}},
        "legend": [],
        "donut_available": False,
        "donut": None,
        "donut_empty_reason": "no_categories",
        "categories": [],
        "category_names": [],
        "stats": stats(),
        "entries": [],
        "entries_total": 0,
        "warnings": [],
    }
    return RenderBundle(**{**values, **fields})


def first_message(exc: pytest.ExceptionInfo[ValidationError]) -> str:
    errors = exc.value.errors(include_input=False, include_context=False, include_url=False)
    assert len(errors) == 1
    return errors[0]["msg"]


def test_the_bundle_has_exactly_the_documented_fields() -> None:
    dumped = bundle().model_dump(mode="json")
    assert set(dumped) == {
        "figure",
        "legend",
        "donut_available",
        "donut",
        "donut_empty_reason",
        "categories",
        "category_names",
        "stats",
        "entries",
        "entries_total",
        "nodes",
        "warnings",
    }
    assert "donut_legend" not in dumped
    assert dumped["nodes"] == []


def test_the_stats_have_exactly_the_documented_fields() -> None:
    assert stats().model_dump() == {
        "nodes": 2,
        "links": 1,
        "drawn_links": 1,
        "total_in": 3.5,
        "total_out": 2.5,
        "layers": 2,
        "category_count": 0,
    }


def test_render_types_dump_as_plain_json_objects() -> None:
    full = bundle(
        legend=[
            LegendItem("Food", "#112233", "category", 4.5),
            LegendItem("Layer 1", "#fff", "layer"),
        ],
        categories=[CategoryRow("Food", "#112233", 4.5, 0.5, "category")],
        entries=[EntryRow("a", "b", 4.5, "Food", mixed=False, overridden=True)],
        category_names=["Food"],
        entries_total=1,
        warnings=["w"],
    )
    dumped = full.model_dump(mode="json")
    assert dumped["legend"] == [
        {"label": "Food", "color": "#112233", "kind": "category", "value": 4.5},
        {"label": "Layer 1", "color": "#fff", "kind": "layer", "value": None},
    ]
    assert dumped["categories"] == [
        {"name": "Food", "color": "#112233", "value": 4.5, "share": 0.5, "kind": "category"}
    ]
    assert dumped["entries"] == [
        {
            "source": "a",
            "target": "b",
            "value": 4.5,
            "category": "Food",
            "mixed": False,
            "overridden": True,
        }
    ]
    assert json.loads(json.dumps(dumped)) == dumped


def test_node_rows_dump_as_plain_json_objects_and_round_trip() -> None:
    full = bundle(nodes=[NodeRow("a", 0, 0.0, 3.5), NodeRow("b", 1, 3.5, 0.0)])
    dumped = full.model_dump(mode="json")
    assert dumped["nodes"] == [
        {"name": "a", "layer": 0, "node_in": 0.0, "node_out": 3.5},
        {"name": "b", "layer": 1, "node_in": 3.5, "node_out": 0.0},
    ]
    assert RenderBundle.model_validate_json(full.model_dump_json()) == full


def test_a_bundle_survives_a_json_round_trip() -> None:
    original = bundle(
        donut_available=True,
        donut=DONUT,
        donut_empty_reason="basis_empty",
        legend=[LegendItem("A", "#000000", "node")],
        entries=[EntryRow("a", "b", 1.0, None, mixed=False, overridden=False)],
        entries_total=1,
    )
    assert RenderBundle.model_validate_json(original.model_dump_json()) == original


@pytest.mark.parametrize(
    ("available", "donut", "reason"),
    [
        (False, None, "no_categories"),
        (True, DONUT, None),
        (True, DONUT, "basis_empty"),
    ],
    ids=["no categories", "drawn donut", "empty basis"],
)
def test_the_consistent_donut_states_are_accepted(
    available: bool, donut: dict[str, Any] | None, reason: str | None
) -> None:
    made = bundle(donut_available=available, donut=donut, donut_empty_reason=reason)
    assert (made.donut_available, made.donut, made.donut_empty_reason) == (available, donut, reason)


NEEDS_DONUT = "donut must be set when donut_available is true"
NO_DONUT = "donut must be null when donut_available is false"
REASON = "donut_empty_reason is 'no_categories' exactly when there is no donut"


@pytest.mark.parametrize(
    ("available", "donut", "reason", "message"),
    [
        (True, None, None, NEEDS_DONUT),
        (True, None, "no_categories", NEEDS_DONUT),
        (False, DONUT, "no_categories", NO_DONUT),
        (False, DONUT, None, NO_DONUT),
        (True, DONUT, "no_categories", REASON),
        (False, None, None, REASON),
        (False, None, "basis_empty", REASON),
    ],
)
def test_contradicting_donut_fields_are_refused_with_a_clear_message(
    available: bool, donut: dict[str, Any] | None, reason: str | None, message: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        bundle(donut_available=available, donut=donut, donut_empty_reason=reason)
    assert first_message(caught) == f"Value error, {message}"


def test_unknown_fields_and_reasons_are_refused() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        bundle(donut_legend=[])
    with pytest.raises(ValidationError, match="extra_forbidden"):
        stats(extra=1)
    with pytest.raises(ValidationError, match="literal_error"):
        bundle(donut_empty_reason="other")
