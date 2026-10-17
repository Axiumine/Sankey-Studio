# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The secrets file of the data directory: connection strings, apart from the settings.

``<data_dir>/credentials.json`` (version 1) holds one entry per MongoDB connection, keyed by the
connection name::

    {"version": 1, "mongo_connections": {"main": {"uri": "mongodb://user:pw@host/"}}}

``settings.json`` keeps the rest of the connection (name, default database) and no ``uri``.
Only ``storage.settings_store`` reads and writes the file. Every error here lists locations and
messages, never a value (``_Model`` hides the input).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator

from sankey_studio.models.base import CONNECTION_NAME_RE, _Model
from sankey_studio.models.settings import checked_uri

#: Same limit as ``AppSettings.mongo_connections``.
MAX_SECRETS = 20


class ConnectionSecret(_Model):
    """The secret part of one connection. Room for more fields (a key passphrase, a token)."""

    uri: SecretStr

    @field_validator("uri")
    @classmethod
    def _uri(cls, v: SecretStr) -> SecretStr:
        return checked_uri(v)


class StoredCredentials(_Model):
    """The whole file. A name without a connection in ``settings.json`` is allowed and ignored."""

    version: Literal[1] = 1
    mongo_connections: dict[str, ConnectionSecret] = Field(
        default_factory=dict, max_length=MAX_SECRETS
    )

    @field_validator("mongo_connections")
    @classmethod
    def _names(cls, v: dict[str, ConnectionSecret]) -> dict[str, ConnectionSecret]:
        if not all(CONNECTION_NAME_RE.match(name) for name in v):
            raise ValueError("connection name: 1-64 chars of letters, digits, '_', '.', '-'")
        return v
