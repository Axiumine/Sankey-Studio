"""Process-wide state per graphs directory: ONE lock and ONE listing index.

Two ``FileGraphRepository`` instances on the same directory (for example after a settings change
rebuilt the repository while a request still held the old one) must exclude each other, so the
lock lives in a registry keyed by the resolved directory, not in the instance. The registry holds
weak references: the state disappears with its last repository.
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sankey_studio.storage.files.index import DirectoryIndex

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(eq=False)
class DirState:
    """Shared by every repository of one directory. Hold ``lock`` for any read-modify-write."""

    directory: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    index: DirectoryIndex = field(init=False)

    def __post_init__(self) -> None:
        self.index = DirectoryIndex(self.directory)


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
