"""Settings helpers for the HTTP flows: the PUT body of a connection, JSON walkers, disk reads."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from tests.e2e.support.builders import MONGO_URI
from tests.e2e.support.clients import json_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

    from tests.e2e.support.server import LiveServer

SETTINGS_PATH: Final = "/api/v1/settings"


def connection(
    name: str = "main", uri: str | None = MONGO_URI, database: str | None = "flows"
) -> dict[str, Any]:
    """One ``mongo_connections`` item of a ``PUT /settings`` body (``uri`` omitted when None)."""
    item: dict[str, Any] = {"name": name, "default_database": database}
    if uri is not None:
        item["uri"] = uri
    return item


def get_settings(api: httpx.Client) -> dict[str, Any]:
    """``GET /settings`` (asserts the 200)."""
    return dict(json_of(api.get(SETTINGS_PATH)))


def put_settings(api: httpx.Client, body: dict[str, Any], status: int = 200) -> Any:
    """``PUT /settings`` with ``body``; asserts ``status`` and returns the parsed JSON."""
    return json_of(api.put(SETTINGS_PATH, json=body), status)


def stored_settings(server: LiveServer) -> dict[str, Any]:
    """The settings file as it is on disk (it holds the real URIs: the one place that may)."""
    return dict(json.loads(server.settings_file.read_text(encoding="utf-8")))


def stored_uris(server: LiveServer) -> dict[str, str]:
    """``{connection name: URI}`` as stored on disk."""
    return {item["name"]: item["uri"] for item in stored_settings(server)["mongo_connections"]}


def keys_of(value: Any) -> Iterator[str]:
    """Every dictionary key anywhere in a parsed JSON value."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield str(key)
            yield from keys_of(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from keys_of(inner)


def reset_settings(api: httpx.Client, server: LiveServer) -> None:
    """Back to the defaults on a shared server: no connections, default limits, Mongo reachable.

    ``PUT /settings`` replaces the stored settings and every field left out falls back to its
    default, so an empty body is "factory settings".
    """
    server.mongo.unreachable = False
    put_settings(api, {})
