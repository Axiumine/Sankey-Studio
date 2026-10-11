"""``settings.json``: the one place that reads and writes real Mongo URIs.

``dump_settings`` / ``load_settings`` are the ONLY code that turns the ``SecretStr`` of a
``MongoConnection`` into text and back; everything else (``repr``, ``model_dump``, logs, API
output) only ever sees masked values. The file is written atomically with mode 0600 inside a 0700
data directory; a file that cannot be understood is moved aside (``.corrupt-<n>``, still 0600)
and reported instead of being overwritten or silently replaced by defaults.
"""

from __future__ import annotations

import json
import os
import threading
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.storage.atomic import (
    FILE_MODE,
    ensure_private_dir,
    os_reason,
    read_file_nofollow,
    write_atomic,
)
from sankey_studio.storage.common import validation_lines

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.config import BootstrapConfig

SETTINGS_MAX_BYTES = 1024 * 1024
#: At most this many ``settings.json.corrupt-<n>`` files are kept (the last one is reused).
MAX_CORRUPT_COPIES = 20
MAX_DETAILS = 20
#: Location label of an error that belongs to the settings as a whole.
SETTINGS_ROOT = "settings"
SEED_CONNECTION = "default"
MSG_TOO_LARGE = "Settings are too large to save"

#: ``(st_mtime_ns, st_size, st_ino)`` of ``settings.json``; ``None`` while it does not exist.
Signature = tuple[int, int, int]
#: What makes a settings file "corrupt": not JSON, nested too deep, or not a valid settings
#: document. A constant, not a three-name ``except A, B, C:``, which Semgrep cannot parse yet.
_CORRUPT = (SettingsError, ValueError, RecursionError)


def _details(exc: ValidationError) -> list[str]:
    return validation_lines(exc, SETTINGS_ROOT)[:MAX_DETAILS]


def dump_settings(settings: AppSettings) -> dict[str, Any]:
    """JSON-ready dict with the REAL connection URIs (for ``settings.json`` only)."""
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


class SettingsStore:
    """Thread-safe, mtime-cached access to ``<data_dir>/settings.json``."""

    def __init__(self, config: BootstrapConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._cached: tuple[Signature | None, AppSettings] | None = None

    def load(self) -> AppSettings:
        """The stored settings; defaults (seeded from ``SANKEY_MONGO_URI``) while no file exists."""
        with self._lock:
            return self._load()

    def save(self, settings: AppSettings) -> AppSettings:
        """Persist ``settings`` (validated first) and return what a later ``load`` will see.

        ``SettingsError`` before anything is written when the file would exceed
        ``SETTINGS_MAX_BYTES``, the size ``load`` accepts: a larger file could never be read back.
        """
        doc = dump_settings(settings)
        saved = load_settings(doc)
        data = json.dumps(doc, indent=2).encode("ascii")
        if len(data) > SETTINGS_MAX_BYTES:
            raise SettingsError(MSG_TOO_LARGE)
        path = self._config.settings_file
        with self._lock:
            try:
                ensure_private_dir(self._config.data_dir)
                write_atomic(path, data)
            except OSError as exc:
                raise SettingsError(f"Settings could not be saved: {os_reason(exc)}") from exc
            self._cached = (_signature(path), saved)
        return saved

    def _load(self) -> AppSettings:
        path = self._config.settings_file
        self._check_data_dir()
        signature = _signature(path)
        if self._cached is not None and self._cached[0] == signature:
            return self._cached[1]
        settings = self._defaults() if signature is None else self._read(path)
        self._cached = (signature, settings)
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

    def _read(self, path: Path) -> AppSettings:
        try:
            raw = read_file_nofollow(path, SETTINGS_MAX_BYTES)
        except OSError as exc:
            raise SettingsError(f"Settings file cannot be read: {os_reason(exc)}") from exc
        try:
            return load_settings(json.loads(raw))
        except _CORRUPT:
            moved = self._quarantine(path)
            raise SettingsError(f"Settings file is corrupt; it was moved to {moved.name}") from None

    @staticmethod
    def _quarantine(path: Path) -> Path:
        """Move the unreadable file to the first free ``.corrupt-<n>``; keep it 0600."""
        target = path.with_name(f"{path.name}.corrupt-{MAX_CORRUPT_COPIES}")
        for number in range(1, MAX_CORRUPT_COPIES):
            candidate = path.with_name(f"{path.name}.corrupt-{number}")
            if not os.path.lexists(candidate):
                target = candidate
                break
        try:
            path.replace(target)
            target.chmod(FILE_MODE)
        except OSError as exc:
            raise SettingsError(f"Corrupt settings file cannot be moved: {os_reason(exc)}") from exc
        return target
