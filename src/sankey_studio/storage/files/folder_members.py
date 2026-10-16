# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Which graph files sit in which library folder, and moving them (file backend).

Plain functions over a ``DirState``. The listings take its lock for one consistent look; the
writers take it PER GRAPH (re-parenting a thousand graphs must not freeze the app for a thousand
fsynced writes), so callers must NOT hold the lock when they call them.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sankey_studio.errors import NotFoundError, StorageError
from sankey_studio.models import GraphDefinition
from sankey_studio.storage.base import check_graph_id
from sankey_studio.storage.files.codec import graph_filename, read_graph
from sankey_studio.storage.folder_tree import effective

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.models import FolderDefinition, GraphSummary
    from sankey_studio.storage.files.locks import DirState

logger = logging.getLogger(__name__)


def snapshot(state: DirState) -> tuple[list[FolderDefinition], list[GraphSummary]]:
    """The folders and the graph rows (listing order) as they are at one instant."""
    with state.lock:
        return state.tree.read(), state.index.select(None, None)


def graph_counts(
    folders: list[FolderDefinition], rows: list[GraphSummary]
) -> dict[str | None, int]:
    """Graphs per EFFECTIVE folder id (``None`` = the top level, dangling ids included)."""
    known = {folder.id for folder in folders}
    counts: dict[str | None, int] = {}
    for row in rows:
        key = effective(row.folder_id, known)
        counts[key] = counts.get(key, 0) + 1
    return counts


def graphs_in(
    folders: list[FolderDefinition], rows: list[GraphSummary], scope: str | None
) -> list[GraphSummary]:
    """The rows whose effective folder is ``scope`` (``None`` = the top level), listing order."""
    known = {folder.id for folder in folders}
    return [row for row in rows if effective(row.folder_id, known) == scope]


def _readable(state: DirState, graph_id: str) -> GraphDefinition | None:
    """The stored graph, or ``None`` when the id is malformed, the file vanished or is damaged."""
    try:
        return read_graph(state.directory / graph_filename(check_graph_id(graph_id)))
    except NotFoundError, FileNotFoundError:
        return None
    except StorageError:
        logger.warning("Skipping unreadable stored graph %s", graph_id)
        return None


def _set_folder(
    state: DirState, graph_id: str, target: str | None, accept: Callable[[str | None], bool]
) -> bool:
    """Rewrite one graph with ``folder_id=target`` when ``accept(current folder id)``.

    ``False`` when there is no readable graph with this id. Nothing else of the graph changes: not
    its revision, not ``updated_at`` (a move is not an edit of the graph).
    """
    with state.lock:
        graph = _readable(state, graph_id)
        if graph is None:
            return False
        if graph.folder_id != target and accept(graph.folder_id):
            state.store(GraphDefinition.model_validate({**graph.model_dump(), "folder_id": target}))
    return True


def assign(state: DirState, graph_id: str, target: str | None) -> bool:
    """Put the graph in ``target``; ``False`` when it does not exist."""
    return _set_folder(state, graph_id, target, lambda _current: True)


def move_up(state: DirState, graph_id: str, source: str, target: str | None) -> None:
    """Move the graph from ``source`` to ``target``; a graph that is elsewhere by now stays."""
    _set_folder(state, graph_id, target, lambda current: current == source)


def ids_in(state: DirState, folder_id: str) -> list[str]:
    """The ids of the graphs that name ``folder_id`` directly (listing order)."""
    with state.lock:
        return [row.id for row in state.index.select(None, None) if row.folder_id == folder_id]
