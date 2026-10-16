# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``Services.test_storage``: probes a candidate store; refused in read-only remote mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

import pytest

from sankey_studio.config import BootstrapConfig
from sankey_studio.errors import ReadOnlyModeError, StorageError
from sankey_studio.models import AppSettings
from sankey_studio.services import MSG_READ_ONLY, MSG_READ_ONLY_TEST, Services
from tests.conftest import build_connection
from tests.storage.mongo_fakes import Hub
from tests.storage.support import placeholder_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

GOOD_A = "mongodb://a-user:a-pass@good-a.invalid:27017/?appName=t"
DEAD_URI = "mongodb://d-user:d-pass@dead.invalid:27017/?appName=t"


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


def test_testing_a_file_store_creates_the_directory_and_saves_nothing(env: Env) -> None:
    env.services.test_storage(AppSettings())
    assert env.config.graphs_dir.is_dir()
    assert not env.config.settings_file.exists()


def test_testing_a_healthy_mongo_target_saves_nothing_and_closes_its_client(env: Env) -> None:
    candidate = _settings(("a", GOOD_A), backend="mongo", connection="a")
    env.services.test_storage(candidate)
    assert env.services.settings() == AppSettings()
    assert not env.config.settings_file.exists()
    assert env.hub.open() == []
    assert env.hub.closed() == [GOOD_A]


def test_testing_a_dead_target_fails_with_a_clean_message(env: Env) -> None:
    candidate = _settings(("dead", DEAD_URI), backend="mongo", connection="dead")
    with pytest.raises(StorageError) as info:
        env.services.test_storage(candidate)
    assert info.value.message == "MongoDB connection 'dead' is unreachable"
    assert "d-pass" not in repr(info.value)


class Mode(NamedTuple):
    label: str
    remote_mode: bool
    remote_writes: bool
    allowed: bool


MODES = [
    Mode("local", False, False, True),
    Mode("remote read-only", True, False, False),
    Mode("remote with writes", True, True, True),
]


def _services_in(tmp_path: Path, mode: Mode) -> tuple[Services, Hub, BootstrapConfig]:
    config = BootstrapConfig(
        data_dir=tmp_path / "data", remote_mode=mode.remote_mode, remote_writes=mode.remote_writes
    )
    hub = Hub()
    return Services.create(config, mongo_factory=hub), hub, config


def _refused(call: Callable[[], object]) -> bool:
    try:
        call()
    except ReadOnlyModeError:
        return True
    return False


@pytest.mark.parametrize("mode", MODES, ids=[m.label for m in MODES])
def test_testing_a_target_is_refused_exactly_when_updating_the_settings_is(
    tmp_path: Path, mode: Mode
) -> None:
    services, _hub, _config = _services_in(tmp_path, mode)
    candidate = _settings(("a", GOOD_A), backend="mongo", connection="a")
    refused = {
        "test": _refused(lambda: services.test_storage(candidate)),
        "update": _refused(lambda: services.update_settings(AppSettings(theme="dark"))),
    }
    assert refused == {"test": not mode.allowed, "update": not mode.allowed}
    services.close()


def test_testing_a_target_in_read_only_remote_mode_builds_and_pings_nothing(
    tmp_path: Path,
) -> None:
    services, hub, config = _services_in(tmp_path, MODES[1])
    with pytest.raises(ReadOnlyModeError) as info:
        services.test_storage(_settings(("a", GOOD_A), backend="mongo", connection="a"))
    assert info.value.message == MSG_READ_ONLY_TEST
    assert info.value.message == (
        "Storage cannot be tested in read-only remote mode (--allow-remote-writes)"
    )
    assert (info.value.status_code, info.value.code) == (403, "read_only_mode")
    assert hub.clients == []  # no client was built, so nothing was pinged
    assert not config.data_dir.exists()
    with pytest.raises(ReadOnlyModeError):
        services.test_storage(AppSettings())  # a file target is refused as well
    assert not config.graphs_dir.exists()
    services.close()


def test_testing_a_target_is_refused_before_the_candidate_is_even_looked_at(
    tmp_path: Path,
) -> None:
    services, hub, _config = _services_in(tmp_path, MODES[1])
    with pytest.raises(ReadOnlyModeError):
        services.test_storage(placeholder_settings())  # would raise a SettingsError otherwise
    assert hub.clients == []
    services.close()


@pytest.mark.parametrize("mode", [MODES[0], MODES[2]], ids=["local", "remote with writes"])
def test_testing_a_target_works_where_updates_are_allowed(tmp_path: Path, mode: Mode) -> None:
    services, hub, config = _services_in(tmp_path, mode)
    services.test_storage(_settings(("a", GOOD_A), backend="mongo", connection="a"))
    assert hub.closed() == [GOOD_A]
    services.test_storage(AppSettings())
    assert config.graphs_dir.is_dir()
    assert not config.settings_file.exists()  # a probe saves nothing
    services.close()


def test_the_two_read_only_messages_name_what_was_refused() -> None:
    assert (
        MSG_READ_ONLY
        == "Settings cannot be changed in read-only remote mode (--allow-remote-writes)"
    )
    assert MSG_READ_ONLY != MSG_READ_ONLY_TEST
