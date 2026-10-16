# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``FileGraphRepository``: one atomically written ``<id>.json`` per graph.

The revision compare and the write run inside ONE critical section on the lock of the (resolved)
directory, shared by every repository instance of that directory (``locks.py``). Locking is per
process, so run ONE uvicorn worker.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from sankey_studio.errors import NotFoundError, StorageError
from sankey_studio.storage.atomic import check_writable, fsync_dir, os_reason
from sankey_studio.storage.base import check_graph_id
from sankey_studio.storage.common import (
    Clock,
    clamp_page,
    exists_error,
    new_definition,
    revised_definition,
    search_term,
    stale_error,
    utc_now,
)
from sankey_studio.storage.files.codec import graph_filename, read_graph
from sankey_studio.storage.files.locks import DirState, open_state

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sankey_studio.models import (
        GraphCreate,
        GraphDefinition,
        GraphSummary,
        GraphUpdate,
    )

logger = logging.getLogger(__name__)

MSG_NOT_FOUND = "Graph not found"


class FileGraphRepository:
    def __init__(self, graphs_dir: Path, *, clock: Clock = utc_now) -> None:
        self._state: DirState = open_state(graphs_dir)
        self._dir = self._state.directory
        self._clock = clock

    def _path(self, graph_id: str) -> Path:
        return self._dir / graph_filename(check_graph_id(graph_id))

    # ------------------------------------------------------------------ reads

    def list_graphs(
        self,
        *,
        query: str | None = None,
        tag: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[GraphSummary]:
        size, start = clamp_page(limit, offset)
        with self._state.lock:
            rows = self._state.index.select(search_term(query), tag)
        return rows[start : start + size]

    def count(self, *, query: str | None = None, tag: str | None = None) -> int:
        with self._state.lock:
            return len(self._state.index.select(search_term(query), tag))

    def all_tags(self) -> list[str]:
        with self._state.lock:
            return self._state.index.tags()

    def get(self, graph_id: str) -> GraphDefinition:
        try:
            return read_graph(self._path(graph_id))
        except FileNotFoundError:
            raise NotFoundError(MSG_NOT_FOUND) from None

    def _readable(self, graph_id: str) -> GraphDefinition | None:
        """The stored graph, or ``None`` when it vanished or is unreadable (logged)."""
        try:
            return self.get(graph_id)
        except NotFoundError:
            return None
        except StorageError:
            logger.warning("Skipping unreadable stored graph %s", graph_id)
            return None

    def iter_definitions(self) -> Iterator[GraphDefinition]:
        with self._state.lock:
            ids = [summary.id for summary in self._state.index.select(None, None)]
        for graph_id in ids:
            graph = self._readable(graph_id)
            if graph is not None:
                yield graph

    def unreadable_ids(self) -> list[str]:
        with self._state.lock:
            return self._state.index.unreadable()

    # ------------------------------------------------------------------ writes

    def create(self, data: GraphCreate, *, folder_id: str | None = None) -> GraphDefinition:
        graph = new_definition(data, self._clock(), folder_id)
        with self._state.lock:
            self._state.store(graph)
        return graph

    def update(self, graph_id: str, data: GraphUpdate) -> GraphDefinition:
        with self._state.lock:
            current = self.get(graph_id)
            if current.revision != data.revision:
                raise stale_error(current.revision, current.updated_at)
            graph = revised_definition(current, data, self._clock())
            self._state.store(graph)
        return graph

    def put(self, graph: GraphDefinition, *, overwrite: bool = False) -> GraphDefinition:
        path = self._path(graph.id)
        with self._state.lock:
            if not overwrite and os.path.lexists(path):
                found = self._readable(graph.id)
                raise exists_error(
                    found.revision if found else None, found.updated_at if found else None
                )
            self._state.store(graph)
        return graph

    def delete(self, graph_id: str) -> None:
        path = self._path(graph_id)
        with self._state.lock:
            try:
                path.unlink()
                fsync_dir(self._dir)
            except FileNotFoundError:
                raise NotFoundError(MSG_NOT_FOUND) from None
            except OSError as exc:
                raise StorageError(f"The graph could not be deleted: {os_reason(exc)}") from exc

    def ping(self) -> None:
        try:
            check_writable(self._dir)
        except OSError as exc:
            raise StorageError(f"The graphs directory is not writable: {os_reason(exc)}") from exc
