"""The process-wide registry of per-directory state."""

from __future__ import annotations

import gc
import threading
import weakref
from typing import TYPE_CHECKING

from sankey_studio.storage import FileGraphRepository
from sankey_studio.storage.files.index import DirectoryIndex
from sankey_studio.storage.files.locks import DirState, dir_state

if TYPE_CHECKING:
    from pathlib import Path


def test_one_state_per_resolved_directory(tmp_path: Path) -> None:
    (tmp_path / "graphs").mkdir()
    (tmp_path / "other").mkdir()
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "graphs")
    first = dir_state(tmp_path / "graphs")
    assert dir_state(tmp_path / "graphs") is first
    assert dir_state(tmp_path / "graphs" / ".." / "graphs") is first
    assert dir_state(link) is first  # the key is the resolved path
    assert dir_state(tmp_path / "other") is not first


def test_a_state_holds_a_lock_and_an_index_of_the_resolved_directory(tmp_path: Path) -> None:
    state = dir_state(tmp_path)
    assert isinstance(state, DirState)
    assert state.directory == tmp_path.resolve()
    assert isinstance(state.index, DirectoryIndex)
    assert state.lock.acquire(blocking=False)
    assert not state.lock.acquire(blocking=False)
    state.lock.release()
    assert type(state.lock) is type(threading.Lock())


def test_two_repositories_of_one_directory_share_their_state(tmp_path: Path) -> None:
    one = FileGraphRepository(tmp_path / "graphs")
    two = FileGraphRepository(tmp_path / "graphs")
    assert one._state is two._state
    assert one._state.lock is two._state.lock


def test_the_state_goes_away_with_its_last_repository(tmp_path: Path) -> None:
    repo = FileGraphRepository(tmp_path / "graphs")
    ref = weakref.ref(repo._state)
    assert ref() is not None
    del repo
    gc.collect()
    assert ref() is None
    assert dir_state(tmp_path / "graphs") is not None  # a fresh one is simply built
