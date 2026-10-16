# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``GET`` and ``PUT /api/v1/settings``: the wire form, secret handling and validation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.web.routers.settings import router
from tests.conftest import TEST_URI
from tests.web.test_routes_settings_support import (
    BASE,
    MASKED_TEST_URI,
    PASSWORD,
    error_of,
    key_names,
    put_body,
    stored_names,
    stored_uri,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from sankey_studio.models import AppSettings
    from tests.web.conftest import AppFactory, WebApp

NEW_URI = "mongodb://new-user:n3w-pass@elsewhere.invalid:27018/"


@pytest.fixture
def web(make_app: AppFactory, app_settings: AppSettings) -> WebApp:
    """An app serving only the settings router, with the ``test`` connection stored."""
    return make_app([router], settings=app_settings)


def connection(**fields: Any) -> dict[str, Any]:
    return {"name": "test", "default_database": "flows", **fields}


def put(client: TestClient, connections: list[dict[str, Any]], **fields: Any) -> Any:
    return client.put(BASE, json={"mongo_connections": connections, **fields})


# --------------------------------------------------------------------------- GET


def test_the_defaults_of_a_fresh_install(make_app: AppFactory) -> None:
    web = make_app([router])
    response = web.client.get(BASE)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["storage_backend"] == "file"
    assert body["storage_connection"] is None
    assert body["storage_database"] == "sankey_studio"
    assert body["mongo_connections"] == []
    assert (body["theme"], body["max_upload_mb"], body["max_drawn_links"]) == ("system", 25, 3000)
    assert body["bootstrap"] == {
        "sources_dir": str(web.config.effective_sources_dir),
        "graphs_dir": str(web.config.graphs_dir),
        "remote_mode": False,
        "writes_allowed": True,
    }


def test_a_connection_is_listed_masked_and_never_with_its_uri(
    web: WebApp, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = web.client.get(BASE)
    assert response.status_code == 200
    assert response.json()["mongo_connections"] == [
        {
            "name": "test",
            "uri_masked": MASKED_TEST_URI,
            "has_secret": True,
            "default_database": "flows",
        }
    ]
    assert "uri" not in key_names(response.json())
    assert PASSWORD not in response.text
    assert PASSWORD not in caplog.text


def test_get_needs_no_write_permission_and_no_body(web: WebApp) -> None:
    assert web.bare.get(BASE).status_code == 200
    assert web.client.post(BASE).status_code == 405
    assert web.client.delete(BASE).status_code == 405


# --------------------------------------------------------------------------- PUT: secrets


def test_the_answer_of_get_can_be_put_back_without_losing_the_secret(web: WebApp) -> None:
    body = put_body(web.client)
    response = web.client.put(BASE, json=body)
    assert response.status_code == 200
    assert response.json()["settings"] == body
    assert response.json()["copy_report"] is None
    assert stored_uri(web) == TEST_URI


class Sent(NamedTuple):
    """The ``uri`` of a connection in a PUT body (``MISSING``: the key is left out)."""

    uri: object
    kept: bool


MISSING = object()
KEEPS = [
    Sent(MISSING, kept=True),
    Sent(None, kept=True),
    Sent("", kept=True),
    Sent("   ", kept=True),
    Sent(MASKED_TEST_URI, kept=True),
    Sent("mongodb://***", kept=True),
    Sent(NEW_URI, kept=False),
]


@pytest.mark.parametrize(
    "sent",
    KEEPS,
    # a stable id: repr(MISSING) holds an address, and mutmut re-selects tests by node id
    ids=["missing" if s.uri is MISSING else repr(s.uri) for s in KEEPS],
)
def test_only_a_real_uri_replaces_the_stored_secret(web: WebApp, sent: Sent) -> None:
    fields = {} if sent.uri is MISSING else {"uri": sent.uri}
    response = put(web.client, [connection(**fields)])
    assert response.status_code == 200
    assert stored_uri(web) == (TEST_URI if sent.kept else NEW_URI)
    assert "n3w-pass" not in response.text
    assert PASSWORD not in response.text
    listed = response.json()["settings"]["mongo_connections"]
    assert [c["has_secret"] for c in listed] == [True]
    assert [c["uri_masked"] for c in listed] == [
        MASKED_TEST_URI if sent.kept else "mongodb://new-user:***@elsewhere.invalid:27018/"
    ]


def test_a_renamed_connection_keeps_its_secret(web: WebApp) -> None:
    response = put(web.client, [connection(name="renamed", previous_name="test")])
    assert response.status_code == 200
    assert stored_names(web) == ["renamed"]
    assert stored_uri(web, "renamed") == TEST_URI
    assert [c["name"] for c in response.json()["settings"]["mongo_connections"]] == ["renamed"]


def test_a_new_connection_without_a_uri_is_refused_and_nothing_is_saved(web: WebApp) -> None:
    response = put(web.client, [connection(), connection(name="fresh")], theme="dark")
    assert response.status_code == 422
    assert error_of(response) == {
        "code": "settings_error",
        "message": "Connection 'fresh' needs a connection string",
        "details": [],
    }
    assert stored_names(web) == ["test"]
    assert web.services.settings().theme == "system"


def test_a_new_connection_with_a_real_uri_is_added_next_to_the_old_one(web: WebApp) -> None:
    response = put(web.client, [connection(), connection(name="second", uri=NEW_URI)])
    assert response.status_code == 200
    assert stored_names(web) == ["test", "second"]
    assert (stored_uri(web), stored_uri(web, "second")) == (TEST_URI, NEW_URI)
    assert "n3w-pass" not in response.text


def test_removing_a_connection_from_the_body_removes_it(web: WebApp) -> None:
    response = put(web.client, [])
    assert response.status_code == 200
    assert response.json()["settings"]["mongo_connections"] == []
    assert stored_names(web) == []


def test_no_log_line_of_a_save_or_a_read_carries_a_secret(
    web: WebApp, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        saved = put(web.client, [connection(uri=NEW_URI)])
        read = web.client.get(BASE)
    assert (saved.status_code, read.status_code) == (200, 200)
    for secret in (PASSWORD, "n3w-pass"):
        assert secret not in caplog.text
        assert secret not in read.text


# --------------------------------------------------------------------------- PUT: other fields


def test_plain_settings_are_saved_and_read_back(web: WebApp) -> None:
    response = put(web.client, [connection()], theme="dark", max_upload_mb=7, max_links=1234)
    assert response.status_code == 200
    saved = response.json()["settings"]
    assert (saved["theme"], saved["max_upload_mb"], saved["max_links"]) == ("dark", 7, 1234)
    assert web.client.get(BASE).json()["theme"] == "dark"
    stored = web.services.settings()
    assert (stored.theme, stored.max_upload_mb, stored.max_links) == ("dark", 7, 1234)


class Limit(NamedTuple):
    field: str
    value: int
    ok: bool


LIMITS = [
    Limit("max_links", 99, ok=False),
    Limit("max_links", 100, ok=True),
    Limit("max_drawn_links", 49, ok=False),
    Limit("max_drawn_links", 50, ok=True),
    Limit("max_drawn_links", 20_000, ok=True),
    Limit("max_drawn_links", 20_001, ok=False),
    Limit("max_upload_mb", 0, ok=False),
    Limit("max_upload_mb", 1, ok=True),
    Limit("max_upload_mb", 100, ok=True),
    Limit("max_upload_mb", 101, ok=False),
    Limit("mongo_timeout_ms", 499, ok=False),
    Limit("mongo_timeout_ms", 500, ok=True),
    Limit("mongo_timeout_ms", 300_000, ok=True),
    Limit("mongo_timeout_ms", 300_001, ok=False),
]


@pytest.mark.parametrize("case", LIMITS, ids=[f"{c.field}={c.value}" for c in LIMITS])
def test_the_numeric_limits_of_the_body(web: WebApp, case: Limit) -> None:
    response = put(web.client, [connection()], **{case.field: case.value})
    if case.ok:
        assert response.status_code == 200
        assert response.json()["settings"][case.field] == case.value
        return
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert [d.split(":")[0] for d in error["details"]] == [f"body.{case.field}"]
    assert getattr(web.services.settings(), case.field) != case.value


# --------------------------------------------------------------------------- PUT: errors


def test_unknown_fields_and_bad_values_are_a_422_that_never_echoes_input(web: WebApp) -> None:
    hostile = {"name": "x", "uri": "mongodb://u:topsecret@h/", "color": "topsecret"}
    response = web.client.put(
        BASE, json={"storage_backend": "bogus-backend", "mongo_connections": [hostile]}
    )
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert error["message"] == "The request is not valid"
    assert sorted(d.split(":")[0] for d in error["details"]) == [
        "body.mongo_connections.0.color",
        "body.storage_backend",
    ]
    assert "topsecret" not in response.text
    assert "bogus-backend" not in response.text


def test_a_dangerous_uri_option_is_refused_without_echoing_the_uri(web: WebApp) -> None:
    uri = "mongodb://u:topsecret@h.invalid/?tlsCAFile=/etc/ssl/ca.crt"
    response = put(web.client, [connection(name="evil", uri=uri)])
    assert response.status_code == 422
    assert error_of(response) == {
        "code": "settings_error",
        "message": "Settings are invalid",
        "details": ["mongo_connections.0.uri: Value error, uri option 'tlsCAFile' is not allowed"],
    }
    assert "topsecret" not in response.text
    assert "/etc/ssl" not in response.text
    assert stored_names(web) == ["test"]


@pytest.mark.parametrize("body", ["[]", '"text"', "null", "{"])
def test_a_body_that_is_not_an_object_is_a_422(web: WebApp, body: str) -> None:
    response = web.client.put(BASE, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert error_of(response)["code"] == "validation_error"


def test_the_migrate_flag_must_be_a_boolean(web: WebApp) -> None:
    response = web.client.put(f"{BASE}?migrate=banana", json=put_body(web.client))
    assert response.status_code == 422
    assert error_of(response)["details"][0].startswith("query.migrate:")
    assert web.client.put(f"{BASE}?migrate=false", json=put_body(web.client)).status_code == 200


def test_migrate_without_a_change_of_storage_copies_nothing(web: WebApp) -> None:
    response = web.client.put(f"{BASE}?migrate=true", json=put_body(web.client))
    assert response.status_code == 200
    assert response.json()["copy_report"] is None
