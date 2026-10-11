"""Helpers of ``tests/web/test_routes_settings*.py`` (no tests here)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pymongo.errors import ServerSelectionTimeoutError

if TYPE_CHECKING:
    import pytest
    from fastapi.testclient import TestClient

    from tests.web.conftest import WebApp

BASE = "/api/v1/settings"
#: The secret inside the URI of the ``test`` connection of the ``app_settings`` fixture.
PASSWORD = "hunter2"
#: What ``mask_uri`` makes of ``tests.conftest.TEST_URI``.
MASKED_TEST_URI = "mongodb://tester:***@mongo.invalid:27017/?appName=tests"


def key_names(value: Any) -> set[str]:
    """Every dict key anywhere inside a JSON value."""
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= key_names(item)
        return found
    if isinstance(value, list):
        return {key for item in value for key in key_names(item)}
    return set()


def put_body(client: TestClient) -> dict[str, Any]:
    """The answer of ``GET /settings`` as the body of a ``PUT`` (the page does exactly this)."""
    response = client.get(BASE)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def stored_uri(web: WebApp, name: str = "test") -> str | None:
    """The real URI stored for connection ``name`` (``None`` when there is no such connection)."""
    connection = web.services.settings().connection(name)
    return None if connection is None else connection.uri.get_secret_value()


def stored_names(web: WebApp) -> list[str]:
    return [conn.name for conn in web.services.settings().mongo_connections]


def break_ping(monkeypatch: pytest.MonkeyPatch, web: WebApp) -> None:
    """Every ``ping`` command of the in-memory server fails like an unreachable host.

    The exception text carries the URI on purpose: it must never reach a response.
    """
    text = f"mongodb://tester:{PASSWORD}@mongo.invalid:27017 unreachable"

    def unreachable(*_args: object, **_kwargs: object) -> None:
        raise ServerSelectionTimeoutError(text)

    monkeypatch.setattr(type(web.mongo.admin), "command", unreachable)


def error_of(response: Any) -> dict[str, Any]:
    """The ``error`` object of an envelope (asserting the response is one)."""
    body = response.json()
    assert set(body) == {"error"}
    error: dict[str, Any] = body["error"]
    assert set(error) == {"code", "message", "details"}
    return error
