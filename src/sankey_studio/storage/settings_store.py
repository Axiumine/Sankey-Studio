# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``settings.json`` and ``credentials.json``: the only code that reads and writes real Mongo URIs.

The settings live in two files of the data directory. ``settings.json`` holds everything but the
connection strings; ``credentials.json`` (``models.credentials``) holds the strings, keyed by
connection name. Both are written atomically with mode 0600 inside a 0700 data directory, the
secrets first. ``dump_settings`` / ``load_settings`` are the ONLY code that turns the
``SecretStr`` of a ``MongoConnection`` into text and back (``storage.credentials`` splits and
joins the plain dicts they handle); everything else (``repr``, ``model_dump``, logs, API output)
only ever sees masked values.

Loading: a ``uri`` still inside ``settings.json`` (a file from before ``credentials.json``
existed) is used and moved to ``credentials.json`` by the next save. A settings file that cannot
be understood is moved aside (``.corrupt-<n>``, still 0600, together with ``credentials.json``
under the same number) and reported instead of being overwritten or silently replaced by
defaults. A ``credentials.json`` that cannot be used is reported and left where it is: unlike the
settings it has no default to fall back to.
"""

from __future__ import annotations

import json
import os
import threading
from typing import TYPE_CHECKING, Any, NoReturn

from pydantic import ValidationError

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.models.credentials import StoredCredentials
from sankey_studio.storage.atomic import (
    FILE_MODE,
    ensure_private_dir,
    os_reason,
    read_file_nofollow,
    read_private_file,
    write_atomic,
)
from sankey_studio.storage.common import validation_lines
from sankey_studio.storage.credentials import join_credentials, split_credentials

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.config import BootstrapConfig

SETTINGS_MAX_BYTES = 1024 * 1024
CREDENTIALS_MAX_BYTES = 1024 * 1024
#: At most this many ``settings.json.corrupt-<n>`` files are kept (the last one is reused).
MAX_CORRUPT_COPIES = 20
MAX_DETAILS = 20
#: Location label of an error that belongs to the settings as a whole.
SETTINGS_ROOT = "settings"
CREDENTIALS_ROOT = "credentials"
SEED_CONNECTION = "default"
MSG_TOO_LARGE = "Settings are too large to save"
MSG_CREDENTIALS_TOO_LARGE = "Credentials are too large to save"
MSG_CREDENTIALS_INVALID = "credentials.json is invalid"
MSG_CREDENTIALS_NOT_JSON = "credentials.json is not valid JSON"
MSG_CREDENTIALS_MISSING = "credentials.json has no connection string for some connections"
#: ``json.dumps`` escapes every non-ASCII character, so the file is ASCII (and size == chars).
FILE_ENCODING = "ascii"

#: ``(st_mtime_ns, st_size, st_ino)`` of one file; ``None`` while it does not exist.
Signature = tuple[int, int, int]
#: What the cache is keyed on: the signatures of ``settings.json`` and ``credentials.json``.
Stamp = tuple[Signature | None, Signature | None]
#: What makes a settings file "corrupt": not JSON, nested too deep, or not a valid settings
#: document. A constant, not a three-name ``except A, B, C:``, which Semgrep cannot parse yet.
_CORRUPT = (SettingsError, ValueError, RecursionError)
#: Text that is not a JSON document (``ValidationError`` is a ``ValueError``: catch it first).
_NOT_JSON = (ValueError, RecursionError)


def _details(exc: ValidationError) -> list[str]:
    return validation_lines(exc, SETTINGS_ROOT)[:MAX_DETAILS]


def dump_settings(settings: AppSettings) -> dict[str, Any]:
    """JSON-ready dict with the REAL connection URIs (in memory only: ``save`` splits it)."""
    doc = settings.model_dump(mode="json")
    for index, conn in enumerate(settings.mongo_connections):
        doc["mongo_connections"][index]["uri"] = conn.uri.get_secret_value()
    return doc


def load_settings(doc: object) -> AppSettings:
    """Validate a ``dump_settings`` document. A masked placeholder URI is refused.

    Raises ``SettingsError`` listing field locations and messages, never the input.
    """
    try:
        return AppSettings.model_validate(doc)
    except ValidationError as exc:
        raise SettingsError("Settings are invalid", details=_details(exc)) from None


def _signature(path: Path) -> Signature | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return info.st_mtime_ns, info.st_size, info.st_ino


def _encode(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, indent=2).encode(FILE_ENCODING)


class SettingsStore:
    """Thread-safe, mtime-cached access to ``<data_dir>/settings.json`` and ``credentials.json``."""

    def __init__(self, config: BootstrapConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._cached: tuple[Stamp, AppSettings] | None = None

    def load(self) -> AppSettings:
        """The stored settings; defaults (seeded from ``SANKEY_MONGO_URI``) while no file exists."""
        with self._lock:
            return self._load()

    def save(self, settings: AppSettings) -> AppSettings:
        """Persist ``settings`` (validated first) and return what a later ``load`` will see.

        ``SettingsError`` before anything is written when either file would exceed its cap
        (``SETTINGS_MAX_BYTES``, ``CREDENTIALS_MAX_BYTES``), the size ``load`` accepts: a larger
        file could never be read back. ``credentials.json`` is replaced first: a crash between
        the two writes leaves every connection of the old settings with a string, except one
        that this save removes or renames (``load`` then names it, see ``_read``).
        """
        doc = dump_settings(settings)
        saved = load_settings(doc)
        public, secret = split_credentials(doc)
        data, secret_data = _encode(public), _encode(secret)
        if len(data) > SETTINGS_MAX_BYTES:
            raise SettingsError(MSG_TOO_LARGE)
        if len(secret_data) > CREDENTIALS_MAX_BYTES:
            raise SettingsError(MSG_CREDENTIALS_TOO_LARGE)
        with self._lock:
            try:
                ensure_private_dir(self._config.data_dir)
                write_atomic(self._config.credentials_file, secret_data)
                write_atomic(self._config.settings_file, data)
            except OSError as exc:
                raise SettingsError(f"Settings could not be saved: {os_reason(exc)}") from exc
            self._cached = (self._stamp(), saved)
        return saved

    def _stamp(self) -> Stamp:
        return _signature(self._config.settings_file), _signature(self._config.credentials_file)

    def _load(self) -> AppSettings:
        self._check_data_dir()
        stamp = self._stamp()
        if self._cached is not None and self._cached[0] == stamp:
            return self._cached[1]
        settings = self._defaults() if stamp[0] is None else self._read()
        self._cached = (stamp, settings)
        return settings

    def _check_data_dir(self) -> None:
        """Refuse a data directory owned by someone else; repair a group/other-writable one."""
        if not self._config.data_dir.exists():
            return
        try:
            ensure_private_dir(self._config.data_dir)
        except OSError as exc:
            raise SettingsError(f"The data directory is not safe: {os_reason(exc)}") from exc

    def _defaults(self) -> AppSettings:
        seed = self._config.mongo_uri
        if seed is None:
            return AppSettings()
        try:
            conn = MongoConnection(name=SEED_CONNECTION, uri=seed)
        except ValidationError as exc:
            raise SettingsError(
                "SANKEY_MONGO_URI is not a valid MongoDB connection string",
                details=_details(exc),
            ) from None
        return AppSettings(mongo_connections=[conn])

    def _read(self) -> AppSettings:
        """The settings of the two files. ``SettingsError`` for each way they can fail.

        An unreadable file, a broken ``credentials.json`` and a connection without a string are
        reported and leave both files alone (nothing is lost, and a save cannot overwrite them:
        it starts from this load). Only a ``settings.json`` that is not JSON or not valid
        settings is moved aside.
        """
        try:
            raw = read_file_nofollow(self._config.settings_file, SETTINGS_MAX_BYTES)
        except OSError as exc:
            raise SettingsError(f"Settings file cannot be read: {os_reason(exc)}") from exc
        try:
            doc = json.loads(raw)
        except _NOT_JSON:
            self._set_aside()
        joined = join_credentials(doc, self._secrets())
        if joined.missing:
            lines = [f"{name}: no entry in credentials.json" for name in joined.missing]
            raise SettingsError(MSG_CREDENTIALS_MISSING, details=lines[:MAX_DETAILS])
        try:
            return load_settings(joined.doc)
        except _CORRUPT:
            self._set_aside()

    def _secrets(self) -> dict[str, str]:
        """``{connection name: URI}`` of ``credentials.json``; empty while the file is absent."""
        try:
            raw = read_private_file(self._config.credentials_file, CREDENTIALS_MAX_BYTES)
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise SettingsError(f"Credentials file cannot be read: {os_reason(exc)}") from exc
        try:
            stored = StoredCredentials.model_validate(json.loads(raw))
        except ValidationError as exc:
            lines = validation_lines(exc, CREDENTIALS_ROOT)[:MAX_DETAILS]
            raise SettingsError(MSG_CREDENTIALS_INVALID, details=lines) from None
        except _NOT_JSON:
            raise SettingsError(MSG_CREDENTIALS_NOT_JSON) from None
        return {
            name: item.uri.get_secret_value() for name, item in stored.mongo_connections.items()
        }

    def _set_aside(self) -> NoReturn:
        """Move the unusable ``settings.json`` (and ``credentials.json``) aside, then report it.

        Both go to the first number that is free for both, so a repair finds the pair. The
        secrets go first: when that move fails nothing has changed and the next load retries.
        Only a regular file is moved: a symlink (or anything else) at that name is the
        operator's, and ``chmod`` of the copy would follow it.
        """
        path, secrets = self._config.settings_file, self._config.credentials_file
        number = self._free_number((path, secrets))
        if secrets.is_file() and not secrets.is_symlink():
            self._move_aside(secrets, number, "Credentials file")
        moved = self._move_aside(path, number, "Corrupt settings file")
        raise SettingsError(f"Settings file is corrupt; it was moved to {moved.name}") from None

    @staticmethod
    def _free_number(paths: tuple[Path, ...]) -> int:
        """The first ``n`` that no ``<name>.corrupt-<n>`` of ``paths`` uses (else the last)."""
        for number in range(1, MAX_CORRUPT_COPIES):
            copies = (p.with_name(f"{p.name}.corrupt-{number}") for p in paths)
            if not any(os.path.lexists(copy) for copy in copies):
                return number
        return MAX_CORRUPT_COPIES

    @staticmethod
    def _move_aside(path: Path, number: int, what: str) -> Path:
        """Rename ``path`` to ``<name>.corrupt-<number>`` and keep it 0600."""
        target = path.with_name(f"{path.name}.corrupt-{number}")
        try:
            path.replace(target)
            target.chmod(FILE_MODE)
        except OSError as exc:
            raise SettingsError(f"{what} cannot be moved: {os_reason(exc)}") from exc
        return target
