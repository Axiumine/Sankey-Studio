# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Process-wide state per graphs directory: ONE lock, ONE listing index and the folders file.

Two ``FileGraphRepository`` instances on the same directory (for example after a settings change
rebuilt the repository while a request still held the old one) must exclude each other, so the
lock lives in a registry keyed by the resolved directory, not in the instance. The registry holds
weak references: the state disappears with its last repository.

The folder repository shares this state with the graph repository: moving a graph into a folder
and creating a graph both write graph files under the same lock and through ``DirState.store``.
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sankey_studio.errors import StorageError
from sankey_studio.storage.atomic import ensure_private_dir, os_reason, write_atomic
from sankey_studio.storage.files.codec import encode_graph, graph_filename
from sankey_studio.storage.files.folder_file import FolderFile
from sankey_studio.storage.files.index import DirectoryIndex

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.models import GraphDefinition


@dataclass(eq=False)
class DirState:
    """Shared by every repository of one directory. Hold ``lock`` for any read-modify-write."""

    directory: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    index: DirectoryIndex = field(init=False)
    tree: FolderFile = field(init=False)

    def __post_init__(self) -> None:
        self.index = DirectoryIndex(self.directory)
        self.tree = FolderFile(self.directory)

    def store(self, graph: GraphDefinition) -> None:
        """Write ``graph`` and its index entry. The caller holds ``lock``."""
        try:
            write_atomic(self.directory / graph_filename(graph.id), encode_graph(graph))
            self.index.remember(graph)
        except OSError as exc:
            raise StorageError(f"The graph could not be saved: {os_reason(exc)}") from exc


_REGISTRY_LOCK = threading.Lock()
_STATES: weakref.WeakValueDictionary[Path, DirState] = weakref.WeakValueDictionary()


def dir_state(graphs_dir: Path) -> DirState:
    key = graphs_dir.resolve()
    with _REGISTRY_LOCK:
        state = _STATES.get(key)
        if state is None:
            state = DirState(key)
            _STATES[key] = state
        return state


def open_state(graphs_dir: Path) -> DirState:
    """Make sure ``graphs_dir`` is a private directory, then return its shared state."""
    try:
        ensure_private_dir(graphs_dir)
    except OSError as exc:
        raise StorageError(f"The graphs directory is not usable: {os_reason(exc)}") from exc
    return dir_state(graphs_dir)
