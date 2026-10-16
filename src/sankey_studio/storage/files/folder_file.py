# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``folders.json``: every library folder in ONE file next to the graph files.

The name never matches the graph file pattern (``<32 hex>.json``), so the graph index ignores it
and ``unreadable_ids()`` stays clean; the temporary files of an atomic write start with a dot and
are ignored too. The file is written atomically (mode 0600) and read with ``O_NOFOLLOW`` and a size
cap. Reads are cached by the ``(mtime_ns, size, inode)`` signature, so another process replacing
the file is noticed.

A damaged file (bad JSON, wrong envelope, a newer ``schema_version``, an invalid or repeated
folder, too many folders) fails SOFT on reads (no folders, so every graph shows at the top level,
one warning in the log) and CLOSED on writes (``StorageError``: saving over it would destroy it).
Callers hold the directory lock around every call.
"""

from __future__ import annotations

import json
import logging
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sankey_studio.errors import StorageError
from sankey_studio.models import FOLDERS_MAX, SCHEMA_VERSION
from sankey_studio.storage.atomic import os_reason, read_file_nofollow, write_atomic
from sankey_studio.storage.folders_base import parse_folder

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.models import FolderDefinition

logger = logging.getLogger(__name__)

FOLDERS_FILENAME: Final = "folders.json"
#: Far above 1000 folders of about 300 bytes each; also the largest file that is read.
MAX_FOLDERS_BYTES: Final = 4 * 1024 * 1024
MSG_TOO_MANY = "Too many collections to save"
MSG_DAMAGED = "The collections file is unreadable; fix or remove it (graphs are not affected)"

#: ``(st_mtime_ns, st_size, st_ino)``: an atomic replace always changes the inode.
Signature = tuple[int, int, int]
#: What a damaged file raises: bad JSON, nesting too deep, an invalid record. A constant tuple,
#: not a three-name ``except A, B, C:``, which Semgrep cannot parse.
_DAMAGED = (ValueError, RecursionError, StorageError)
#: Two-space indent, pure ASCII (every other character is escaped), ``NaN`` refused.
_ENCODER = json.JSONEncoder(indent=2, ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """What the file held when it had ``signature``; ``items`` is ``None`` for a damaged file."""

    signature: Signature | None
    items: tuple[FolderDefinition, ...] | None


#: Stands for "something is there, but it cannot be the folders file": never equals a real stat.
NOT_A_FILE: Final[Signature] = (-1, -1, -1)


def _signature(path: Path) -> Signature | None:
    """The signature of the regular file; ``None`` when it is missing."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):  # a symlink, directory or FIFO is never the folders file
        return NOT_A_FILE
    return info.st_mtime_ns, info.st_size, info.st_ino


def _records(doc: object) -> list[dict[str, Any]] | None:
    """The folder records of a decoded file, or ``None`` when the envelope is wrong."""
    if not isinstance(doc, dict):
        return None
    version, records = doc.get("schema_version"), doc.get("folders")
    if not isinstance(version, int) or not 1 <= version <= SCHEMA_VERSION:
        return None
    if not isinstance(records, list) or len(records) > FOLDERS_MAX:
        return None
    if not all(isinstance(record, dict) for record in records):
        return None
    return records


def _parse(raw: bytes) -> tuple[FolderDefinition, ...] | None:
    """The folders of a file's bytes, or ``None`` when the file is damaged."""
    try:
        records = _records(json.loads(raw))
        items = tuple(parse_folder(record) for record in records or [])
    except _DAMAGED:
        return None
    if records is None or len({item.id for item in items}) != len(items):
        return None
    return items


class FolderFile:
    def __init__(self, directory: Path) -> None:
        self._path = directory / FOLDERS_FILENAME
        self._snapshot = _Snapshot(None, ())

    def _load(self) -> _Snapshot:
        signature = _signature(self._path)
        if signature is None:
            return _Snapshot(None, ())
        if signature == NOT_A_FILE:
            return _Snapshot(signature, None)
        try:
            raw = read_file_nofollow(self._path, MAX_FOLDERS_BYTES)
        except FileNotFoundError:  # replaced or removed between the stat and the open
            return _Snapshot(None, ())
        except OSError:
            return _Snapshot(signature, None)
        return _Snapshot(signature, _parse(raw))

    def _current(self) -> _Snapshot:
        """The snapshot of the file as it is NOW (re-read only when its signature changed)."""
        signature = _signature(self._path)
        if signature == self._snapshot.signature:
            return self._snapshot
        self._snapshot = self._load()
        if self._snapshot.items is None:
            logger.warning("The collections file is unreadable")
        return self._snapshot

    def read(self) -> list[FolderDefinition]:
        """Every folder; none when the file is missing or damaged (the latter is logged)."""
        items = self._current().items
        return [] if items is None else list(items)

    def read_for_write(self) -> list[FolderDefinition]:
        """Like ``read``, but a damaged file raises ``StorageError`` instead of reading as empty."""
        items = self._current().items
        if items is None:
            raise StorageError(MSG_DAMAGED)
        return list(items)

    def save(self, items: list[FolderDefinition]) -> None:
        """Replace the file with ``items`` (a new signature is remembered for the next read)."""
        doc = {
            "schema_version": SCHEMA_VERSION,
            "folders": [i.model_dump(mode="json") for i in items],
        }
        data = _ENCODER.encode(doc).encode("ascii")
        if len(data) > MAX_FOLDERS_BYTES:
            raise StorageError(MSG_TOO_MANY)
        try:
            write_atomic(self._path, data)
        except OSError as exc:
            raise StorageError(f"The collections could not be saved: {os_reason(exc)}") from exc
        self._snapshot = _Snapshot(_signature(self._path), tuple(items))
