# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E A.1 (settings): Mongo connections, the "keep the secret" semantics and the probes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import MONGO_PASSWORD, MONGO_URI
from tests.e2e.support.clients import json_of
from tests.e2e.support.http_a_settings import (
    connection,
    get_settings,
    put_settings,
    reset_settings,
    stored_uris,
)

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer

MASKED = "mongodb://tester:***@mongo.invalid:27017/?appName=e2e"
PROBE = "/api/v1/settings/mongo/{name}/test"
STORAGE_PROBE = "/api/v1/settings/storage/test"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module; the fixture below resets its settings before every test."""
    return module_server


@pytest.fixture(autouse=True)
def factory_settings(live_server: LiveServer, api: httpx.Client) -> None:
    reset_settings(api, live_server)


def with_connections(api: httpx.Client, *items: dict[str, Any]) -> dict[str, Any]:
    """A PUT body: the stored settings (as a GET answer) with these connections."""
    return {**get_settings(api), "mongo_connections": list(items)}


def said(error: dict[str, Any]) -> str:
    """Everything an error envelope tells the user: the message and the detail lines."""
    return " ".join([error["message"], *error["details"]])


def test_a_new_connection_is_listed_masked_and_its_secret_is_stored(
    live_server: LiveServer, api: httpx.Client
) -> None:
    saved = put_settings(api, with_connections(api, connection()))
    [listed] = saved["settings"]["mongo_connections"]
    assert listed == {
        "name": "main",
        "uri_masked": MASKED,
        "has_secret": True,
        "default_database": "flows",
    }
    assert get_settings(api)["mongo_connections"] == [listed]
    assert stored_uris(live_server) == {"main": MONGO_URI}  # the secret lives on disk only


@pytest.mark.parametrize("keep", [None, "", MASKED], ids=["omitted", "empty", "masked-echo"])
def test_a_connection_without_a_new_uri_keeps_its_stored_secret(
    live_server: LiveServer, api: httpx.Client, keep: str | None
) -> None:
    put_settings(api, with_connections(api, connection()))
    again = connection(uri=keep, database="other")
    if keep is None:
        again["uri"] = None  # an explicit null is the same as leaving it out
    saved = put_settings(api, with_connections(api, again))
    assert saved["settings"]["mongo_connections"][0]["has_secret"] is True
    assert saved["settings"]["mongo_connections"][0]["default_database"] == "other"
    assert stored_uris(live_server) == {"main": MONGO_URI}
    assert json_of(api.post(PROBE.format(name="main")))["ok"] is True


def test_a_new_uri_replaces_the_secret(live_server: LiveServer, api: httpx.Client) -> None:
    put_settings(api, with_connections(api, connection()))
    rotated = "mongodb://tester:rotated-pw@mongo.invalid:27017/?appName=e2e"
    saved = put_settings(api, with_connections(api, connection(uri=rotated)))
    assert saved["settings"]["mongo_connections"][0]["uri_masked"] == MASKED
    assert stored_uris(live_server) == {"main": rotated}
    assert "rotated-pw" not in api.get("/api/v1/settings").text


def test_a_renamed_connection_keeps_its_secret_and_a_retry_is_harmless(
    live_server: LiveServer, api: httpx.Client
) -> None:
    put_settings(api, with_connections(api, connection()))
    renamed = {**connection("renamed", uri=None), "previous_name": "main"}
    for _ in range(2):  # the second request is a retry of the first: still 200, same secret
        saved = put_settings(api, with_connections(api, renamed))
        assert [c["name"] for c in saved["settings"]["mongo_connections"]] == ["renamed"]
        assert stored_uris(live_server) == {"renamed": MONGO_URI}
    assert api.post(PROBE.format(name="main")).status_code == 404
    assert json_of(api.post(PROBE.format(name="renamed")))["ok"] is True


def test_a_rename_between_two_unknown_names_is_refused(api: httpx.Client) -> None:
    ghost = {**connection("new", uri=None), "previous_name": "gone"}
    error = json_of(api.put("/api/v1/settings", json=with_connections(api, ghost)), 422)["error"]
    assert error["code"] == "settings_error"
    assert get_settings(api)["mongo_connections"] == []


def test_a_new_connection_without_any_uri_is_refused_and_nothing_is_stored(
    live_server: LiveServer, api: httpx.Client
) -> None:
    refused = api.put("/api/v1/settings", json=with_connections(api, connection(uri=None)))
    error = json_of(refused, 422)["error"]
    assert error["code"] == "settings_error"
    assert "'main' needs a connection string" in said(error)
    assert get_settings(api)["mongo_connections"] == []
    assert stored_uris(live_server) == {}


@pytest.mark.parametrize(
    "uri",
    ["ftp://tester:hunter2@mongo.invalid/", "tester:hunter2@mongo.invalid"],
    ids=["ftp", "bare"],
)
def test_a_bad_uri_is_refused_without_echoing_it(api: httpx.Client, uri: str) -> None:
    refused = api.put("/api/v1/settings", json=with_connections(api, connection(uri=uri)))
    error = json_of(refused, 422)["error"]
    assert error["code"] == "settings_error"
    assert MONGO_PASSWORD not in refused.text
    assert "mongo.invalid" not in refused.text
    assert get_settings(api)["mongo_connections"] == []


def test_connection_names_must_be_valid_and_unique(api: httpx.Client) -> None:
    bad_name = with_connections(api, connection("not a name"))
    assert json_of(api.put("/api/v1/settings", json=bad_name), 422)["error"]["details"]
    twice = with_connections(api, connection("same"), connection("same"))
    assert json_of(api.put("/api/v1/settings", json=twice), 422)["error"]["code"] in {
        "settings_error",
        "validation_error",
    }
    too_many = with_connections(api, *(connection(f"c{i}") for i in range(21)))
    assert api.put("/api/v1/settings", json=too_many).status_code == 422
    assert get_settings(api)["mongo_connections"] == []


def test_the_connection_test_reports_a_latency_and_names_unknown_ones(
    api: httpx.Client,
) -> None:
    put_settings(api, with_connections(api, connection()))
    probe = json_of(api.post(PROBE.format(name="main")))
    assert probe["ok"] is True
    assert isinstance(probe["latency_ms"], float)
    assert probe["latency_ms"] >= 0
    missing = json_of(api.post(PROBE.format(name="nope")), 404)["error"]
    assert (missing["code"], missing["message"]) == (
        "source_not_found",
        "Unknown MongoDB connection 'nope'",
    )


def test_an_unreachable_server_is_a_503_that_names_the_connection_only(
    live_server: LiveServer, api: httpx.Client
) -> None:
    put_settings(api, with_connections(api, connection()))
    live_server.mongo.unreachable = True
    down = api.post(PROBE.format(name="main"))
    assert json_of(down, 503)["error"]["code"] == "storage_error"
    assert "main" in down.text
    assert MONGO_PASSWORD not in down.text
    assert "mongo.invalid" not in down.text
    live_server.mongo.unreachable = False
    assert api.post(PROBE.format(name="main")).status_code == 200


def test_deleting_a_connection_removes_it_and_its_secret(
    live_server: LiveServer, api: httpx.Client
) -> None:
    put_settings(api, with_connections(api, connection("keep"), connection("drop")))
    put_settings(api, with_connections(api, connection("keep", uri=None)))
    assert [c["name"] for c in get_settings(api)["mongo_connections"]] == ["keep"]
    assert stored_uris(live_server) == {"keep": MONGO_URI}
    assert api.post(PROBE.format(name="drop")).status_code == 404


def test_the_storage_probe_checks_a_candidate_and_saves_nothing(
    live_server: LiveServer, api: httpx.Client
) -> None:
    put_settings(api, with_connections(api, connection()))
    before = get_settings(api)
    on_file = {**before, "storage_backend": "file"}
    on_mongo = {**before, "storage_backend": "mongo", "storage_connection": "main"}
    assert json_of(api.post(STORAGE_PROBE, json=on_file)) == {"ok": True}
    assert json_of(api.post(STORAGE_PROBE, json=on_mongo)) == {"ok": True}
    live_server.mongo.unreachable = True
    assert json_of(api.post(STORAGE_PROBE, json=on_mongo), 503)["error"]["code"] == "storage_error"
    live_server.mongo.unreachable = False
    assert get_settings(api) == before  # a probe never switches the backend


def test_the_mongo_backend_needs_a_configured_connection(api: httpx.Client) -> None:
    body = {**get_settings(api), "storage_backend": "mongo", "storage_connection": None}
    for call in (api.put("/api/v1/settings", json=body), api.post(STORAGE_PROBE, json=body)):
        error = json_of(call, 422)["error"]
        assert error["code"] == "settings_error"
        assert "storage_connection" in said(error)
    assert get_settings(api)["storage_backend"] == "file"
