# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Splitting the settings document in two, and putting it back together.

``dump_settings`` makes ONE document with the real connection strings inside. The store writes it
as two files: ``settings.json`` (everything but the strings) and the secrets file (only the
strings, keyed by connection name, ``models.credentials.StoredCredentials``). These pure
functions do the split and the join on plain dicts, so ``load_settings`` stays the one place
that validates a settings document and sees the same shape it always saw.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from sankey_studio.models.base import CONNECTION_NAME_RE

if TYPE_CHECKING:
    from collections.abc import Mapping

#: ``version`` written to the secrets file (``StoredCredentials.version``).
CREDENTIALS_VERSION = 1


class Joined(NamedTuple):
    """A settings document with the secrets put back, and the connections that had none."""

    doc: object
    missing: list[str]


def split_credentials(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(settings document without any uri, secrets document)`` of a ``dump_settings`` document."""
    secrets = {conn["name"]: {"uri": conn["uri"]} for conn in doc["mongo_connections"]}
    public = [{k: v for k, v in conn.items() if k != "uri"} for conn in doc["mongo_connections"]]
    return (
        {**doc, "mongo_connections": public},
        {"version": CREDENTIALS_VERSION, "mongo_connections": secrets},
    )


def _joined(conn: object, secrets: Mapping[str, str]) -> object:
    """``conn`` with its ``uri`` from ``secrets``; a ``uri`` already in ``conn`` wins."""
    if not isinstance(conn, dict) or "uri" in conn:
        return conn
    name = conn.get("name")
    if not isinstance(name, str) or name not in secrets:
        return conn
    return {**conn, "uri": secrets[name]}


def _missing(conn: object) -> str | None:
    """The name of a connection that still has no ``uri``; ``None`` if it has one or no valid name.

    A name that is not a valid connection name is left for ``load_settings`` to refuse; it is
    never put in a message.
    """
    if not isinstance(conn, dict) or "uri" in conn:
        return None
    name = conn.get("name")
    return name if isinstance(name, str) and CONNECTION_NAME_RE.match(name) else None


def join_credentials(doc: object, secrets: Mapping[str, str]) -> Joined:
    """Put each connection's string back into the parsed ``settings.json`` ``doc``.

    A ``uri`` that is still inside ``doc`` (a file written before the secrets file existed, or
    edited by hand) wins over the secrets file and is moved out on the next save. Any other
    shape of ``doc`` comes back as it is: ``load_settings`` reports it.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("mongo_connections"), list):
        return Joined(doc, [])
    joined = [_joined(conn, secrets) for conn in doc["mongo_connections"]]
    names = [_missing(conn) for conn in joined]
    return Joined({**doc, "mongo_connections": joined}, [n for n in names if n is not None])
