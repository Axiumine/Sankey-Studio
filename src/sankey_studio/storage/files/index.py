# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""In-memory listing index of one graphs directory, validated by ``stat`` on every use.

Listing 1000 graphs must not parse 1000 JSON files per request. The index keeps one
``GraphSummary`` plus the case-folded search fields per file and re-reads a file only when its
``(mtime_ns, size, inode)`` signature changed. The repository writes through (``remember``) so
its own changes never wait for the next scan, and anything another process does to the directory
(including deleting a graph) is noticed by the signatures. Callers hold the directory lock
around every call.
"""

from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sankey_studio.errors import StorageError
from sankey_studio.storage.common import summary_of
from sankey_studio.storage.files.codec import GRAPH_SUFFIX, graph_filename, read_graph

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.models import GraphDefinition, GraphSummary

logger = logging.getLogger(__name__)

#: ``(st_mtime_ns, st_size, st_ino)``: an atomic replace always changes the inode.
Signature = tuple[int, int, int]

_FILE_RE = re.compile(r"[0-9a-f]{32}\.json")


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """A readable graph: its summary and the lower-cased fields a text search looks at."""

    summary: GraphSummary
    folded: tuple[str, ...]


def _signature(item: os.DirEntry[str]) -> Signature | None:
    """The signature of a regular file; ``None`` for anything else or a file that just vanished."""
    try:
        info = item.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):  # symlinks, directories and FIFOs are never graphs
        return None
    return info.st_mtime_ns, info.st_size, info.st_ino


def entry_of(graph: GraphDefinition) -> IndexEntry:
    summary = summary_of(graph)
    folded = (summary.name, summary.description, *summary.tags)
    return IndexEntry(summary, tuple(text.casefold() for text in folded))


def matches(entry: IndexEntry, term: str | None, tag: str | None) -> bool:
    """``term`` is a case-insensitive substring of name/description/a tag; ``tag`` is exact."""
    if tag and tag not in entry.summary.tags:
        return False
    if term is None:
        return True
    needle = term.casefold()
    return any(needle in text for text in entry.folded)


class DirectoryIndex:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._signatures: dict[str, Signature] = {}
        self._entries: dict[str, IndexEntry] = {}

    def _scan(self) -> dict[str, Signature]:
        try:
            with os.scandir(self._dir) as items:
                candidates = [item for item in items if _FILE_RE.fullmatch(item.name)]
        except OSError as exc:
            raise StorageError("The graphs directory cannot be listed") from exc
        found: dict[str, Signature] = {}
        for item in candidates:
            signature = _signature(item)
            if signature is not None:
                found[item.name.removesuffix(GRAPH_SUFFIX)] = signature
        return found

    def _load(self, graph_id: str) -> IndexEntry | None:
        try:
            return entry_of(read_graph(self._dir / graph_filename(graph_id)))
        except FileNotFoundError:
            return None
        except StorageError:
            logger.warning("Skipping unreadable stored graph %s", graph_id)
            return None

    def refresh(self) -> None:
        """Bring the index in line with the directory (re-reads only what changed)."""
        found = self._scan()
        for graph_id in [known for known in self._signatures if known not in found]:
            del self._signatures[graph_id]
            self._entries.pop(graph_id, None)
        for graph_id, signature in found.items():
            if self._signatures.get(graph_id) == signature:
                continue
            self._signatures[graph_id] = signature
            entry = self._load(graph_id)
            if entry is None:
                self._entries.pop(graph_id, None)
            else:
                self._entries[graph_id] = entry

    def remember(self, graph: GraphDefinition) -> None:
        """Write-through after the repository stored ``graph``."""
        info = (self._dir / graph_filename(graph.id)).stat()
        self._signatures[graph.id] = (info.st_mtime_ns, info.st_size, info.st_ino)
        self._entries[graph.id] = entry_of(graph)

    def select(self, term: str | None, tag: str | None) -> list[GraphSummary]:
        """Matching summaries in listing order: ``updated_at`` descending, then id ascending."""
        self.refresh()
        chosen = [e.summary for e in self._entries.values() if matches(e, term, tag)]
        chosen.sort(key=lambda summary: summary.id)
        # reverse=True keeps the order of equal keys, so timestamp ties stay in id order
        chosen.sort(key=lambda summary: summary.updated_at, reverse=True)
        return chosen

    def unreadable(self) -> list[str]:
        """Ids (sorted) of graph files that exist but cannot be read: damaged or too new."""
        self.refresh()
        return sorted(self._signatures.keys() - self._entries.keys())

    def tags(self) -> list[str]:
        self.refresh()
        return sorted({tag for entry in self._entries.values() for tag in entry.summary.tags})
