# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The process-wide registry of per-directory state."""

from __future__ import annotations

import gc
import threading
import weakref
from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.storage import FileGraphRepository
from sankey_studio.storage.files.folder_file import FOLDERS_FILENAME, FolderFile
from sankey_studio.storage.files.index import DirectoryIndex
from sankey_studio.storage.files.locks import DirState, dir_state, open_state
from tests.storage.folder_builders import folder
from tests.storage.support import ID_A, Reads, definition, mode_of

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


def test_a_state_also_holds_the_folders_file_of_its_directory(tmp_path: Path) -> None:
    state = dir_state(tmp_path)
    assert isinstance(state.tree, FolderFile)
    assert state.tree.read() == []
    state.tree.save([folder(1, "a")])
    assert (tmp_path / FOLDERS_FILENAME).is_file()
    assert [item.name for item in dir_state(tmp_path).tree.read()] == ["a"]


def test_store_writes_the_graph_file_and_the_index_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = dir_state(tmp_path)
    graph = definition(ID_A, "stored")
    state.store(graph)
    reads = Reads(monkeypatch)
    assert [row.id for row in state.index.select(None, None)] == [ID_A]
    assert (tmp_path / f"{ID_A}.json").is_file()
    assert mode_of(tmp_path / f"{ID_A}.json") == 0o600
    assert reads.paths == []  # the index was written through, nothing was parsed again


def test_open_state_prepares_a_private_directory_and_shares_the_state(tmp_path: Path) -> None:
    target = tmp_path / "a" / "graphs"
    state = open_state(target)
    assert target.is_dir()
    assert mode_of(target) == 0o700
    assert open_state(target) is state
    assert dir_state(target) is state


def test_open_state_of_an_unusable_path_is_a_storage_error(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x")
    with pytest.raises(StorageError) as info:
        open_state(tmp_path / "file" / "graphs")
    assert info.value.message.startswith("The graphs directory is not usable: ")
