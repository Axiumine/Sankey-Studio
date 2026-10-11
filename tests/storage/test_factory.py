"""``make_graph_repository`` and ``storage_target``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.models import AppSettings
from sankey_studio.storage import (
    FileGraphRepository,
    MongoGraphRepository,
    MongoStoreTarget,
    make_graph_repository,
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
