# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Settings over the wire: what ``PUT /settings`` accepts and what ``GET /settings`` returns.

``AppSettings`` itself never crosses the API: its connection URIs are secrets. A request carries
``MongoConnectionIn`` (the URI is optional), a response carries ``ConnectionOut`` (a masked URI and
``has_secret``, never a field called ``uri``). ``merge_settings`` is the ONE place that decides
whether an incoming URI replaces the stored secret or leaves it alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from sankey_studio.errors import SettingsError
from sankey_studio.models import CONNECTION_NAME_RE, AppSettings, StyleSpec
from sankey_studio.storage import load_settings
from sankey_studio.util import MASKED_URI, looks_masked, mask_uri

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sankey_studio.config import BootstrapConfig
    from sankey_studio.models import MongoConnection
    from sankey_studio.services import UpdateResult
    from sankey_studio.storage import CopyReport

__all__ = [
    "BootstrapOut",
    "ConnectionOut",
    "CopyReportOut",
    "MongoConnectionIn",
    "SettingsIn",
    "SettingsOut",
    "SettingsSaved",
    "bootstrap_out",
    "connection_out",
    "merge_settings",
    "settings_out",
    "settings_saved",
]

#: Fields of ``SettingsIn`` that are answers of ``GET /settings`` echoed back, never stored.
_ECHO_ONLY = {"mongo_connections", "bootstrap"}


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


# --------------------------------------------------------------------------- requests


class BootstrapOut(_Wire):
    """The operator-level settings, read-only in the UI (they come from the environment/CLI)."""

    sources_dir: str
    graphs_dir: str
    remote_mode: bool
    writes_allowed: bool


class MongoConnectionIn(_Wire):
    """A connection as submitted. ``uri`` is optional: leave it out to keep the stored secret.

    ``previous_name`` is the name the connection had when the page was loaded (a rename keeps the
    secret). ``uri_masked`` and ``has_secret`` are accepted so a ``GET /settings`` answer can be
    sent back as it is; they are ignored.
    """

    name: str = Field(pattern=CONNECTION_NAME_RE.pattern)
    uri: SecretStr | None = None
    previous_name: str | None = Field(default=None, pattern=CONNECTION_NAME_RE.pattern)
    default_database: str | None = Field(default=None, max_length=64)
    uri_masked: str | None = None
    has_secret: bool | None = None


class SettingsIn(_Wire):
    """The body of ``PUT /settings``: ``AppSettings`` with ``MongoConnectionIn`` connections.

    The limits repeat those of ``AppSettings`` so a bad value is a 422 on the body; the merged
    result is validated again by ``AppSettings`` (``merge_settings``). ``bootstrap`` is the
    read-only block of ``GET /settings``, accepted and ignored.
    """

    storage_backend: Literal["file", "mongo"] = "file"
    storage_connection: str | None = None
    storage_database: str = Field(default="sankey_studio", max_length=64)
    mongo_connections: list[MongoConnectionIn] = Field(default_factory=list, max_length=20)
    theme: Literal["system", "light", "dark"] = "system"
    default_style: StyleSpec = Field(default_factory=StyleSpec)
    max_links: int = Field(default=200_000, ge=100, le=5_000_000)
    max_drawn_links: int = Field(default=3_000, ge=50, le=20_000)
    max_upload_mb: int = Field(default=25, ge=1, le=100)
    mongo_timeout_ms: int = Field(default=15_000, ge=500, le=300_000)
    bootstrap: BootstrapOut | None = None


def _connection_doc(conn: MongoConnectionIn, secrets: Mapping[str, str]) -> dict[str, Any]:
    """The ``settings.json`` form of one incoming connection, with the secret decided.

    The stored secret is looked up by ``previous_name or name`` and kept when the submitted URI is
    missing, empty, a masked placeholder or equal to ``mask_uri`` of the stored one. When
    ``previous_name`` is not stored but ``name`` is, the rename already happened (a retried
    request): the secret of ``name`` is kept, so the retry is idempotent. A connection that has no
    stored secret and brings no real URI is a ``SettingsError``.
    """
    stored = secrets.get(conn.previous_name or conn.name, secrets.get(conn.name))
    supplied = "" if conn.uri is None else conn.uri.get_secret_value().strip()
    keeps = not supplied or looks_masked(supplied)
    keeps = keeps or (stored is not None and supplied == mask_uri(stored))
    if keeps and stored is None:
        raise SettingsError(f"Connection '{conn.name}' needs a connection string")
    return {
        "name": conn.name,
        "uri": stored if keeps else supplied,
        "default_database": conn.default_database,
    }


def merge_settings(stored: AppSettings, incoming: SettingsIn) -> AppSettings:
    """``incoming`` as ``AppSettings``, keeping the stored URI of every connection that sent none.

    Raises ``SettingsError`` for a connection without any secret and for settings that
    ``AppSettings`` refuses (the message lists locations and reasons, never a submitted value).
    """
    secrets = {conn.name: conn.uri.get_secret_value() for conn in stored.mongo_connections}
    doc = incoming.model_dump(exclude=_ECHO_ONLY)
    doc["mongo_connections"] = [
        _connection_doc(conn, secrets) for conn in incoming.mongo_connections
    ]
    return load_settings(doc)


# --------------------------------------------------------------------------- responses


class ConnectionOut(_Wire):
    """A connection as returned: the URI is masked, or hidden altogether in read-only mode."""

    name: str
    uri_masked: str
    has_secret: bool
    default_database: str | None


class SettingsOut(_Wire):
    """The answer of ``GET /settings``. There is no field called ``uri`` anywhere in it."""

    storage_backend: Literal["file", "mongo"]
    storage_connection: str | None
    storage_database: str
    mongo_connections: list[ConnectionOut]
    theme: Literal["system", "light", "dark"]
    default_style: StyleSpec
    max_links: int
    max_drawn_links: int
    max_upload_mb: int
    mongo_timeout_ms: int
    bootstrap: BootstrapOut


class CopyReportOut(_Wire):
    """What a storage switch with ``migrate=true`` copied (``storage.CopyReport`` as JSON)."""

    copied: int
    skipped: int
    unreadable: int
    unreadable_ids: list[str]
    folders: int
    folders_skipped: int


class SettingsSaved(_Wire):
    """The answer of ``PUT /settings``: the settings as saved and the copy report, if one ran."""

    settings: SettingsOut
    copy_report: CopyReportOut | None


def bootstrap_out(config: BootstrapConfig) -> BootstrapOut:
    return BootstrapOut(
        sources_dir=str(config.effective_sources_dir),
        graphs_dir=str(config.graphs_dir),
        remote_mode=config.remote_mode,
        writes_allowed=config.privileged_writes_allowed,
    )


def connection_out(conn: MongoConnection, *, hide_hosts: bool) -> ConnectionOut:
    """``mask_uri`` output, or a bare placeholder when ``hide_hosts`` (no host, no user name)."""
    raw = conn.uri.get_secret_value()
    return ConnectionOut(
        name=conn.name,
        uri_masked=MASKED_URI if hide_hosts else mask_uri(raw),
        has_secret=bool(raw),
        default_database=conn.default_database,
    )


def settings_out(settings: AppSettings, config: BootstrapConfig) -> SettingsOut:
    """The API form of ``settings``; remote read-only mode hides connection hosts and user names."""
    hide = not config.privileged_writes_allowed
    return SettingsOut(
        **settings.model_dump(exclude={"mongo_connections"}),
        mongo_connections=[connection_out(c, hide_hosts=hide) for c in settings.mongo_connections],
        bootstrap=bootstrap_out(config),
    )


def _copy_report_out(report: CopyReport | None) -> CopyReportOut | None:
    if report is None:
        return None
    return CopyReportOut(
        copied=report.copied,
        skipped=report.skipped,
        unreadable=report.unreadable,
        unreadable_ids=list(report.unreadable_ids),
        folders=report.folders,
        folders_skipped=report.folders_skipped,
    )


def settings_saved(result: UpdateResult, config: BootstrapConfig) -> SettingsSaved:
    """The ``PUT /settings`` answer for an ``UpdateResult`` of ``Services.update_settings``."""
    return SettingsSaved(
        settings=settings_out(result.settings, config),
        copy_report=_copy_report_out(result.copy_report),
    )
