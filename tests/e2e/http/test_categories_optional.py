# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E A.3 (categories are optional): no category means no donut, and nothing else is affected."""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import BUDGET, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.http_a_categories import entry, preview
from tests.e2e.support.http_a_exports import assert_download
from tests.e2e.support.http_a_library import update_body

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer

DONUT_EXPORTS = ["svg", "png", "html", "json", "csv"]


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: every test here is a pure computation or uses its own names."""
    return module_server


@pytest.fixture
def saved(api: httpx.Client) -> dict[str, object]:
    return seed_graph(api, unique_name("No categories"))


def test_a_graph_without_categories_renders_a_sankey_and_no_donut(api: httpx.Client) -> None:
    bundle = preview(api, BUDGET.csv)
    assert bundle["figure"]["data"][0]["type"] == "sankey"
    assert bundle["donut"] is None
    assert bundle["donut_available"] is False
    assert bundle["donut_empty_reason"] == "no_categories"
    assert (bundle["categories"], bundle["category_names"], bundle["legend"]) == ([], [], [])
    assert bundle["stats"]["category_count"] == 0
    assert bundle["warnings"] == []  # a missing donut is a state, not a problem


def test_the_saved_graph_renders_the_same_without_categories(
    api: httpx.Client, saved: dict[str, object]
) -> None:
    bundle = json_of(api.get(f"/api/v1/graphs/{saved['id']}/render"))
    assert (bundle["donut"], bundle["donut_empty_reason"]) == (None, "no_categories")
    assert bundle["stats"]["nodes"] == BUDGET.nodes


@pytest.mark.parametrize("fmt", DONUT_EXPORTS)
def test_the_donut_export_of_such_a_graph_is_a_422_in_every_format(
    api: httpx.Client, saved: dict[str, object], fmt: str
) -> None:
    refused = api.get(
        f"/api/v1/graphs/{saved['id']}/export", params={"chart": "donut", "format": fmt}
    )
    error = json_of(refused, 422)["error"]
    assert error["code"] == "no_categories"
    assert "no donut" in error["message"]
    assert "content-disposition" not in refused.headers  # nothing to download


def test_a_draft_donut_export_without_categories_is_refused_too(api: httpx.Client) -> None:
    refused = api.post(
        "/api/v1/export", params={"chart": "donut", "format": "csv"}, json=graph_draft()
    )
    assert json_of(refused, 422)["error"]["code"] == "no_categories"


@pytest.mark.parametrize("fmt", ["html", "json", "csv"])
def test_the_sankey_exports_work_without_categories(
    api: httpx.Client, saved: dict[str, object], fmt: str
) -> None:
    answer = api.get(f"/api/v1/graphs/{saved['id']}/export", params={"format": fmt})
    assert_download(answer, fmt)
    if fmt == "csv":
        lines = answer.text.splitlines()
        assert lines[0] == "source,target,value,category"
        assert len(lines) == BUDGET.links + 1
        rows = list(csv.reader(lines[1:]))
        assert ["Salary", "Budget", "3000.0", ""] in rows
    if fmt == "json":
        assert answer.json()["data"][0]["type"] == "sankey"
    if fmt == "html":
        assert "<title>" in answer.text


def test_adding_one_category_makes_the_donut_appear_and_the_exports_work(
    api: httpx.Client,
) -> None:
    graph = seed_graph(api, unique_name("Gains a category"))
    donut = {"chart": "donut", "format": "csv"}
    export = f"/api/v1/graphs/{graph['id']}/export"
    assert api.get(export, params=donut).status_code == 422
    transform = {**graph["transform"], "entry_categories": [entry("Budget", "Rent", "Housing")]}
    body = update_body(graph, transform=transform)
    assert api.put(f"/api/v1/graphs/{graph['id']}", json=body).status_code == 200
    after = api.get(export, params=donut)
    assert after.status_code == 200
    rows = list(csv.reader(after.text.splitlines()))
    assert rows[0] == ["category", "value", "share"]
    assert {row[0]: float(row[1]) for row in rows[1:]} == {
        "Housing": 1200.0,
        "Uncategorized": 7040.0,
    }
