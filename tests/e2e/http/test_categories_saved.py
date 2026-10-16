# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E A.3 (categories): reserved names and limits are refused; categories survive a save."""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.http_a_categories import entry, preview, rule, slices
from tests.e2e.support.http_a_library import update_body

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer

RESERVED = ["Other", "Uncategorized", "other", "UNCATEGORIZED", "  Other  "]
REFUSED = "are reserved names"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: the tests use their own graph names."""
    return module_server


def refused(api: httpx.Client, transform: dict[str, Any]) -> list[str]:
    """The 422 detail lines of a preview with this transform."""
    answer = api.post("/api/v1/preview", json=graph_draft(BUDGET.csv, transform=transform))
    error = json_of(answer, 422)["error"]
    assert error["code"] == "validation_error"
    return list(error["details"])


@pytest.mark.parametrize("name", RESERVED)
def test_reserved_names_are_refused_for_entries_and_rules(api: httpx.Client, name: str) -> None:
    for transform, path in (
        ({"entry_categories": [entry("Budget", "Rent", name)]}, "entry_categories.0.category"),
        ({"category_rules": [rule("either", "*", name)]}, "category_rules.0.category"),
    ):
        details = refused(api, transform)
        assert len(details) == 1
        assert details[0].startswith(f"body.transform.{path}:")
        assert REFUSED in details[0]


def test_a_reserved_name_in_the_data_is_dropped_with_a_warning(api: httpx.Client) -> None:
    content = "source,target,value,category\nA,B,1,Other\nB,C,2,Real\n"
    bundle = preview(api, content)
    assert slices(bundle) == {"Real": 2.0, "Uncategorized": 1.0}
    [warning] = bundle["warnings"]
    assert warning.endswith("1 using the reserved names Uncategorized/Other")
    assert warning.startswith("Categories ignored")


@pytest.mark.parametrize(
    ("transform", "fragment"),
    [
        ({"entry_categories": [entry("A", "B", "x" * 101)]}, "at most 100 characters"),
        ({"category_rules": [rule("either", "*", "x" * 101)]}, "at most 100 characters"),
        ({"category_rules": [rule("either", "", "X")]}, "at least 1 character"),
        ({"category_rules": [rule("both", "*", "X")]}, "'source', 'target' or 'either'"),
        (
            {"entry_categories": [entry("A", "B", "X"), entry("A", "B", "Y")]},
            "must not repeat a (source, target) pair",
        ),
        ({"category_rules": [rule("either", "*", "X")] * 201}, "at most 200 items"),
        ({"rules_override": "yes please"}, "valid boolean"),
        ({"entry_categories": [{"source": "A", "target": "B"}]}, "Field required"),
    ],
    ids=[
        "entry-too-long",
        "rule-too-long",
        "empty-pattern",
        "bad-match",
        "repeated-pair",
        "too-many-rules",
        "override-not-a-bool",
        "category-missing",
    ],
)
def test_malformed_category_input_is_a_clear_422(
    api: httpx.Client, transform: dict[str, Any], fragment: str
) -> None:
    details = refused(api, transform)
    assert any(fragment in line for line in details), details
    assert all("x" * 50 not in line for line in details)  # the submitted text is never echoed


def test_a_category_is_trimmed_and_the_data_spelling_is_merged_case_insensitively(
    api: httpx.Client,
) -> None:
    chosen = preview(api, BUDGET.csv, {"entry_categories": [entry("Budget", "Rent", " Housing ")]})
    assert slices(chosen)["Housing"] == 1200.0
    content = "source,target,value,category\nA,B,1,food\nB,C,2,Food\nC,D,4,FOOD\n"
    merged = slices(preview(api, content))
    assert merged == {"food": 7.0}  # one slice, named after the first spelling seen


def test_categories_survive_a_save_and_clearing_them_removes_the_donut(
    api: httpx.Client,
) -> None:
    transform = {
        "entry_categories": [entry("Budget", "Rent", "Housing"), entry("Budget", "Food", None)],
        "category_rules": [rule("target", "Util*", "Bills")],
    }
    saved = seed_graph(
        api, unique_name("Categorised"), graph_draft(BUDGET_CATEGORISED.csv, transform=transform)
    )
    stored = json_of(api.get(f"/api/v1/graphs/{saved['id']}"))
    assert stored["transform"]["entry_categories"] == transform["entry_categories"]
    assert stored["transform"]["category_rules"] == transform["category_rules"]
    bundle = json_of(api.get(f"/api/v1/graphs/{saved['id']}/render"))
    assert slices(bundle) == slices(preview(api, BUDGET_CATEGORISED.csv, transform))
    assert slices(bundle)["Uncategorized"] == 640.0  # Food was cleared on purpose

    cleared = update_body(
        stored,
        source=graph_draft(BUDGET.csv)["source"],  # a source without categories ...
        transform={"entry_categories": [], "category_rules": []},  # ... and no choices
    )
    updated = json_of(api.put(f"/api/v1/graphs/{saved['id']}", json=cleared))
    assert updated["revision"] == stored["revision"] + 1
    after = json_of(api.get(f"/api/v1/graphs/{saved['id']}/render"))
    assert (after["donut"], after["donut_empty_reason"]) == (None, "no_categories")
    again = api.get(
        f"/api/v1/graphs/{saved['id']}/export", params={"chart": "donut", "format": "csv"}
    )
    assert json_of(again, 422)["error"]["code"] == "no_categories"


def test_the_donut_csv_of_a_categorised_graph_matches_the_table(api: httpx.Client) -> None:
    saved = seed_graph(api, unique_name("Donut csv"), graph_draft(BUDGET_CATEGORISED.csv))
    answer = api.get(
        f"/api/v1/graphs/{saved['id']}/export", params={"chart": "donut", "format": "csv"}
    )
    assert answer.status_code == 200
    rows = list(csv.reader(answer.text.splitlines()))
    assert rows[0] == ["category", "value", "share"]
    exported = {row[0]: float(row[1]) for row in rows[1:]}
    assert exported == pytest.approx(dict(BUDGET_CATEGORISED.categories))
    assert sum(float(row[2]) for row in rows[1:]) == pytest.approx(1.0)
