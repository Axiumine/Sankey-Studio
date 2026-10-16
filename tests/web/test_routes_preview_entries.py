# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""POST /api/v1/entries: the server-paged entries table of an unsaved draft."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.web.routers import preview
from tests.web.test_routes_graphs_support import (
    API,
    BUDGET,
    code,
    csv_source,
    draft_json,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from tests.web.conftest import AppFactory, WebApp

URL = f"{API}/entries"
CSV_150 = {"source": csv_source(150)}


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([preview.router])


def page(client: TestClient, query: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(URL + query, json=body)
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result


def values(result: dict[str, Any]) -> list[float]:
    return [row["value"] for row in result["rows"]]


def pairs(result: dict[str, Any]) -> list[tuple[str, str]]:
    return [(row["source"], row["target"]) for row in result["rows"]]


def test_the_default_page_holds_100_of_the_largest_entries(client: TestClient) -> None:
    result = page(client, "", CSV_150)
    assert set(result) == {"rows", "total"}
    assert result["total"] == 150
    assert values(result) == [float(v) for v in range(150, 50, -1)]
    assert set(result["rows"][0]) == {
        "source",
        "target",
        "value",
        "category",
        "mixed",
        "overridden",
    }


def test_offset_and_limit_slice_the_ordered_rows(client: TestClient) -> None:
    result = page(client, "?offset=10&limit=5", CSV_150)
    assert values(result) == [140.0, 139.0, 138.0, 137.0, 136.0]
    assert result["total"] == 150


class Window(NamedTuple):
    query: str
    rows: int


@pytest.mark.parametrize(
    "case",
    [
        Window("?limit=1", 1),
        Window("?limit=500", 150),
        Window("?offset=149", 1),
        Window("?offset=150", 0),
        Window("?offset=1000", 0),
    ],
)
def test_the_window_edges_of_150_entries(client: TestClient, case: Window) -> None:
    result = page(client, case.query, CSV_150)
    assert len(result["rows"]) == case.rows
    assert result["total"] == 150


def test_a_page_never_holds_more_than_500_rows(client: TestClient) -> None:
    result = page(client, "?limit=500", {"source": csv_source(501)})
    assert len(result["rows"]) == 500
    assert result["total"] == 501


@pytest.mark.parametrize("query", ["?limit=501", "?limit=0", "?offset=-1", "?limit=x"])
def test_an_out_of_range_window_is_a_422(client: TestClient, query: str) -> None:
    response = client.post(URL + query, json=CSV_150)
    assert response.status_code == 422
    assert code(response) == "validation_error"


def test_q_matches_source_or_target_ignoring_case(client: TestClient) -> None:
    result = page(client, "?q=M2", {"source": csv_source(30)})
    assert result["total"] == 11  # m2 and m20..m29
    assert all("m2" in row["target"] for row in result["rows"])


def test_a_blank_q_is_no_filter(client: TestClient) -> None:
    assert page(client, "?q=", CSV_150)["total"] == 150


def test_only_uncategorized_keeps_the_rows_without_a_category(client: TestClient) -> None:
    result = page(client, "?only_uncategorized=true", draft_json(*BUDGET))
    assert pairs(result) == [("Budget", "Food")]
    assert result["total"] == 1


class Order(NamedTuple):
    sort: str
    pairs: list[tuple[str, str]]


@pytest.mark.parametrize(
    "case",
    [
        Order(
            "value",
            [("Salary", "Budget"), ("Budget", "Rent"), ("Freelance", "Budget"), ("Budget", "Food")],
        ),
        Order(
            "source",
            [("Budget", "Rent"), ("Budget", "Food"), ("Freelance", "Budget"), ("Salary", "Budget")],
        ),
        Order(
            "target",
            [("Salary", "Budget"), ("Freelance", "Budget"), ("Budget", "Food"), ("Budget", "Rent")],
        ),
        Order(
            "category",
            [("Budget", "Rent"), ("Salary", "Budget"), ("Freelance", "Budget"), ("Budget", "Food")],
        ),
    ],
    ids=lambda case: case.sort,
)
def test_the_sort_orders_the_rows(client: TestClient, case: Order) -> None:
    result = page(client, f"?sort={case.sort}", draft_json(*BUDGET))
    assert pairs(result) == case.pairs


@pytest.mark.parametrize("query", ["?sort=size", "?sort=", "?bogus=1", f"?q={'x' * 201}"])
def test_a_bad_filter_is_a_422(client: TestClient, query: str) -> None:
    assert client.post(URL + query, json=CSV_150).status_code == 422


def test_q_may_be_200_characters_long(client: TestClient) -> None:
    assert page(client, f"?q={'x' * 200}", CSV_150)["total"] == 0


def test_an_explicit_category_of_the_transform_is_shown(client: TestClient) -> None:
    choice = {"source": "Budget", "target": "Food", "category": "Housing"}
    body = draft_json(*BUDGET, transform={"entry_categories": [choice]})
    row = next(r for r in page(client, "", body)["rows"] if r["target"] == "Food")
    assert row["category"] == "Housing"
    assert row["overridden"] is True


def test_a_body_that_is_not_a_draft_is_a_422(client: TestClient) -> None:
    response = client.post(URL, json={"links": []})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0] == "body.source: Field required"


def test_a_failing_source_keeps_its_status(client: TestClient) -> None:
    source = {"type": "text", "origin": "file", "path": "missing.csv"}
    response = client.post(URL, json={"source": source})
    assert response.status_code == 404
    assert code(response) == "source_not_found"


def test_paging_reuses_the_graph_built_by_the_first_call(web: WebApp) -> None:
    cache = web.app.state.result_cache
    for query in ("", "?offset=100", "?q=n1&sort=target"):
        web.client.post(URL + query, json=CSV_150)
        assert cache.size == 1


def test_entries_stay_available_in_read_only_remote_mode(make_app: AppFactory) -> None:
    web = make_app([preview.router], mode="remote_read_only")
    assert web.client.post(URL, json=CSV_150).status_code == 200
