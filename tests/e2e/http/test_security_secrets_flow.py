# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md A.8, part 5: a stored Mongo password is in no response, no log line and no graph file.

One server holds a connection whose URI has a password. The test drives everything that touches
it: the settings answer, saves that keep or rotate the secret, probes that work and probes that
fail, the Mongo routes, a saved Mongo graph and its exports, the pages, and the refusals. Then it
scans every response the client saw (status line, headers, body), every log record of the server
and everything printed. ``settings.json`` is the one place the secret is allowed to live, and it
is private to the owner.
"""

from __future__ import annotations

import logging
import stat
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import (
    FLOWS_COLLECTION,
    FLOWS_DATABASE,
    MONGO_PASSWORD,
    MONGO_URI,
    mongo_settings,
    seed_flows,
)
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.http_b_tape import attach

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

API = "/api/v1"
ROTATED = "rotated-Pa55w0rd"
ROTATED_URI = f"mongodb://tester:{ROTATED}@mongo.invalid:27017/?appName=e2e"
HTML = {"Accept": "text/html"}
SOURCE = {
    "type": "mongo",
    "connection": "main",
    "database": FLOWS_DATABASE,
    "collection": FLOWS_COLLECTION,
    "source_field": "from",
    "target_field": "to",
    "value_field": "amount",
}


def settings_body(client_get: dict[str, object], **changes: object) -> dict[str, object]:
    """The ``GET /settings`` answer as a ``PUT`` body, with ``changes`` applied."""
    body = {key: value for key, value in client_get.items() if key != "bootstrap"}
    return {**body, **changes}


@pytest.fixture
def server(make_server: ServerFactory) -> LiveServer:
    return make_server(settings=mongo_settings("main"), seed_mongo=seed_flows)


def test_the_password_never_leaves_the_settings_file(
    server: LiveServer, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    with make_client(server) as api:
        tape = attach(api)
        drive_everything(server, api)
    assert len(tape) > 20  # the scan looked at a real session
    tape.assert_clean([MONGO_PASSWORD, ROTATED, MONGO_URI, ROTATED_URI])
    logged = caplog.text
    printed = capfd.readouterr()
    for secret in (MONGO_PASSWORD, ROTATED):
        assert secret not in logged
        assert secret not in printed.out + printed.err
    assert "mongo.invalid:27017" not in logged  # not even the host of the URI
    assert "unreachable" in logged  # the failed probes were logged, with the name only


def drive_everything(server: LiveServer, api: httpx.Client) -> None:
    """Touch every route and page that could carry the connection."""
    stored = json_of(api.get(f"{API}/settings"))
    assert stored["mongo_connections"][0]["uri_masked"].startswith("mongodb://tester:***@")
    assert "uri" not in stored["mongo_connections"][0]
    keep = settings_body(stored)  # sends the masked URI back: the secret is kept
    assert api.put(f"{API}/settings", json=keep).status_code == 200
    assert json_of(api.post(f"{API}/settings/mongo/main/test"))["ok"] is True
    mongo_routes(api)
    graph = json_of(api.post(f"{API}/graphs", json={"name": "Mongo", "source": SOURCE}), 201)
    for path in (f"/graphs/{graph['id']}/render", f"/graphs/{graph['id']}/export", "/graphs"):
        assert (
            api.get(
                f"{API}{path}", params={"format": "json"} if "export" in path else {}
            ).status_code
            == 200
        )
    assert api.get(f"{API}/graphs/export", params={"ids": graph["id"]}).status_code == 200
    for page in ("/", "/settings", "/graphs/new", f"/graphs/{graph['id']}"):
        assert api.get(page, headers=HTML).status_code == 200
    rotate_and_fail(server, api, stored)
    check_stored_secret(server, api)


def mongo_routes(api: httpx.Client) -> None:
    assert json_of(api.get(f"{API}/mongo/main/databases")) == [FLOWS_DATABASE]
    listing = api.get(f"{API}/mongo/main/collections", params={"database": FLOWS_DATABASE})
    assert json_of(listing) == [FLOWS_COLLECTION]
    sample: dict[str, str | int] = {
        "database": FLOWS_DATABASE,
        "collection": FLOWS_COLLECTION,
        "n": 2,
    }
    assert api.get(f"{API}/mongo/main/sample", params=sample).status_code == 200
    assert api.post(f"{API}/preview", json={"source": SOURCE}).status_code == 200


def rotate_and_fail(server: LiveServer, api: httpx.Client, stored: dict[str, object]) -> None:
    rotated = [{"name": "main", "uri": ROTATED_URI, "default_database": FLOWS_DATABASE}]
    assert (
        api.put(
            f"{API}/settings", json=settings_body(stored, mongo_connections=rotated)
        ).status_code
        == 200
    )
    refused = api.put(
        f"{API}/settings",
        json=settings_body(
            stored, mongo_connections=[{"name": "x", "uri": f"{MONGO_URI}&tlsCAFile=/x"}]
        ),
    )
    assert refused.status_code == 422
    server.mongo.unreachable = True
    for response in (
        api.post(f"{API}/settings/mongo/main/test"),
        api.get(f"{API}/mongo/main/databases"),
        api.post(f"{API}/preview", json={"source": SOURCE}),
    ):
        assert response.status_code in {422, 503}
        assert "unreachable" in response.json()["error"]["message"]
    server.mongo.unreachable = False


def check_stored_secret(server: LiveServer, api: httpx.Client) -> None:
    settings_file = server.settings_file
    assert ROTATED in settings_file.read_text()  # the one place it lives
    assert stat.S_IMODE(settings_file.stat().st_mode) == 0o600  # private to the owner
    for path in server.graphs_dir.glob("*.json"):
        assert ROTATED not in path.read_text()
        assert MONGO_PASSWORD not in path.read_text()
    assert ROTATED not in api.get(f"{API}/settings").text


def test_a_second_client_reading_the_settings_cannot_see_the_secret_either(
    server: LiveServer,
) -> None:
    with make_client(server) as api, make_client(server, origin=None) as curl:
        for client in (api, curl):
            settings = client.get(f"{API}/settings")
            assert MONGO_PASSWORD not in settings.text
            assert json_of(settings)["mongo_connections"][0]["has_secret"] is True
