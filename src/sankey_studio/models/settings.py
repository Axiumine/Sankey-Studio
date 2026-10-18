# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Settings models persisted in ``settings.json``: Mongo connections and ``AppSettings``."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from sankey_studio.errors import UnsafeSourceError
from sankey_studio.models.base import CONNECTION_NAME_RE, _Model
from sankey_studio.models.fields import _safe_name
from sankey_studio.models.style import StyleSpec
from sankey_studio.mongo_safety import check_mongo_uri, validate_db_name
from sankey_studio.util import looks_masked


def checked_uri(v: SecretStr) -> SecretStr:
    """The stripped connection string; ``ValueError`` (never echoing it) when it is unusable.

    The one rule for both places a URI is read: ``MongoConnection.uri`` and the secrets file
    (``models.credentials``). A masked placeholder and an unsafe option are refused.
    """
    raw = v.get_secret_value().strip()
    if looks_masked(raw):
        raise ValueError("uri is a masked placeholder; enter the real connection string")
    try:
        check_mongo_uri(raw)
    except UnsafeSourceError as exc:
        raise ValueError(exc.message) from None
    return SecretStr(raw)


class MongoConnection(_Model):
    """A named MongoDB connection. The URI may hold credentials: never log or return it.

    The URI is validated at save time (``mongo_safety.check_mongo_uri``): options that read local
    files or ambient credentials are refused, and a masked placeholder (``mask_uri`` output,
    ``**********``) is refused so a UI round trip can never overwrite the real secret.
    """

    name: str
    uri: SecretStr
    default_database: str | None = Field(default=None, max_length=64)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not CONNECTION_NAME_RE.match(v):
            raise ValueError("connection name: 1-64 chars of letters, digits, '_', '.', '-'")
        return v

    @field_validator("uri")
    @classmethod
    def _uri(cls, v: SecretStr) -> SecretStr:
        return checked_uri(v)

    @field_validator("default_database")
    @classmethod
    def _default_database(cls, v: str | None) -> str | None:
        return v if v is None else _safe_name(validate_db_name, v)


class AppSettings(_Model):
    """User-editable settings, persisted to ``<data_dir>/settings.json``.

    SECRETS: ``MongoConnection.uri`` is a ``SecretStr``, so ``repr``/``str``/``model_dump()``/
    ``model_dump_json()`` never reveal it - but they also cannot round-trip it (the JSON form is
    ``**********``, which the validator refuses). The only code that may write or read the real
    values is ``storage.settings_store.dump_settings`` / ``load_settings``. Operator-level paths
    (``sources_dir``, remote mode) are NOT here: see ``config.BootstrapConfig``.
    """

    storage_backend: Literal["file", "mongo"] = "file"
    storage_connection: str | None = None
    #: Database that holds the ``sankey_studio_graphs`` and ``sankey_studio_collections``
    #: (library folders) collections when the backend is Mongo.
    storage_database: str = Field(default="sankey_studio", max_length=64)
    mongo_connections: list[MongoConnection] = Field(default_factory=list, max_length=20)
    theme: Literal["system", "light", "dark"] = "system"
    default_style: StyleSpec = Field(default_factory=StyleSpec)
    #: Cap on RAW rows read from one source (``GraphTooLargeError`` beyond it).
    max_links: int = Field(default=200_000, ge=100, le=5_000_000)
    #: Cap on links DRAWN in a figure (top-N by value; a note says "showing N of M links").
    max_drawn_links: int = Field(default=3_000, ge=50, le=20_000)
    max_upload_mb: int = Field(default=25, ge=1, le=100)
    mongo_timeout_ms: int = Field(default=15_000, ge=500, le=300_000)

    @field_validator("storage_database")
    @classmethod
    def _storage_database(cls, v: str) -> str:
        return _safe_name(validate_db_name, v)

    @model_validator(mode="after")
    def _consistent(self) -> AppSettings:
        names = [c.name for c in self.mongo_connections]
        if len(names) != len(set(names)):
            raise ValueError("mongo connection names must be unique")
        if self.storage_backend == "mongo" and self.storage_connection not in names:
            raise ValueError("storage_backend 'mongo' needs storage_connection naming a connection")
        return self

    def connection(self, name: str) -> MongoConnection | None:
        return next((c for c in self.mongo_connections if c.name == name), None)
