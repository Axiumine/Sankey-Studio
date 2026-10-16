# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``make_graph_repository``, ``make_folder_repository``, ``make_stores`` and ``storage_target``."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.models import AppSettings, FolderCreate
from sankey_studio.storage import (
    FileFolderRepository,
    FileGraphRepository,
    MongoFolderRepository,
    MongoGraphRepository,
    MongoStoreTarget,
    Stores,
    make_folder_repository,
    make_graph_repository,
    make_stores,
    storage_target,
)
from tests.conftest import build_connection
from tests.storage.support import ID_A, config_for, definition

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.mongo import MongoClients


def _mongo_settings(connection: str = "test", database: str = "sankey_studio") -> AppSettings:
    return AppSettings(
        storage_backend="mongo",
        storage_connection=connection,
        storage_database=database,
        mongo_connections=[build_connection("test"), build_connection("other")],
    )


def test_the_file_backend_uses_the_graphs_directory_of_the_config(
    tmp_path: Path, mongo_clients: MongoClients
) -> None:
    config = config_for(tmp_path)
    repo = make_graph_repository(AppSettings(), mongo_clients, config)
    assert isinstance(repo, FileGraphRepository)
    repo.put(definition(ID_A, "g"))
    assert (config.data_dir / "graphs" / f"{ID_A}.json").is_file()


def test_the_mongo_backend_targets_the_selected_connection_and_database(
    tmp_path: Path, mongo_clients: MongoClients
) -> None:
    settings = _mongo_settings("other", "my_graphs")
    repo = make_graph_repository(settings, mongo_clients, config_for(tmp_path))
    assert isinstance(repo, MongoGraphRepository)
    assert repo._target == MongoStoreTarget("other", "my_graphs")
    assert repo._clients is mongo_clients
    assert not (tmp_path / "data").exists()  # no graphs directory for the Mongo backend


def test_the_target_is_read_from_the_settings() -> None:
    target = storage_target(_mongo_settings("other", "db2"))
    assert target == MongoStoreTarget("other", "db2", "sankey_studio_graphs")
    assert target.folders_collection == "sankey_studio_collections"


def test_a_file_backend_with_a_leftover_connection_still_uses_files(
    tmp_path: Path, mongo_clients: MongoClients
) -> None:
    settings = AppSettings(
        storage_backend="file",
        storage_connection="test",
        mongo_connections=[build_connection("test")],
    )
    assert isinstance(
        make_graph_repository(settings, mongo_clients, config_for(tmp_path)), FileGraphRepository
    )


def test_without_a_connection_there_is_no_target() -> None:
    with pytest.raises(StorageError) as info:
        storage_target(AppSettings())
    assert info.value.message == "No storage connection is selected"


def test_the_file_backend_has_a_folder_repository_on_the_same_directory(
    tmp_path: Path, mongo_clients: MongoClients
) -> None:
    config = config_for(tmp_path)
    settings = AppSettings()
    folders = make_folder_repository(settings, mongo_clients, config)
    assert isinstance(folders, FileFolderRepository)
    graphs = make_graph_repository(settings, mongo_clients, config)
    assert folders._state is graphs._state  # type: ignore[attr-defined]  # one lock, one index
    folders.create_folder(FolderCreate(name="box"))
    assert (config.data_dir / "graphs" / "folders.json").is_file()


def test_the_mongo_backend_has_a_folder_repository_on_the_same_target(
    tmp_path: Path, mongo_clients: MongoClients
) -> None:
    settings = _mongo_settings("other", "my_graphs")
    config = config_for(tmp_path)
    folders = make_folder_repository(settings, mongo_clients, config)
    assert isinstance(folders, MongoFolderRepository)
    assert folders._target == MongoStoreTarget("other", "my_graphs")
    assert folders._clients is mongo_clients
    assert not (tmp_path / "data").exists()  # no graphs directory for the Mongo backend


def test_a_file_backend_with_a_leftover_connection_still_has_file_folders(
    tmp_path: Path, mongo_clients: MongoClients
) -> None:
    settings = AppSettings(
        storage_backend="file",
        storage_connection="test",
        mongo_connections=[build_connection("test")],
    )
    folders = make_folder_repository(settings, mongo_clients, config_for(tmp_path))
    assert isinstance(folders, FileFolderRepository)


def test_without_a_connection_there_is_no_folder_repository(
    tmp_path: Path, mongo_clients: MongoClients
) -> None:
    settings = AppSettings.model_construct(storage_backend="mongo", storage_connection=None)
    with pytest.raises(StorageError) as info:
        make_folder_repository(settings, mongo_clients, config_for(tmp_path))
    assert info.value.message == "No storage connection is selected"


class Backend(NamedTuple):
    settings: AppSettings
    graphs: type
    folders: type


BACKENDS = [
    Backend(AppSettings(), FileGraphRepository, FileFolderRepository),
    Backend(_mongo_settings(), MongoGraphRepository, MongoFolderRepository),
]


@pytest.mark.parametrize("case", BACKENDS, ids=["file", "mongo"])
def test_make_stores_builds_both_repositories_of_one_backend(
    tmp_path: Path, mongo_clients: MongoClients, case: Backend
) -> None:
    stores = make_stores(case.settings, mongo_clients, config_for(tmp_path))
    assert isinstance(stores, Stores)
    assert type(stores.graphs) is case.graphs
    assert type(stores.folders) is case.folders
