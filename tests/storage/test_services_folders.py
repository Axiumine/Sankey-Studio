"""``Services.folders()``, the ``Stores`` pair, the storage probe and the migration of folders."""

from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError, dataclass
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

import pytest

from sankey_studio.config import BootstrapConfig
from sankey_studio.errors import StorageError
from sankey_studio.models import AppSettings, GraphDefinition
from sankey_studio.services import Services
from sankey_studio.storage import (
    CopyReport,
    FileFolderRepository,
    FileGraphRepository,
    MongoFolderRepository,
    MongoGraphRepository,
    Stores,
)
from sankey_studio.storage.base import MONGO_FOLDERS_COLLECTION, MONGO_GRAPHS_COLLECTION
from tests.conftest import build_connection
from tests.storage.folder_builders import body, fid, folder
from tests.storage.mongo_fakes import Hub
from tests.storage.support import ID_A, ID_B, definition

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

URI = "mongodb://a-user:a-pass@good-a.invalid:27017/?appName=t"
DB = "sankey_studio"


@dataclass(slots=True)
class Env:
    services: Services
    hub: Hub
    config: BootstrapConfig


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    config = BootstrapConfig(data_dir=tmp_path / "data")
    hub = Hub()
    services = Services.create(config, mongo_factory=hub)
    yield Env(services, hub, config)
    services.close()


def _settings(
    *,
    backend: Literal["file", "mongo"] = "file",
    connection: str | None = None,
    database: str = DB,
) -> AppSettings:
    """Two connections (a, b); the library store as asked."""
    return AppSettings(
        mongo_connections=[build_connection("a", URI), build_connection("b", URI)],
        storage_backend=backend,
        storage_connection=connection,
        storage_database=database,
    )


def _mongo(connection: str = "a", database: str = DB) -> AppSettings:
    return _settings(backend="mongo", connection=connection, database=database)


# --------------------------------------------------------------------------- the cached repository


def test_the_file_backend_is_the_default_and_the_instance_is_cached(env: Env) -> None:
    folders = env.services.folders()
    assert isinstance(folders, FileFolderRepository)
    assert env.services.folders() is folders
    folders.create_folder(body("box"))
    assert (env.config.graphs_dir / "folders.json").is_file()


def test_graphs_and_folders_of_one_directory_work_together(env: Env) -> None:
    box = env.services.folders().create_folder(body("box"))
    graph = env.services.graphs().put(definition(ID_A, "g"))
    env.services.folders().move_graphs([graph.id], box.id)
    assert env.services.graphs().get(ID_A).folder_id == box.id
    assert [g.id for g in env.services.folders().list_in(box.id)] == [ID_A]
    assert [(f.id, f.graph_count) for f in env.services.folders().list_folders()] == [(box.id, 1)]


def test_an_unrelated_settings_change_keeps_both_instances(env: Env) -> None:
    graphs, folders = env.services.graphs(), env.services.folders()
    env.services.update_settings(AppSettings(theme="dark", max_links=500))
    assert env.services.graphs() is graphs
    assert env.services.folders() is folders


class Change(NamedTuple):
    label: str
    before: AppSettings
    after: AppSettings


CHANGES = [
    Change("backend", _mongo("a"), _settings(backend="file", connection="a")),
    Change("connection", _mongo("a"), _mongo("b")),
    Change("database", _mongo("a", "one"), _mongo("a", "two")),
]


@pytest.mark.parametrize("case", CHANGES, ids=[c.label for c in CHANGES])
def test_every_component_of_the_key_rebuilds_the_folders_with_the_graphs(
    env: Env, case: Change
) -> None:
    env.services.update_settings(case.before)
    graphs, folders = env.services.graphs(), env.services.folders()
    assert env.services.folders() is folders
    env.services.update_settings(case.after)
    assert env.services.graphs() is not graphs
    new_folders = env.services.folders()
    assert new_folders is not folders
    assert env.services.folders() is new_folders


def test_each_accessor_is_cached_on_its_own(env: Env) -> None:
    """Asking for the graphs does not rebuild the folders and the other way round."""
    folders = env.services.folders()
    env.services.graphs()
    env.services.graphs()
    assert env.services.folders() is folders
    graphs = env.services.graphs()
    env.services.folders()
    assert env.services.graphs() is graphs


def test_the_resolved_graphs_directory_is_part_of_the_key(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = env.services.folders()
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setattr(BootstrapConfig, "graphs_dir", property(lambda _self: elsewhere))
    second = env.services.folders()
    assert second is not first
    assert isinstance(second, FileFolderRepository)
    assert env.services.folders() is second
    monkeypatch.undo()
    assert env.services.folders() is not second


def test_a_symlinked_graphs_directory_resolves_to_the_same_key(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = env.services.folders()
    link = tmp_path / "link"
    link.symlink_to(env.config.graphs_dir)
    monkeypatch.setattr(BootstrapConfig, "graphs_dir", property(lambda _self: link))
    assert env.services.folders() is first


def test_the_mongo_backend_gets_a_mongo_folder_repository_on_the_shared_clients(env: Env) -> None:
    env.services.update_settings(_mongo("b", "mine"))
    repo = env.services.folders()
    assert isinstance(repo, MongoFolderRepository)
    assert repo._clients is env.services.mongo
    target = repo._target
    assert (target.connection, target.database) == ("b", "mine")
    assert target.folders_collection == MONGO_FOLDERS_COLLECTION
    assert target.collection == MONGO_GRAPHS_COLLECTION


def test_concurrent_callers_share_one_folder_repository(env: Env) -> None:
    barrier = threading.Barrier(20)
    seen: list[object] = []

    def work() -> None:
        barrier.wait()
        seen.append(env.services.folders())

    threads = [threading.Thread(target=work) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(seen) == 20
    assert len({id(r) for r in seen}) == 1


def test_a_failing_build_is_not_cached(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory should be")
    monkeypatch.setattr(BootstrapConfig, "graphs_dir", property(lambda _self: blocker))
    with pytest.raises(StorageError, match="The graphs directory is not usable"):
        env.services.folders()
    monkeypatch.undo()
    assert isinstance(env.services.folders(), FileFolderRepository)


# --------------------------------------------------------------------------- the pair


def test_a_candidate_is_a_pair_of_repositories_on_the_candidate_settings(env: Env) -> None:
    with env.services._candidate(_settings()) as files:
        assert isinstance(files, Stores)
        assert isinstance(files.graphs, FileGraphRepository)
        assert isinstance(files.folders, FileFolderRepository)
    with env.services._candidate(_mongo("a", "mine")) as mongo:
        assert isinstance(mongo.graphs, MongoGraphRepository)
        assert isinstance(mongo.folders, MongoFolderRepository)
        assert mongo.graphs._target == mongo.folders._target
        assert mongo.folders._clients is not env.services.mongo  # clients of its own
    assert env.hub.open() == []  # the candidate's client is closed again


class Spy:
    """A repository whose ``ping`` records itself (and may fail)."""

    def __init__(self, name: str, log: list[str], error: Exception | None = None) -> None:
        self._name = name
        self._log = log
        self._error = error

    def ping(self) -> None:
        self._log.append(self._name)
        if self._error is not None:
            raise self._error


def test_a_pair_pings_the_graphs_first_and_then_the_folders() -> None:
    log: list[str] = []
    Stores(Spy("graphs", log), Spy("folders", log)).ping()  # type: ignore[arg-type]
    assert log == ["graphs", "folders"]


def test_a_failing_graph_ping_stops_before_the_folders_are_asked() -> None:
    log: list[str] = []
    stores = Stores(Spy("graphs", log, StorageError("g")), Spy("folders", log))  # type: ignore[arg-type]
    with pytest.raises(StorageError, match="g"):
        stores.ping()
    assert log == ["graphs"]


def test_a_failing_folder_ping_is_reported_to_the_caller() -> None:
    log: list[str] = []
    stores = Stores(Spy("graphs", log), Spy("folders", log, StorageError("f")))  # type: ignore[arg-type]
    with pytest.raises(StorageError, match="f"):
        stores.ping()
    assert log == ["graphs", "folders"]


def test_the_pair_is_a_frozen_value() -> None:
    stores = Stores(Spy("g", []), Spy("f", []))  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        stores.graphs = Spy("x", [])  # type: ignore[misc,assignment]
    assert stores == Stores(stores.graphs, stores.folders)


# --------------------------------------------------------------------------- the probe


def _indexes(env: Env, collection: str) -> list[list[tuple[str, int]]]:
    info = env.hub.server[DB][collection].index_information()
    return [spec["key"] for spec in info.values()]


def test_testing_a_mongo_target_probes_both_collections(env: Env) -> None:
    env.services.test_storage(_mongo("a"))
    assert [("parent_id", 1), ("name_key", 1)] in _indexes(env, MONGO_FOLDERS_COLLECTION)
    assert [("folder_id", 1)] in _indexes(env, MONGO_GRAPHS_COLLECTION)
    assert env.hub.open() == []


def test_a_folder_collection_that_cannot_be_written_fails_the_probe(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(_self: object) -> None:
        raise StorageError("MongoDB connection 'a' is not authorised")

    monkeypatch.setattr(MongoFolderRepository, "ping", refused)
    with pytest.raises(StorageError, match="is not authorised"):
        env.services.test_storage(_mongo("a"))
    assert env.hub.open() == []


def test_testing_a_file_target_pings_the_directory_once_for_the_pair(env: Env) -> None:
    env.services.test_storage(_settings())
    assert env.config.graphs_dir.is_dir()
    assert not (env.config.graphs_dir / "folders.json").exists()  # a probe saves nothing


# --------------------------------------------------------------------------- migration


def _seed(env: Env) -> list[GraphDefinition]:
    folders, graphs = env.services.folders(), env.services.graphs()
    folders.put_folder(folder(1, "Work"))
    folders.put_folder(folder(2, "Q3", 1))
    seeded = [
        GraphDefinition.model_validate({**definition(ID_A, "a").model_dump(), "folder_id": fid(2)}),
        definition(ID_B, "b"),
    ]
    for graph in seeded:
        graphs.put(graph)
    return seeded


def test_switching_to_mongo_with_migrate_copies_the_folders_and_their_graphs(env: Env) -> None:
    seeded = _seed(env)
    result = env.services.update_settings(_mongo("a"), migrate=True)
    assert result.copy_report == CopyReport(copied=2, skipped=0, folders=2, folders_skipped=0)
    graphs, folders = env.services.graphs(), env.services.folders()
    assert isinstance(folders, MongoFolderRepository)
    assert list(graphs.iter_definitions()) == sorted(seeded, key=lambda g: g.id)
    assert [f.name for f in folders.list_definitions()] == ["Q3", "Work"]
    assert [g.id for g in folders.list_in(fid(2))] == [ID_A]
    assert [g.id for g in folders.list_in("root")] == [ID_B]


def test_switching_back_to_files_copies_the_folders_too(env: Env) -> None:
    env.services.update_settings(_mongo("a"))
    folders = env.services.folders()
    folders.put_folder(folder(1, "Work"))
    env.services.graphs().put(
        GraphDefinition.model_validate({**definition(ID_A, "a").model_dump(), "folder_id": fid(1)})
    )
    result = env.services.update_settings(_settings(backend="file", connection="a"), migrate=True)
    assert result.copy_report == CopyReport(copied=1, skipped=0, folders=1, folders_skipped=0)
    assert [g.id for g in env.services.folders().list_in(fid(1))] == [ID_A]
    assert (env.config.graphs_dir / "folders.json").is_file()


def test_a_folder_the_destination_already_has_is_counted_in_the_report(env: Env) -> None:
    _seed(env)
    env.services.update_settings(_mongo("a"), migrate=True)
    env.services.update_settings(_settings(backend="file", connection="a"))
    result = env.services.update_settings(_mongo("a"), migrate=True)
    assert result.copy_report == CopyReport(copied=0, skipped=2, folders=0, folders_skipped=2)


def test_switching_without_migrate_copies_nothing_and_reports_nothing(env: Env) -> None:
    _seed(env)
    result = env.services.update_settings(_mongo("a"))
    assert result.copy_report is None
    assert env.hub.server[DB][MONGO_FOLDERS_COLLECTION].count_documents({}) == 0
    assert env.services.folders().list_folders() == []


def test_a_failing_copy_leaves_the_settings_alone(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(env)

    def broken(_self: object, _folder: object, **_kwargs: Any) -> None:
        raise StorageError("connection lost")

    monkeypatch.setattr(MongoFolderRepository, "put_folder", broken)
    with pytest.raises(StorageError, match="connection lost"):
        env.services.update_settings(_mongo("a"), migrate=True)
    assert env.services.settings().storage_backend == "file"
    assert isinstance(env.services.folders(), FileFolderRepository)
    assert len(env.services.folders().list_folders()) == 2
