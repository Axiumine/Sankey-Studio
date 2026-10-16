# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""POST/GET/PUT/DELETE /api/v1/graphs: create, read, optimistic update and delete."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.web.routers import graphs
from tests.web.test_routes_graphs_support import (
    API,
    BUDGET,
    MALFORMED_IDS,
    PLAIN,
    UNKNOWN_ID,
    code,
    graph_json,
    save,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from tests.web.conftest import AppFactory, WebApp

URL = f"{API}/graphs"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


def update_body(revision: int, name: str = "Household") -> dict[str, Any]:
    return {**graph_json(name, *BUDGET), "revision": revision}


def test_a_created_graph_is_201_with_its_stored_definition(client: TestClient) -> None:
    body = graph_json("Household", *BUDGET, description="Monthly", tags=["home", " home ", "q1"])
    response = client.post(URL, json=body)
    assert response.status_code == 201
    created = response.json()
    assert re.fullmatch(r"[0-9a-f]{32}", created["id"])
    assert (created["name"], created["description"]) == ("Household", "Monthly")
    assert created["tags"] == ["home", "q1"]
    assert (created["revision"], created["schema_version"]) == (1, 1)
    assert created["created_at"] == created["updated_at"]
    assert created["source"]["type"] == "manual"
    assert len(created["source"]["links"]) == 4
    assert client.get(f"{URL}/{created['id']}").json() == created


def test_every_create_makes_a_new_graph(client: TestClient) -> None:
    ids = {client.post(URL, json=graph_json("Same", *PLAIN)).json()["id"] for _ in range(3)}
    assert len(ids) == 3
    assert client.get(URL).json()["total"] == 3


class Invalid(NamedTuple):
    label: str
    body: dict[str, Any]
    detail: str


INVALID = [
    Invalid("null name", graph_json("x", *PLAIN) | {"name": None}, "body.name: Input should be"),
    Invalid("empty name", graph_json("", *PLAIN), "body.name: String should have at least 1"),
    Invalid("long name", graph_json("n" * 201, *PLAIN), "body.name: String should have at most"),
    Invalid("id", graph_json("x", *PLAIN, id="a" * 32), "body.id: Extra inputs are not permitted"),
    Invalid(
        "revision",
        graph_json("x", *PLAIN, revision=3),
        "body.revision: Extra inputs are not permitted",
    ),
    Invalid(
        "tags", graph_json("x", *PLAIN, tags=["t"] * 21), "body.tags: List should have at most"
    ),
    Invalid("no source", {"name": "x"}, "body.source: Field required"),
]


@pytest.mark.parametrize("case", INVALID, ids=lambda case: case.label)
def test_an_invalid_body_is_a_422_that_names_the_field(client: TestClient, case: Invalid) -> None:
    response = client.post(URL, json=case.body)
    assert response.status_code == 422
    assert code(response) == "validation_error"
    assert response.json()["error"]["details"][0].startswith(case.detail)
    assert client.get(URL).json()["total"] == 0


def test_a_name_of_200_characters_is_accepted(client: TestClient) -> None:
    response = client.post(URL, json=graph_json("n" * 200, *PLAIN))
    assert response.status_code == 201
    assert response.json()["name"] == "n" * 200


@pytest.mark.parametrize("graph_id", [*MALFORMED_IDS, UNKNOWN_ID])
def test_a_graph_that_does_not_exist_is_a_404(client: TestClient, graph_id: str) -> None:
    for response in (
        client.get(f"{URL}/{graph_id}"),
        client.put(f"{URL}/{graph_id}", json=update_body(1)),
        client.delete(f"{URL}/{graph_id}"),
        client.post(f"{URL}/{graph_id}/duplicate"),
        client.get(f"{URL}/{graph_id}/render"),
    ):
        assert response.status_code == 404
        assert code(response) == "not_found"
        assert response.json()["error"]["message"] == "Graph not found"


def test_an_update_replaces_the_graph_and_bumps_the_revision(web: WebApp) -> None:
    stored = save(web, "Household", *PLAIN, tags=["old"])
    body = {**update_body(1, "Renamed"), "description": "New text", "tags": ["new"]}
    response = web.client.put(f"{URL}/{stored.id}", json=body)
    assert response.status_code == 200
    updated = response.json()
    assert (updated["id"], updated["revision"]) == (stored.id, 2)
    assert (updated["name"], updated["description"], updated["tags"]) == (
        "Renamed",
        "New text",
        ["new"],
    )
    assert len(updated["source"]["links"]) == 4
    assert datetime.fromisoformat(updated["created_at"]) == stored.created_at
    assert datetime.fromisoformat(updated["updated_at"]) >= stored.updated_at
    assert web.client.get(f"{URL}/{stored.id}").json() == updated


def test_a_stale_revision_is_a_409_with_the_current_revision_and_time(web: WebApp) -> None:
    stored = save(web, "Household", *PLAIN)
    assert web.client.put(f"{URL}/{stored.id}", json=update_body(1)).status_code == 200
    current = web.services.graphs().get(stored.id)
    response = web.client.put(f"{URL}/{stored.id}", json=update_body(1, "Lost edit"))
    assert response.status_code == 409
    assert code(response) == "conflict"
    assert response.json()["error"]["details"] == [
        "revision=2",
        f"updated_at={current.updated_at.isoformat()}",
    ]
    assert web.services.graphs().get(stored.id).name == "Household"


def test_a_revision_from_the_future_is_a_409_too(web: WebApp) -> None:
    stored = save(web, "Household", *PLAIN)
    response = web.client.put(f"{URL}/{stored.id}", json=update_body(2))
    assert response.status_code == 409
    assert response.json()["error"]["details"][0] == "revision=1"


@pytest.mark.parametrize(
    "patch", [{"revision": 0}, {"revision": "one"}, {"id": "a" * 32}, {"created_at": "2020-01-01"}]
)
def test_a_bad_update_body_is_a_422(web: WebApp, patch: dict[str, Any]) -> None:
    stored = save(web, "Household", *PLAIN)
    response = web.client.put(f"{URL}/{stored.id}", json={**update_body(1), **patch})
    assert response.status_code == 422
    assert web.services.graphs().get(stored.id).revision == 1


def test_an_update_without_a_revision_is_a_422(web: WebApp) -> None:
    stored = save(web, "Household", *PLAIN)
    response = web.client.put(f"{URL}/{stored.id}", json=graph_json("x", *PLAIN))
    assert response.status_code == 422
    assert response.json()["error"]["details"] == ["body.revision: Field required"]


def test_a_delete_is_204_without_a_body(web: WebApp) -> None:
    stored = save(web, "Household", *PLAIN)
    response = web.client.delete(f"{URL}/{stored.id}")
    assert response.status_code == 204
    assert response.content == b""
    assert web.client.get(f"{URL}/{stored.id}").status_code == 404
    assert web.client.delete(f"{URL}/{stored.id}").status_code == 404


def test_a_delete_leaves_the_other_graphs(web: WebApp) -> None:
    keep, drop = save(web, "Keep", *PLAIN), save(web, "Drop", *PLAIN)
    web.client.delete(f"{URL}/{drop.id}")
    assert [item["id"] for item in web.client.get(URL).json()["items"]] == [keep.id]


def test_the_static_paths_are_not_read_as_ids(client: TestClient) -> None:
    response = client.get(f"{URL}/export")
    assert response.status_code == 422  # the export route answered: it wants ?ids=
    assert response.json()["error"]["details"] == ["query.ids: Field required"]
    response = client.post(f"{URL}/import", json=[])
    assert response.status_code == 422
    assert code(response) == "bundle_error"
