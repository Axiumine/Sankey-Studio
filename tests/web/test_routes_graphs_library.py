# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""GET /api/v1/graphs (search, paging) and GET /api/v1/tags."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.web.routers import graphs
from tests.web.test_routes_graphs_support import API, code, put_graph

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from tests.web.conftest import AppFactory, WebApp

URL = f"{API}/graphs"
#: Names in storage order; ``put_graph`` numbers 1..5 are minutes 1..5 (the list is newest first).
LIBRARY = [
    ("Alpha budget", ["finance"]),
    ("Beta flows", ["ops", "finance"]),
    ("Gamma", []),
    ("Delta Budget", ["ops"]),
    ("Epsilon", ["Finance"]),
]


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


@pytest.fixture
def library(web: WebApp) -> list[str]:
    """The ids of the five graphs, oldest first."""
    return [put_graph(web, n, name, tags) for n, (name, tags) in enumerate(LIBRARY, start=1)]


def names(client: TestClient, query: str) -> list[str]:
    response = client.get(URL + query)
    assert response.status_code == 200
    return [item["name"] for item in response.json()["items"]]


def test_an_empty_library_is_an_empty_page(client: TestClient) -> None:
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 200, "offset": 0}


@pytest.mark.usefixtures("library")
def test_the_newest_graph_comes_first(client: TestClient) -> None:
    page = client.get(URL).json()
    assert [item["name"] for item in page["items"]] == [name for name, _ in reversed(LIBRARY)]
    assert page["total"] == 5


def test_a_summary_has_the_listing_fields_only(client: TestClient, library: list[str]) -> None:
    item = client.get(URL).json()["items"][-1]
    assert item == {
        "id": library[0],
        "name": "Alpha budget",
        "description": "",
        "tags": ["finance"],
        "source_type": "manual",
        "revision": 1,
        "updated_at": "2026-01-01T12:01:00Z",
        "folder_id": None,
    }


@pytest.mark.usefixtures("library")
def test_limit_and_offset_page_through_the_list(client: TestClient) -> None:
    page = client.get(URL + "?limit=2&offset=1").json()
    assert [item["name"] for item in page["items"]] == ["Delta Budget", "Gamma"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 1)
    assert names(client, "?limit=2&offset=4") == ["Alpha budget"]
    assert names(client, "?offset=5") == []


class Search(NamedTuple):
    query: str
    found: list[str]
    total: int


@pytest.mark.usefixtures("library")
@pytest.mark.parametrize(
    "case",
    [
        Search("?q=budget", ["Delta Budget", "Alpha budget"], 2),
        Search("?q=BUDGET", ["Delta Budget", "Alpha budget"], 2),
        Search("?q=flows", ["Beta flows"], 1),
        Search("?tag=ops", ["Delta Budget", "Beta flows"], 2),
        Search("?tag=fin", [], 0),
        Search("?tag=finance", ["Beta flows", "Alpha budget"], 2),
        Search("?q=budget&tag=ops", ["Delta Budget"], 1),
        Search("?q=&tag=", ["Epsilon", "Delta Budget", "Gamma", "Beta flows", "Alpha budget"], 5),
        Search("?q=nothing", [], 0),
        Search("?q=budget&limit=1", ["Delta Budget"], 2),
    ],
    ids=lambda case: case.query,
)
def test_search_filters_the_page_and_its_total(client: TestClient, case: Search) -> None:
    page = client.get(URL + case.query).json()
    assert [item["name"] for item in page["items"]] == case.found
    assert page["total"] == case.total


class Bound(NamedTuple):
    query: str
    status: int


@pytest.mark.parametrize(
    "case",
    [
        Bound("?limit=200", 200),
        Bound("?limit=201", 422),
        Bound("?limit=1", 200),
        Bound("?limit=0", 422),
        Bound("?offset=0", 200),
        Bound("?offset=-1", 422),
        Bound(f"?q={'q' * 200}", 200),
        Bound(f"?q={'q' * 201}", 422),
        Bound(f"?tag={'t' * 40}", 200),
        Bound(f"?tag={'t' * 41}", 422),
        Bound("?sort=name", 422),
        Bound("?limit=ten", 422),
    ],
    ids=lambda case: case.query[:24],
)
def test_the_list_query_bounds(client: TestClient, case: Bound) -> None:
    response = client.get(URL + case.query)
    assert response.status_code == case.status
    if case.status == 422:
        assert code(response) == "validation_error"


def test_tags_are_listed_sorted_and_distinct(client: TestClient, library: list[str]) -> None:
    assert len(library) == 5
    response = client.get(f"{API}/tags")
    assert response.status_code == 200
    assert response.json() == ["Finance", "finance", "ops"]


def test_no_tags_is_an_empty_list(client: TestClient) -> None:
    assert client.get(f"{API}/tags").json() == []
