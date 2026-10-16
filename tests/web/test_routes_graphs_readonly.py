# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Remote mode without --allow-remote-writes: graph writes answer 403, everything else works."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.web.routers import compare, graphs
from tests.web.test_routes_graphs_support import (
    API,
    PLAIN,
    code,
    graph_json,
    put_graph,
    save,
)

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, Mode, WebApp

JSON_HEADERS = {"Content-Type": "application/json"}
#: Bodies FastAPI cannot decode as JSON (it would answer 422 before any dependency ran).
UNDECODABLE = ["{", "", "not json", "[1,"]
BUNDLE = {"format": "sankey-studio/graphs", "version": 2, "graphs": []}
MESSAGE = "This action is disabled in read-only remote mode (start with --allow-remote-writes)"


class Call(NamedTuple):
    method: str
    path: str
    body: dict[str, Any] | None


def writes(graph_id: str) -> list[Call]:
    return [
        Call("POST", "/graphs", graph_json("New", *PLAIN)),
        Call("PUT", f"/graphs/{graph_id}", {**graph_json("New", *PLAIN), "revision": 1}),
        Call("DELETE", f"/graphs/{graph_id}", None),
        Call("POST", f"/graphs/{graph_id}/duplicate", None),
        Call("POST", "/graphs/import", BUNDLE),
    ]


def reads(graph_id: str) -> list[Call]:
    return [
        Call("GET", "/graphs", None),
        Call("GET", f"/graphs/{graph_id}", None),
        Call("GET", f"/graphs/{graph_id}/render", None),
        Call("GET", f"/graphs/export?ids={graph_id}", None),
        Call("GET", "/tags", None),
        Call("GET", f"/compare/render?ids={graph_id}", None),
    ]


@pytest.fixture
def remote(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router, compare.router], mode="remote_read_only")


def test_every_graph_write_is_a_403_read_only_mode(remote: WebApp) -> None:
    graph_id = put_graph(remote, 1, "Seed")
    for call in writes(graph_id):
        response = remote.client.request(call.method, API + call.path, json=call.body)
        assert response.status_code == 403, call
        assert code(response) == "read_only_mode", call
        assert response.json()["error"]["message"] == MESSAGE, call


def test_a_refused_write_changes_nothing(remote: WebApp) -> None:
    graph_id = put_graph(remote, 1, "Seed")
    before = remote.services.graphs().get(graph_id)
    for call in writes(graph_id):
        remote.client.request(call.method, API + call.path, json=call.body)
    assert remote.services.graphs().get(graph_id) == before
    assert remote.client.get(f"{API}/graphs").json()["total"] == 1


def test_the_reads_stay_available(remote: WebApp) -> None:
    graph_id = put_graph(remote, 1, "Seed")
    for call in reads(graph_id):
        assert remote.client.get(API + call.path).status_code == 200, call


def test_with_remote_writes_the_graph_writes_work(make_app: AppFactory) -> None:
    web = make_app([graphs.router], mode="remote_writes")
    created = web.client.post(f"{API}/graphs", json=graph_json("New", *PLAIN))
    assert created.status_code == 201
    graph_id = created.json()["id"]
    assert web.client.post(f"{API}/graphs/{graph_id}/duplicate").status_code == 201
    assert web.client.delete(f"{API}/graphs/{graph_id}").status_code == 204


def test_a_local_app_is_never_read_only(make_app: AppFactory) -> None:
    web = make_app([graphs.router])
    stored = save(web, "Seed", *PLAIN)
    assert web.client.delete(f"{API}/graphs/{stored.id}").status_code == 204


def bodied(graph_id: str) -> list[Call]:
    """The writes that take a request body (the others have nothing to decode)."""
    return [call for call in writes(graph_id) if call.body is not None]


@pytest.mark.parametrize("raw", UNDECODABLE)
def test_an_undecodable_body_is_still_a_403_in_read_only_mode(remote: WebApp, raw: str) -> None:
    graph_id = put_graph(remote, 1, "Seed")
    before = remote.services.graphs().get(graph_id)
    calls = bodied(graph_id)
    assert [call.path for call in calls] == ["/graphs", f"/graphs/{graph_id}", "/graphs/import"]
    for call in calls:
        response = remote.client.request(
            call.method, API + call.path, content=raw, headers=JSON_HEADERS
        )
        assert response.status_code == 403, call
        assert code(response) == "read_only_mode", call
        assert response.json()["error"]["message"] == MESSAGE, call
    assert remote.services.graphs().get(graph_id) == before
    assert remote.client.get(f"{API}/graphs").json()["total"] == 1


@pytest.mark.parametrize("mode", ["local", "remote_writes"])
def test_where_writes_are_allowed_an_undecodable_body_is_a_422(
    make_app: AppFactory, mode: Mode
) -> None:
    web = make_app([graphs.router], mode=mode)
    graph_id = put_graph(web, 1, "Seed")
    for call in bodied(graph_id):
        response = web.client.request(
            call.method, API + call.path, content="{", headers=JSON_HEADERS
        )
        assert response.status_code == 422, call
        assert code(response) == "validation_error", call
    assert web.client.get(f"{API}/graphs").json()["total"] == 1
