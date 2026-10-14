"""Fixtures for the storage tests: both repository backends behind one interface."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.storage import (
    FileGraphRepository,
    MongoFolderRepository,
    MongoGraphRepository,
    MongoStoreTarget,
)
from sankey_studio.storage.base import MONGO_GRAPHS_COLLECTION
from sankey_studio.storage.files import FileFolderRepository
from tests.storage.support import Ticker

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient
    from pymongo.collection import Collection

    from sankey_studio.mongo import MongoClients
    from sankey_studio.storage.base import GraphRepository
    from sankey_studio.storage.folders_base import FolderRepository

STORE_DATABASE = "sankey_studio"
STORE_TARGET = MongoStoreTarget("test", STORE_DATABASE)


@dataclass(slots=True)
class RepoEnv:
    """One repository plus the handles a test needs to look behind it."""

    kind: str
    repo: GraphRepository
    clock: Ticker


def _unlock(path: Path) -> None:
    """Give the owner full access again, so pytest can always delete the temporary tree."""
    if path.is_symlink() or not path.is_dir():
        return
    path.chmod(0o700)
    for child in path.iterdir():
        _unlock(child)


@pytest.fixture(autouse=True)
def _removable_tmp(tmp_path: Path) -> Iterator[None]:
    """Tests here chmod directories; a failing (or mutated) test must not leave a locked tree."""
    yield
    with contextlib.suppress(OSError):
        _unlock(tmp_path)


@pytest.fixture
def clock() -> Ticker:
    return Ticker()


@pytest.fixture
def mongo_collection(mongo_client: MongoClient[Any]) -> Collection[Any]:
    """The raw graph collection of the in-memory server (what a real server would hold)."""
    return mongo_client[STORE_DATABASE][MONGO_GRAPHS_COLLECTION]


@pytest.fixture
def mongo_repo(mongo_clients: MongoClients, clock: Ticker) -> MongoGraphRepository:
    return MongoGraphRepository(mongo_clients, STORE_TARGET, clock=clock)


@pytest.fixture
def file_repo(tmp_path: Path, clock: Ticker) -> FileGraphRepository:
    return FileGraphRepository(tmp_path / "graphs", clock=clock)


@pytest.fixture(params=["file", "mongo"])
def env(
    request: pytest.FixtureRequest,
    file_repo: FileGraphRepository,
    mongo_repo: MongoGraphRepository,
    clock: Ticker,
) -> RepoEnv:
    """Every shared behaviour test runs once per backend."""
    repo: GraphRepository = file_repo if request.param == "file" else mongo_repo
    return RepoEnv(request.param, repo, clock)


@dataclass(slots=True)
class FolderEnv:
    """A folder repository and the graph repository that shares its store."""

    kind: str
    folders: FolderRepository
    graphs: GraphRepository
    clock: Ticker


@pytest.fixture
def file_folders(tmp_path: Path, clock: Ticker) -> FileFolderRepository:
    """Folders of the SAME directory (lock, index) as the ``file_repo`` fixture."""
    return FileFolderRepository(tmp_path / "graphs", clock=clock)


@pytest.fixture
def mongo_folders(mongo_clients: MongoClients, clock: Ticker) -> MongoFolderRepository:
    """Folders of the SAME database as the ``mongo_repo`` fixture (graphs and folders)."""
    return MongoFolderRepository(mongo_clients, STORE_TARGET, clock=clock)


@pytest.fixture(params=["file", "mongo"])
def folder_env(
    request: pytest.FixtureRequest,
    clock: Ticker,
) -> FolderEnv:
    """Every shared folder test runs once per backend, each with the graph repository it shares."""
    if request.param == "file":
        graphs: GraphRepository = request.getfixturevalue("file_repo")
        folders: FolderRepository = request.getfixturevalue("file_folders")
    else:
        graphs = request.getfixturevalue("mongo_repo")
        folders = request.getfixturevalue("mongo_folders")
    return FolderEnv(str(request.param), folders, graphs, clock)
