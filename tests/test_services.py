"""``Services``: construction, the cached repository, sources and the source context."""

from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError, dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple

import pytest

from sankey_studio.config import BootstrapConfig
from sankey_studio.errors import StorageError
from sankey_studio.models import AppSettings
from sankey_studio.mongo import MongoClients, default_factory
from sankey_studio.services import Services, UpdateResult, _storage_identity
from sankey_studio.sources.base import SourceContext
from sankey_studio.storage import FileGraphRepository, MongoGraphRepository
from tests.conftest import build_connection
from tests.storage.mongo_fakes import Hub
from tests.storage.support import ID_A, definition, mode_of, umask

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
    database: str = "sankey_studio",
) -> AppSettings:
    """Two connections (a, b); the graph store as asked."""
    return AppSettings(
        mongo_connections=[build_connection("a"), build_connection("b")],
        storage_backend=backend,
        storage_connection=connection,
        storage_database=database,
    )


def _mongo(connection: str = "a", database: str = "sankey_studio") -> AppSettings:
    return _settings(backend="mongo", connection=connection, database=database)


# --------------------------------------------------------------------------- construction


def test_create_wires_config_settings_and_clients(env: Env) -> None:
    assert env.services.config is env.config
    assert isinstance(env.services.mongo, MongoClients)
    assert env.services.settings() == AppSettings()
    assert env.services.settings() is env.services.settings()


def test_the_real_client_factory_is_the_default(tmp_path: Path) -> None:
    services = Services.create(BootstrapConfig(data_dir=tmp_path / "data"))
    assert services.mongo._factory is default_factory
    services.close()


def test_the_given_factory_builds_the_clients(env: Env) -> None:
    env.services.update_settings(_settings())
    env.services.mongo.get("a")
    assert [c.uri for c in env.hub.clients] == [build_connection("a").uri.get_secret_value()]


def test_clients_follow_the_stored_settings_live(env: Env) -> None:
    with pytest.raises(Exception, match="Unknown MongoDB connection 'a'"):
        env.services.mongo.get("a")
    env.services.update_settings(_settings())
    assert env.services.mongo.get("a") is not None


def test_close_closes_every_client_and_is_idempotent(env: Env) -> None:
    env.services.update_settings(_settings())
    env.services.mongo.get("a")
    env.services.mongo.get("b")
    env.services.close()
    env.services.close()
    assert env.hub.open() == []
    assert len(env.hub.closed()) == 2


def test_the_result_type_is_a_frozen_value() -> None:
    result = UpdateResult(AppSettings())
    assert result.copy_report is None
    with pytest.raises(FrozenInstanceError):
        result.copy_report = None  # type: ignore[misc]


# --------------------------------------------------------------------------- repository


def test_the_file_backend_is_the_default_and_the_instance_is_cached(env: Env) -> None:
    repo = env.services.graphs()
    assert isinstance(repo, FileGraphRepository)
    assert env.services.graphs() is repo
    repo.put(definition(ID_A, "g"))
    assert (env.config.graphs_dir / f"{ID_A}.json").is_file()


def test_an_unrelated_settings_change_keeps_the_instance(env: Env) -> None:
    repo = env.services.graphs()
    env.services.update_settings(AppSettings(theme="dark", max_links=500))
    assert env.services.graphs() is repo


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
def test_every_component_of_the_key_rebuilds_the_repository(env: Env, case: Change) -> None:
    env.services.update_settings(case.before)
    first = env.services.graphs()
    assert env.services.graphs() is first
    env.services.update_settings(case.after)
    second = env.services.graphs()
    assert second is not first
    assert env.services.graphs() is second


def test_the_resolved_graphs_directory_is_part_of_the_key(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = env.services.graphs()
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setattr(BootstrapConfig, "graphs_dir", property(lambda _self: elsewhere))
    second = env.services.graphs()
    assert second is not first
    assert isinstance(second, FileGraphRepository)
    assert elsewhere.is_dir()
    assert env.services.graphs() is second
    monkeypatch.undo()
    assert env.services.graphs() is not second


def test_a_symlinked_graphs_directory_resolves_to_the_same_key(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = env.services.graphs()
    link = tmp_path / "link"
    link.symlink_to(env.config.graphs_dir)
    monkeypatch.setattr(BootstrapConfig, "graphs_dir", property(lambda _self: link))
    assert env.services.graphs() is first


def test_the_mongo_backend_gets_a_mongo_repository_on_the_shared_clients(env: Env) -> None:
    env.services.update_settings(_mongo("b", "mine"))
    repo = env.services.graphs()
    assert isinstance(repo, MongoGraphRepository)
    assert repo._clients is env.services.mongo
    assert (repo._target.connection, repo._target.database) == ("b", "mine")


def test_concurrent_callers_share_one_instance(env: Env) -> None:
    barrier = threading.Barrier(20)
    seen: list[object] = []

    def work() -> None:
        barrier.wait()
        seen.append(env.services.graphs())

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
        env.services.graphs()
    monkeypatch.undo()
    assert isinstance(env.services.graphs(), FileGraphRepository)


# --------------------------------------------------------------------------- sources


def test_the_default_sources_directory_is_created_on_demand_and_nothing_else(env: Env) -> None:
    with umask(0o022):
        path = env.services.sources_dir()
    assert path == env.config.data_dir / "sources"
    assert path.is_dir()
    assert mode_of(path) == 0o700
    assert sorted(p.name for p in env.config.data_dir.iterdir()) == ["sources"]
    assert env.services.sources_dir() == path  # a second call is harmless


def test_a_configured_sources_directory_is_used(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=tmp_path / "data", sources_dir=tmp_path / "csv" / "in")
    services = Services.create(config)
    assert services.sources_dir() == tmp_path / "csv" / "in"
    assert (tmp_path / "csv" / "in").is_dir()
    assert not (tmp_path / "data").exists()
    services.close()


def test_an_unusable_sources_directory_is_a_storage_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    config = BootstrapConfig(data_dir=tmp_path / "data", sources_dir=blocker / "sub")
    services = Services.create(config)
    with pytest.raises(StorageError) as info:
        services.sources_dir()
    assert info.value.message.startswith("The sources directory is not usable: ")
    assert str(tmp_path) not in info.value.message
    services.close()


@pytest.mark.parametrize("strict", [True, False])
def test_the_source_context_carries_settings_directory_clients_and_strictness(
    env: Env, strict: bool
) -> None:
    ctx = env.services.source_context(strict=strict)
    assert isinstance(ctx, SourceContext)
    assert ctx.strict is strict
    assert ctx.settings is env.services.settings()
    assert ctx.sources_dir == env.config.data_dir / "sources"
    assert ctx.mongo is env.services.mongo


def test_the_source_context_is_lenient_by_default(env: Env) -> None:
    assert env.services.source_context().strict is False


# --------------------------------------------------------------------------- storage identity


def test_the_identity_of_a_file_store_is_just_its_kind() -> None:
    assert _storage_identity(AppSettings()) == ("file",)
    assert _storage_identity(_settings(backend="file", connection="a", database="other")) == (
        "file",
    )


def test_the_identity_of_a_mongo_store_names_connection_database_and_uri() -> None:
    settings = _mongo("b", "mine")
    uri = build_connection("b").uri.get_secret_value()
    assert _storage_identity(settings) == ("mongo", "b", "mine", uri)


def test_every_part_of_a_mongo_identity_matters() -> None:
    base = _storage_identity(_mongo("a", "one"))
    assert _storage_identity(_mongo("a", "one")) == base
    assert _storage_identity(_mongo("b", "one")) != base
    assert _storage_identity(_mongo("a", "two")) != base
    renamed = AppSettings(
        storage_backend="mongo",
        storage_connection="a",
        storage_database="one",
        mongo_connections=[build_connection("a", uri="mongodb://other:pw@elsewhere.invalid/")],
    )
    assert _storage_identity(renamed) != base


def test_a_missing_storage_connection_has_an_empty_uri_in_the_identity() -> None:
    settings = AppSettings.model_construct(
        storage_backend="mongo", storage_connection="gone", storage_database="mine"
    )
    assert _storage_identity(settings) == ("mongo", "gone", "mine", "")


# --------------------------------------------------------------------------- settings transaction

WAIT_S = 5.0
#: How long a thread must stay outside the lock to count as "kept out".
GRACE_S = 0.2


class Contender:
    """A thread that tries to enter ``settings_transaction`` and says when it got in."""

    def __init__(self, services: Services) -> None:
        self.started = threading.Event()
        self.entered = threading.Event()
        self._services = services
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        self.started.set()
        with self._services.settings_transaction():
            self.entered.set()

    def start(self) -> None:
        self._thread.start()
        assert self.started.wait(WAIT_S)

    def kept_out(self) -> bool:
        return not self.entered.wait(GRACE_S)

    def finish(self) -> None:
        assert self.entered.wait(WAIT_S)
        self._thread.join(WAIT_S)
        assert not self._thread.is_alive()


def test_the_transaction_keeps_every_other_thread_out_until_it_ends(env: Env) -> None:
    contender = Contender(env.services)
    with env.services.settings_transaction():
        contender.start()
        assert contender.kept_out()
    contender.finish()


def test_the_transaction_is_re_entrant_so_update_settings_can_run_inside_it(env: Env) -> None:
    saved: list[AppSettings] = []

    def work() -> None:
        with env.services.settings_transaction(), env.services.settings_transaction():
            saved.append(env.services.update_settings(AppSettings(theme="dark")).settings)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(WAIT_S)
    assert not thread.is_alive()  # a plain (non re-entrant) lock would deadlock here
    assert [s.theme for s in saved] == ["dark"]
    assert env.services.settings().theme == "dark"


def test_the_transaction_reads_what_the_last_writer_saved(env: Env) -> None:
    env.services.update_settings(AppSettings(theme="dark"))
    with env.services.settings_transaction():
        assert env.services.settings().theme == "dark"


def test_the_lock_is_released_when_the_transaction_raises(env: Env) -> None:
    with pytest.raises(ZeroDivisionError), env.services.settings_transaction():
        _ = 1 / 0
    contender = Contender(env.services)
    contender.start()
    contender.finish()


def test_update_settings_holds_the_lock_for_the_whole_storage_switch(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside, release = threading.Event(), threading.Event()

    def slow_switch(_services: Services, _new: AppSettings, **_options: bool) -> None:
        inside.set()  # the ping/copy of a real switch happens here
        assert release.wait(WAIT_S)

    monkeypatch.setattr(Services, "_switch_storage", slow_switch)
    writer = threading.Thread(target=env.services.update_settings, args=(_mongo("a"),), daemon=True)
    writer.start()
    assert inside.wait(WAIT_S)
    contender = Contender(env.services)
    contender.start()
    assert contender.kept_out()
    release.set()
    contender.finish()
    writer.join(WAIT_S)
    assert env.services.settings().storage_backend == "mongo"


def test_probing_a_candidate_store_does_not_take_the_settings_lock(env: Env) -> None:
    probed = threading.Event()

    def probe() -> None:
        env.services.test_storage(AppSettings())
        probed.set()

    with env.services.settings_transaction():
        threading.Thread(target=probe, daemon=True).start()
        assert probed.wait(WAIT_S)
