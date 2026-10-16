# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md A.8, part 4: the remote server (``--allow-remote``) is read-only unless told otherwise.

A read-only remote server refuses every route that persists with 403 ``read_only_mode`` - also
for a body that would be invalid (the refusal comes before the body is read) - and leaves graphs,
settings and sources untouched. Everything that only reads or computes keeps working, the pages
say ``writes_allowed: false`` and the settings answer hides the Mongo hosts and user names.
``--allow-remote-writes`` turns the writes back on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import GraphCreate
from tests.e2e.support.builders import (
    BUDGET_CATEGORISED,
    graph_create,
    graph_draft,
    mongo_settings,
    seed_flows,
)
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.http_b_security import (
    API,
    WRITE_ROUTES,
    Route,
    assert_security_headers,
    boot_data,
    send,
    snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

HTML = {"Accept": "text/html"}
ROUTES = [pytest.param(route, id=route.label) for route in WRITE_ROUTES]
OPTIONS: dict[str, Any] = {"settings": mongo_settings("main"), "seed_mongo": seed_flows}


def seeded(make_server: ServerFactory, **options: Any) -> LiveServer:
    """A remote server holding one graph (saved straight into its store) and a Mongo connection."""
    server = make_server(remote_mode=True, **{**OPTIONS, **options})
    draft = graph_create("Remote graph", graph_draft(BUDGET_CATEGORISED.csv))
    server.services.graphs().create(GraphCreate.model_validate(draft))
    return server


@pytest.fixture(scope="module")
def read_only_server(module_make_server: ServerFactory) -> LiveServer:
    """One read-only remote server for the module: nothing here may change it."""
    return seeded(module_make_server)


@pytest.fixture
def read_only(read_only_server: LiveServer) -> Iterator[httpx.Client]:
    with make_client(read_only_server) as client:
        yield client


def only_graph(client: httpx.Client) -> str:
    return str(json_of(client.get(f"{API}/graphs"))["items"][0]["id"])


# ------------------------------------------------------------------------------ writes refused


@pytest.mark.parametrize("route", ROUTES)
def test_every_route_that_persists_is_a_403_in_read_only_mode(
    read_only_server: LiveServer, route: Route
) -> None:
    with make_client(read_only_server) as client:
        graph_id = only_graph(client)
        before = snapshot(client, read_only_server)
        response = send(client, route, graph_id)
        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "read_only_mode"
        assert "read-only" in error["message"]
        assert_security_headers(response, no_store=True)
        assert snapshot(client, read_only_server) == before


@pytest.mark.parametrize(
    ("method", "path", "content"),
    [
        ("PUT", f"{API}/settings", b'{"max_links": 1, "bogus": 1}'),
        ("PUT", f"{API}/settings", b"\xff\xfe{"),
        ("POST", f"{API}/graphs", b"not json at all"),
        ("POST", f"{API}/settings/storage/test", b"{}"),
    ],
)
def test_the_refusal_comes_before_the_body_is_read(
    read_only: httpx.Client, method: str, path: str, content: bytes
) -> None:
    headers = {"Content-Type": "application/json"}
    response = read_only.request(method, path, content=content, headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (403, "read_only_mode")


def test_an_upload_is_refused_before_a_byte_of_it_is_read(make_server: ServerFactory) -> None:
    server = seeded(make_server, settings={**OPTIONS["settings"], "max_upload_mb": 1})
    big = {"file": ("big.csv", b"a,b,1\n" * 500_000, "text/csv")}  # 3 MB: over the cap, not a 413
    with make_client(server) as client:
        response = client.post(f"{API}/sources/files", files=big)
    assert (response.status_code, response.json()["error"]["code"]) == (403, "read_only_mode")
    assert not list(server.sources_dir.glob("*"))


# ------------------------------------------------------------------------------ reads allowed


def test_reading_and_drawing_keep_working(read_only: httpx.Client) -> None:
    graph_id = only_graph(read_only)
    assert read_only.get(f"{API}/graphs/{graph_id}").status_code == 200
    assert read_only.get(f"{API}/tags").status_code == 200
    rendered = json_of(read_only.get(f"{API}/graphs/{graph_id}/render"))
    assert rendered["stats"]["links"] == BUDGET_CATEGORISED.links
    assert json_of(read_only.post(f"{API}/preview", json=graph_draft()))["stats"]["nodes"] == 10
    assert json_of(read_only.post(f"{API}/entries", json=graph_draft()))["total"] == 9
    assert json_of(read_only.post(f"{API}/sources/detect", json={"sample": "a,b,1"})) == {
        "format": "csv"
    }
    assert read_only.get(f"{API}/compare/render", params={"ids": graph_id}).status_code == 200
    for fmt in ("csv", "json", "html"):
        export = read_only.get(f"{API}/graphs/{graph_id}/export", params={"format": fmt})
        assert export.status_code == 200
    assert (
        read_only.post(f"{API}/export", params={"format": "csv"}, json=graph_draft()).status_code
        == 200
    )
    bundle = read_only.get(f"{API}/graphs/export", params={"ids": graph_id})
    assert json_of(bundle)["graphs"][0]["id"] == graph_id


def test_the_mongo_inspect_routes_stay_available(read_only: httpx.Client) -> None:
    assert json_of(read_only.get(f"{API}/mongo/main/databases")) == ["flows"]
    names = read_only.get(f"{API}/mongo/main/collections", params={"database": "flows"})
    assert json_of(names) == ["transfers"]


def test_the_pages_and_the_settings_say_so(read_only: httpx.Client) -> None:
    for path in ("/", "/graphs/new", "/settings"):
        data = boot_data(read_only.get(path, headers=HTML).text)
        assert (data["remote_mode"], data["writes_allowed"]) == (True, False), path
    settings = json_of(read_only.get(f"{API}/settings"))
    assert settings["bootstrap"]["remote_mode"] is True
    assert settings["bootstrap"]["writes_allowed"] is False
    (connection,) = settings["mongo_connections"]
    assert connection["uri_masked"] == "mongodb://***"  # no host, no user name
    assert connection["has_secret"] is True
    assert "mongo.invalid" not in str(settings)
    assert "tester" not in str(settings)


# ------------------------------------------------------------------------------ writes switched on


def test_remote_writes_turn_the_writes_back_on_but_keep_the_remote_flags(
    make_server: ServerFactory,
) -> None:
    server = make_server(remote_mode=True, allow_remote_writes=True, **OPTIONS)
    with make_client(server) as client:
        created = json_of(client.post(f"{API}/graphs", json=graph_create("Writable")), 201)
        assert client.delete(f"{API}/graphs/{created['id']}").status_code == 204
        saved = json_of(client.get(f"{API}/settings"))
        saved.pop("bootstrap")
        assert client.put(f"{API}/settings", json={**saved, "max_links": 150}).status_code == 200
        data = boot_data(client.get("/", headers=HTML).text)
        assert (data["remote_mode"], data["writes_allowed"]) == (True, True)
        assert json_of(client.get(f"{API}/settings"))["bootstrap"]["writes_allowed"] is True
