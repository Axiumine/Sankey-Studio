# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``Services.update_settings`` / ``test_storage``: storage switches that never lose data."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import pytest

from sankey_studio.config import BootstrapConfig
from sankey_studio.errors import (
    ReadOnlyModeError,
    SettingsError,
    SourceNotFoundError,
    StorageError,
)
from sankey_studio.models import AppSettings
from sankey_studio.services import Services
from sankey_studio.storage import (
    CopyReport,
    FileGraphRepository,
    MongoGraphRepository,
    SettingsStore,
)
from sankey_studio.storage import mongo_store as mongo_store_module
from tests.conftest import build_connection
from tests.storage.mongo_fakes import Hub
from tests.storage.support import (
    ID_A,
    ID_B,
    ID_C,
    OTHER_URI,
    SECRET_URI,
    Spec,
    definition,
    placeholder_settings,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sankey_studio.models import GraphDefinition

GOOD_A = "mongodb://a-user:a-pass@good-a.invalid:27017/?appName=t"
GOOD_B = "mongodb://b-user:b-pass@good-b.invalid:27017/?appName=t"
DEAD_URI = "mongodb://d-user:d-pass@dead.invalid:27017/?appName=t"
REFUSED_URI = "mongodb://r-user:r-pass@refused.invalid:27017/?appName=t"


@dataclass(slots=True)
class Env:
    services: Services
    hub: Hub
    config: BootstrapConfig


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    config = BootstrapConfig(data_dir=tmp_path / "data")
    hub = Hub()
    hub.dead.add("dead.invalid")
    hub.refused.add("refused.invalid")
    services = Services.create(config, mongo_factory=hub)
    yield Env(services, hub, config)
    services.close()


def _settings(
    *uris: tuple[str, str],
    backend: Literal["file", "mongo"] = "file",
    connection: str | None = None,
    **fields: Any,
) -> AppSettings:
    return AppSettings(
        mongo_connections=[build_connection(name, uri) for name, uri in uris],
        storage_backend=backend,
        storage_connection=connection,
        **fields,
    )


def _mongo_store(env: Env, connection: str = "a") -> MongoGraphRepository:
    """A repository on the destination of a switch (the hub's one shared in-memory server)."""
    from sankey_studio.mongo import MongoClients
    from sankey_studio.storage import MongoStoreTarget

    clients = MongoClients(env.services.settings, env.hub)
    return MongoGraphRepository(clients, MongoStoreTarget(connection, "sankey_studio"))


def _seed_files(env: Env) -> list[GraphDefinition]:
    repo = env.services.graphs()
    graphs = [definition(ID_A, "a", Spec(revision=3)), definition(ID_B, "b"), definition(ID_C, "c")]
    for graph in graphs:
        repo.put(graph)
    return graphs


def _on_disk(env: Env) -> AppSettings:
    return SettingsStore(env.config).load()


# --------------------------------------------------------------------------- plain updates


def test_a_plain_update_is_saved_and_reports_no_copy(env: Env) -> None:
    result = env.services.update_settings(_settings(theme="dark", max_links=500))
    assert result.copy_report is None
    assert (result.settings.theme, result.settings.max_links) == ("dark", 500)
    assert env.services.settings() == result.settings
    assert _on_disk(env) == result.settings
    assert env.hub.clients == []  # nothing was pinged or built


def test_the_secrets_reach_the_file_and_nothing_else(env: Env) -> None:
    env.services.update_settings(_settings(("a", SECRET_URI), ("b", OTHER_URI)))
    kept = json.loads(env.config.credentials_file.read_text())["mongo_connections"]
    assert {name: item["uri"] for name, item in kept.items()} == {"a": SECRET_URI, "b": OTHER_URI}
    public = json.loads(env.config.settings_file.read_text())["mongo_connections"]
    assert all("uri" not in conn for conn in public)


def test_an_invalid_candidate_is_refused_before_anything_changes(env: Env) -> None:
    good = env.services.update_settings(_settings(("a", GOOD_A), theme="dark")).settings
    with pytest.raises(SettingsError, match="Settings are invalid"):
        env.services.update_settings(placeholder_settings())
    assert env.services.settings() == good


def test_validation_comes_before_any_probe_of_the_destination(env: Env) -> None:
    broken = placeholder_settings().model_copy(
        update={"storage_backend": "mongo", "storage_connection": "a"}
    )
    with pytest.raises(SettingsError, match="Settings are invalid"):
        env.services.update_settings(broken, migrate=True)
    assert env.hub.clients == []  # nothing was built, pinged or copied
    assert not env.config.data_dir.exists()


# --------------------------------------------------------------------------- read-only mode


def test_remote_read_only_mode_refuses_the_update(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=tmp_path / "data", remote_mode=True)
    services = Services.create(config, mongo_factory=Hub())
    with pytest.raises(ReadOnlyModeError) as info:
        services.update_settings(AppSettings(theme="dark"))
    assert info.value.code == "read_only_mode"
    assert info.value.status_code == 403
    assert "read-only" in info.value.message
    assert not config.data_dir.exists()
    services.close()


def test_remote_mode_with_writes_allowed_updates_normally(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=tmp_path / "data", remote_mode=True, remote_writes=True)
    services = Services.create(config, mongo_factory=Hub())
    assert services.update_settings(AppSettings(theme="dark")).settings.theme == "dark"
    services.close()


# --------------------------------------------------------------------------- switching the store


def test_switching_to_mongo_without_migrating_leaves_the_files_alone(env: Env) -> None:
    graphs = _seed_files(env)
    result = env.services.update_settings(_settings(("a", GOOD_A), backend="mongo", connection="a"))
    assert result.copy_report is None
    repo = env.services.graphs()
    assert isinstance(repo, MongoGraphRepository)
    assert repo.count() == 0  # nothing was copied
    files = FileGraphRepository(env.config.graphs_dir)
    assert list(files.iter_definitions()) == graphs  # and nothing was deleted
    assert env.hub.open() == [GOOD_A]  # the probe's client is closed again; the live one is open


def test_migrating_copies_every_graph_verbatim_and_keeps_the_source(env: Env) -> None:
    graphs = _seed_files(env)
    result = env.services.update_settings(
        _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
    )
    assert result.copy_report == CopyReport(copied=3, skipped=0)
    assert list(env.services.graphs().iter_definitions()) == graphs
    assert list(FileGraphRepository(env.config.graphs_dir).iter_definitions()) == graphs
    assert _on_disk(env).storage_connection == "a"


def test_migrating_back_to_files_skips_what_is_already_there(env: Env) -> None:
    graphs = _seed_files(env)
    env.services.update_settings(
        _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
    )
    env.services.graphs().put(definition("d" * 32, "only in mongo"))
    result = env.services.update_settings(_settings(("a", GOOD_A)), migrate=True)
    assert result.copy_report == CopyReport(copied=1, skipped=3)
    files = FileGraphRepository(env.config.graphs_dir)
    assert {g.id for g in files.iter_definitions()} == {g.id for g in graphs} | {"d" * 32}


def test_migrating_an_empty_store_reports_zero(env: Env) -> None:
    result = env.services.update_settings(
        _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
    )
    assert result.copy_report == CopyReport(0, 0)


def test_unreadable_graphs_stay_behind_but_are_reported_and_the_switch_goes_through(
    env: Env,
) -> None:
    _seed_files(env)
    (env.config.graphs_dir / f"{'d' * 32}.json").write_bytes(b"{broken")
    newer = json.loads(definition("e" * 32, "future").model_dump_json())
    newer["schema_version"] = 99
    (env.config.graphs_dir / f"{'e' * 32}.json").write_text(json.dumps(newer))
    result = env.services.update_settings(
        _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
    )
    assert result.copy_report == CopyReport(
        copied=3, skipped=0, unreadable=2, unreadable_ids=("d" * 32, "e" * 32)
    )
    assert result.settings.storage_backend == "mongo"
    assert _on_disk(env).storage_backend == "mongo"
    assert _mongo_store(env).count() == 3
    assert (env.config.graphs_dir / f"{'d' * 32}.json").read_bytes() == b"{broken"  # kept


def test_migrate_without_a_target_change_does_nothing(env: Env) -> None:
    _seed_files(env)
    result = env.services.update_settings(_settings(theme="dark"), migrate=True)
    assert result.copy_report is None


def test_a_connection_added_in_the_same_update_can_be_the_destination(env: Env) -> None:
    with pytest.raises(SourceNotFoundError, match="Unknown MongoDB connection"):
        env.services.mongo.get("a")
    env.services.update_settings(
        _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
    )
    assert env.services.mongo.get("a") is not None


def test_changing_the_database_of_the_store_is_a_switch(env: Env) -> None:
    env.services.update_settings(_settings(("a", GOOD_A), backend="mongo", connection="a"))
    env.services.graphs().put(definition(ID_A, "in first db"))
    result = env.services.update_settings(
        _settings(("a", GOOD_A), backend="mongo", connection="a", storage_database="second"),
        migrate=True,
    )
    assert result.copy_report == CopyReport(copied=1, skipped=0)
    assert env.services.graphs().get(ID_A).name == "in first db"


def test_editing_the_uri_of_the_storage_connection_is_a_switch_too(env: Env) -> None:
    env.services.update_settings(_settings(("a", GOOD_A), backend="mongo", connection="a"))
    pinged = len(env.hub.clients)
    env.services.update_settings(_settings(("a", GOOD_B), backend="mongo", connection="a"))
    assert len(env.hub.clients) > pinged  # a probe client was built for the new URI
    with pytest.raises(StorageError, match="is unreachable"):
        env.services.update_settings(_settings(("a", DEAD_URI), backend="mongo", connection="a"))
    assert env.services.settings().mongo_connections[0].uri.get_secret_value() == GOOD_B


def test_editing_an_unrelated_connection_is_not_a_switch(env: Env) -> None:
    env.services.update_settings(
        _settings(("a", GOOD_A), ("b", GOOD_B), backend="mongo", connection="a")
    )
    built = len(env.hub.clients)
    env.services.update_settings(
        _settings(("a", GOOD_A), ("b", OTHER_URI), backend="mongo", connection="a")
    )
    assert len(env.hub.clients) == built  # no probe was needed


# --------------------------------------------------------------------------- failures


def test_an_unreachable_destination_leaves_everything_as_it_was(env: Env) -> None:
    old = env.services.update_settings(_settings(("a", GOOD_A), theme="dark")).settings
    graphs = _seed_files(env)
    with pytest.raises(StorageError) as info:
        env.services.update_settings(
            _settings(("a", GOOD_A), ("dead", DEAD_URI), backend="mongo", connection="dead"),
            migrate=True,
        )
    assert info.value.message == "MongoDB connection 'dead' is unreachable"
    assert env.services.settings() == old
    assert _on_disk(env) == old
    assert isinstance(env.services.graphs(), FileGraphRepository)
    assert list(env.services.graphs().iter_definitions()) == graphs
    assert DEAD_URI not in json.dumps(json.loads(env.config.settings_file.read_text()))
    assert DEAD_URI not in env.config.credentials_file.read_text()


def test_a_destination_that_cannot_be_built_leaves_everything_as_it_was(env: Env) -> None:
    old = env.services.settings()
    with pytest.raises(StorageError, match="could not be created"):
        env.services.update_settings(_settings(("r", REFUSED_URI), backend="mongo", connection="r"))
    assert env.services.settings() == old
    assert not env.config.settings_file.exists()
    assert not env.config.credentials_file.exists()


def test_a_failure_midway_through_the_copy_keeps_the_old_settings(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = env.services.update_settings(_settings(("a", GOOD_A))).settings
    graphs = _seed_files(env)
    real_put = MongoGraphRepository.put
    calls: list[str] = []

    def flaky(
        self: MongoGraphRepository, graph: GraphDefinition, *, overwrite: bool = False
    ) -> GraphDefinition:
        calls.append(graph.id)
        if len(calls) == 2:
            raise StorageError("connection lost")
        return real_put(self, graph, overwrite=overwrite)

    monkeypatch.setattr(MongoGraphRepository, "put", flaky)
    with pytest.raises(StorageError, match="connection lost"):
        env.services.update_settings(
            _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
        )
    monkeypatch.undo()
    assert env.services.settings() == old
    assert list(env.services.graphs().iter_definitions()) == graphs  # the source is complete
    assert _mongo_store(env).count() == 1  # the part that was copied stays (a retry is safe)
    retry = env.services.update_settings(
        _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
    )
    assert retry.copy_report == CopyReport(copied=2, skipped=1)


def test_a_failing_save_after_a_successful_copy_keeps_the_old_settings(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = env.services.settings()
    _seed_files(env)

    def refuse(_self: SettingsStore, _settings: AppSettings) -> AppSettings:
        raise SettingsError("disk full")

    monkeypatch.setattr(SettingsStore, "save", refuse)
    with pytest.raises(SettingsError, match="disk full"):
        env.services.update_settings(
            _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
        )
    monkeypatch.undo()
    assert env.services.settings() == old
    assert isinstance(env.services.graphs(), FileGraphRepository)


def test_the_probe_client_is_closed_after_a_successful_switch(env: Env) -> None:
    env.services.update_settings(
        _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
    )
    assert env.hub.closed() == [GOOD_A]  # only the probe exists: the live client is built lazily
    assert env.hub.open() == []


def test_the_probe_client_is_closed_after_a_failed_copy(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_files(env)

    def lost(*_args: object, **_kwargs: object) -> GraphDefinition:
        raise StorageError("connection lost")

    monkeypatch.setattr(MongoGraphRepository, "put", lost)
    with pytest.raises(StorageError, match="connection lost"):
        env.services.update_settings(
            _settings(("a", GOOD_A), backend="mongo", connection="a"), migrate=True
        )
    assert env.hub.closed() == [GOOD_A]
    assert env.hub.open() == []


# --------------------------------------------------------------------------- stale clients


def _warm(env: Env, *names: str) -> None:
    for name in names:
        env.services.mongo.get(name)


def test_clients_of_changed_or_removed_connections_are_closed(env: Env) -> None:
    env.services.update_settings(_settings(("a", GOOD_A), ("b", GOOD_B), ("c", OTHER_URI)))
    _warm(env, "a", "b", "c")
    assert env.hub.closed() == []
    env.services.update_settings(_settings(("a", GOOD_A), ("b", SECRET_URI)))  # b edited, c gone
    assert sorted(env.hub.closed()) == sorted([GOOD_B, OTHER_URI])
    assert env.hub.open() == [GOOD_A]


def test_unchanged_connections_keep_their_clients(env: Env) -> None:
    env.services.update_settings(_settings(("a", GOOD_A), ("b", GOOD_B)))
    _warm(env, "a", "b")
    env.services.update_settings(_settings(("a", GOOD_A), ("b", GOOD_B), theme="dark"))
    assert env.hub.closed() == []
    assert sorted(env.hub.open()) == sorted([GOOD_A, GOOD_B])


def test_a_new_connection_closes_nothing(env: Env) -> None:
    env.services.update_settings(_settings(("a", GOOD_A)))
    _warm(env, "a")
    env.services.update_settings(_settings(("a", GOOD_A), ("b", GOOD_B)))
    assert env.hub.closed() == []


def test_a_new_timeout_closes_every_client(env: Env) -> None:
    env.services.update_settings(_settings(("a", GOOD_A), ("b", GOOD_B)))
    _warm(env, "a", "b")
    env.services.update_settings(_settings(("a", GOOD_A), ("b", GOOD_B), mongo_timeout_ms=5_000))
    assert sorted(env.hub.closed()) == sorted([GOOD_A, GOOD_B])


def test_concurrent_updates_are_serialised(env: Env) -> None:
    barrier = threading.Barrier(8)
    errors: list[Exception] = []

    def work(index: int) -> None:
        barrier.wait()
        try:
            env.services.update_settings(AppSettings(max_links=1000 + index))
        except Exception as exc:  # noqa: BLE001 - any failure fails the test below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert env.services.settings().max_links in {1000 + i for i in range(8)}
    assert mongo_store_module.ITER_PAGE == 100
