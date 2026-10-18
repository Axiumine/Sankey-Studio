# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E (settings): the connection string lives in ``credentials.json``, apart from the settings.

A server starts with one connection. The test reads both files, saves through the API, replaces
``credentials.json`` by hand while the server runs (the way an operator rotates a password) and
breaks it on purpose. ``settings.json`` never holds the password; the answers never do either.
"""

from __future__ import annotations

import json
import stat
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.storage.atomic import write_atomic
from tests.e2e.support.builders import MONGO_PASSWORD, MONGO_URI, mongo_settings
from tests.e2e.support.clients import json_of, make_client

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

SETTINGS = "/api/v1/settings"
REPLACED = "replaced-Pa55w0rd"
REPLACED_URI = f"mongodb://operator:{REPLACED}@mongo.invalid:27017/?appName=e2e"
MASKED = "mongodb://tester:***@mongo.invalid:27017/?appName=e2e"
MASKED_REPLACED = "mongodb://operator:***@mongo.invalid:27017/?appName=e2e"


@pytest.fixture
def server(make_server: ServerFactory) -> LiveServer:
    return make_server(settings=mongo_settings("main"))


def _credentials(server: LiveServer) -> dict[str, str]:
    """``{name: URI}`` as ``credentials.json`` holds it (the one file that may)."""
    doc = json.loads(server.credentials_file.read_text(encoding="utf-8"))
    return {name: item["uri"] for name, item in doc["mongo_connections"].items()}


def _put_back(api: httpx.Client, **changes: Any) -> Any:
    """``PUT /settings`` with the answer of ``GET /settings`` (masked URIs) and ``changes``."""
    current = json_of(api.get(SETTINGS))
    body = {key: value for key, value in current.items() if key != "bootstrap"}
    return json_of(api.put(SETTINGS, json={**body, **changes}))


def test_the_string_is_in_credentials_json_and_in_no_other_file_or_answer(
    server: LiveServer,
) -> None:
    assert _credentials(server) == {"main": MONGO_URI}
    assert MONGO_PASSWORD not in server.settings_file.read_text(encoding="utf-8")
    assert json.loads(server.settings_file.read_text())["mongo_connections"] == [
        {"name": "main", "default_database": "flows"}
    ]
    for path in (server.settings_file, server.credentials_file):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600  # private to the owner
    with make_client(server) as api:
        answer = api.get(SETTINGS)
    assert MONGO_PASSWORD not in answer.text
    assert json_of(answer)["mongo_connections"][0]["uri_masked"] == MASKED


def test_a_save_that_sends_no_string_keeps_the_files_apart(server: LiveServer) -> None:
    with make_client(server) as api:
        saved = _put_back(api, theme="dark")
    assert saved["settings"]["theme"] == "dark"
    assert json.loads(server.settings_file.read_text())["theme"] == "dark"
    assert MONGO_PASSWORD not in server.settings_file.read_text(encoding="utf-8")
    assert _credentials(server) == {"main": MONGO_URI}


def test_a_credentials_file_replaced_by_hand_applies_without_a_restart(
    server: LiveServer,
) -> None:
    replacement = {"version": 1, "mongo_connections": {"main": {"uri": REPLACED_URI}}}
    with make_client(server) as api:
        assert json_of(api.get(SETTINGS))["mongo_connections"][0]["uri_masked"] == MASKED
        write_atomic(server.credentials_file, json.dumps(replacement).encode())
        listed = json_of(api.get(SETTINGS))["mongo_connections"][0]
        assert listed["uri_masked"] == MASKED_REPLACED
        assert REPLACED not in json.dumps(listed)
        _put_back(api, theme="light")  # a later save keeps the replaced string, not a stale copy
    assert _credentials(server) == {"main": REPLACED_URI}
    assert REPLACED not in server.settings_file.read_text(encoding="utf-8")


def test_a_broken_credentials_file_is_a_422_that_names_the_file_and_heals_when_fixed(
    server: LiveServer,
) -> None:
    good = server.credentials_file.read_bytes()
    server.credentials_file.write_text("{broken", encoding="utf-8")
    with make_client(server) as api:
        broken = api.get(SETTINGS)
        assert broken.status_code == 422
        assert broken.json()["error"]["code"] == "settings_error"
        assert broken.json()["error"]["message"] == "credentials.json is not valid JSON"
        assert MONGO_PASSWORD not in broken.text
        write_atomic(server.credentials_file, good)
        assert json_of(api.get(SETTINGS))["mongo_connections"][0]["uri_masked"] == MASKED
