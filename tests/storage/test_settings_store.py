# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``settings_store``: the only code that handles real Mongo URIs, and the cached file store.

It reads and writes ``settings.json`` and ``credentials.json``; the secrets file has its own tests
in ``test_settings_credentials*.py``.
"""

from __future__ import annotations

import json
import logging
import stat
import threading
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from pydantic import SecretStr

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.storage import SettingsStore, atomic, dump_settings, load_settings
from sankey_studio.storage import settings_store as module
from sankey_studio.util import mask_uri
from tests.storage.support import (
    OTHER_URI,
    SECRET_URI,
    config_for,
    mode_of,
    placeholder_settings,
    settings_with,
    umask,
)

if TYPE_CHECKING:
    from pathlib import Path

SECRETS = ("hunter2", "s3cret-pass", "mongo.invalid", "other.invalid")
MASKED_MESSAGE = (
    "mongo_connections.0.uri: Value error, uri is a masked placeholder; "
    "enter the real connection string"
)


def _no_secret(*texts: object) -> None:
    for text in texts:
        for secret in SECRETS:
            assert secret not in str(text)


# --------------------------------------------------------------------------- dump / load


def test_dump_writes_the_real_uris_and_load_restores_them() -> None:
    settings = settings_with(("a", SECRET_URI), ("b", OTHER_URI), max_links=500)
    doc = dump_settings(settings)
    assert [c["uri"] for c in doc["mongo_connections"]] == [SECRET_URI, OTHER_URI]
    assert [c["name"] for c in doc["mongo_connections"]] == ["a", "b"]
    assert doc["max_links"] == 500
    loaded = load_settings(doc)
    assert loaded == settings
    assert [c.uri.get_secret_value() for c in loaded.mongo_connections] == [SECRET_URI, OTHER_URI]


def test_dump_leaves_the_settings_object_masked() -> None:
    settings = settings_with(("a", SECRET_URI))
    dump_settings(settings)
    _no_secret(settings, repr(settings), settings.model_dump_json(), settings.model_dump())


def test_dump_of_settings_without_connections() -> None:
    doc = dump_settings(AppSettings())
    assert doc["mongo_connections"] == []
    assert load_settings(doc) == AppSettings()


@pytest.mark.parametrize(
    "placeholder",
    ["**********", "***", "mongodb://tester:***@mongo.invalid/", "mongodb://***"],
)
def test_a_masked_placeholder_is_refused_on_load(placeholder: str) -> None:
    doc = dump_settings(settings_with(("a", SECRET_URI)))
    doc["mongo_connections"][0]["uri"] = placeholder
    with pytest.raises(SettingsError) as info:
        load_settings(doc)
    assert info.value.message == "Settings are invalid"
    assert info.value.details == [MASKED_MESSAGE]
    assert info.value.status_code == 422


def test_the_default_json_form_cannot_be_loaded_back() -> None:
    settings = settings_with(("a", SECRET_URI))
    with pytest.raises(SettingsError, match="Settings are invalid"):
        load_settings(json.loads(settings.model_dump_json()))
    assert mask_uri(SECRET_URI) != SECRET_URI


class Invalid(NamedTuple):
    doc: Any
    detail: str


NOT_A_MAPPING = "settings: Input should be a valid dictionary or instance of AppSettings"


@pytest.mark.parametrize(
    "case",
    [
        Invalid({"sources_dir": "/"}, "sources_dir: Extra inputs are not permitted"),
        Invalid({"max_links": 99}, "max_links: Input should be greater than or equal to 100"),
        Invalid({"theme": "pink"}, "theme: Input should be 'system', 'light' or 'dark'"),
        Invalid(
            {"storage_backend": "mongo"},
            "settings: Value error, storage_backend 'mongo' needs storage_connection "
            "naming a connection",
        ),
        Invalid(
            {"storage_database": "admin"},
            "storage_database: Value error, "
            "MongoDB system databases (admin, local, config) are not allowed",
        ),
        Invalid([], NOT_A_MAPPING),
        Invalid(None, NOT_A_MAPPING),
        Invalid("text", NOT_A_MAPPING),
    ],
)
def test_invalid_documents_are_reported_by_location_and_message(case: Invalid) -> None:
    with pytest.raises(SettingsError) as info:
        load_settings(case.doc)
    assert info.value.message == "Settings are invalid"
    assert info.value.details == [case.detail]
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_errors_never_echo_the_input() -> None:
    doc = dump_settings(settings_with(("a", SECRET_URI)))
    doc["mongo_connections"][0]["uri"] = SECRET_URI + "&tlsCAFile=/etc/hunter2"
    doc["max_links"] = "hunter2"
    with pytest.raises(SettingsError) as info:
        load_settings(doc)
    _no_secret(info.value, info.value.details, repr(info.value))
    assert "/etc/" not in str(info.value.details)
    assert len(info.value.details) == 2


@pytest.mark.parametrize(("extras", "reported"), [(1, 1), (19, 19), (20, 20), (21, 20), (40, 20)])
def test_at_most_twenty_details_are_reported(extras: int, reported: int) -> None:
    doc = {f"unknown_{i}": 1 for i in range(extras)}
    with pytest.raises(SettingsError) as info:
        load_settings(doc)
    assert len(info.value.details) == reported


# --------------------------------------------------------------------------- defaults and seed


def test_without_a_file_the_defaults_are_returned_and_nothing_is_created(tmp_path: Path) -> None:
    store = SettingsStore(config_for(tmp_path))
    settings = store.load()
    assert settings == AppSettings()
    assert store.load() is settings  # cached
    assert not (tmp_path / "data").exists()


def test_the_seed_uri_becomes_the_default_connection(tmp_path: Path) -> None:
    store = SettingsStore(config_for(tmp_path, SECRET_URI))
    settings = store.load()
    [conn] = settings.mongo_connections
    assert conn.name == "default"
    assert conn.uri.get_secret_value() == SECRET_URI
    assert conn.default_database is None
    assert settings.storage_backend == "file"
    assert settings.storage_connection is None
    assert not (tmp_path / "data").exists()  # seeding persists nothing
    _no_secret(settings, repr(settings))


class Seed(NamedTuple):
    uri: str
    detail: str


@pytest.mark.parametrize(
    "case",
    [
        Seed(
            "mongodb://u:pw-secret@h/?tlsCAFile=/etc/ca-bundle",
            "uri: Value error, uri option 'tlsCAFile' is not allowed",
        ),
        Seed(
            "http://pw-secret@host/",
            "uri: Value error, uri must start with mongodb:// or mongodb+srv://",
        ),
        Seed(
            "mongodb://***",
            "uri: Value error, uri is a masked placeholder; enter the real connection string",
        ),
    ],
)
def test_an_invalid_seed_is_a_settings_error_that_does_not_echo_it(
    tmp_path: Path, case: Seed
) -> None:
    store = SettingsStore(config_for(tmp_path, case.uri))
    with pytest.raises(SettingsError) as info:
        store.load()
    assert info.value.message == "SANKEY_MONGO_URI is not a valid MongoDB connection string"
    assert info.value.details == [case.detail]
    assert "pw-secret" not in repr(info.value)
    assert "/etc/ca-bundle" not in repr(info.value)


def test_a_saved_file_wins_over_the_seed(tmp_path: Path) -> None:
    SettingsStore(config_for(tmp_path, SECRET_URI)).save(AppSettings())
    assert SettingsStore(config_for(tmp_path, SECRET_URI)).load().mongo_connections == []


# --------------------------------------------------------------------------- save


def test_save_writes_private_files_with_the_real_uri_in_a_private_directory(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    settings = settings_with(("a", SECRET_URI), theme="dark", max_upload_mb=7)
    with umask(0o022):
        assert store.save(settings) == settings
    assert mode_of(config.data_dir) == 0o700
    assert mode_of(config.settings_file) == 0o600
    assert stat.S_ISREG(config.settings_file.stat().st_mode)
    on_disk = json.loads(config.settings_file.read_text(encoding="utf-8"))
    assert on_disk["mongo_connections"] == [{"name": "a", "default_database": None}]
    assert mode_of(config.credentials_file) == 0o600
    assert (on_disk["theme"], on_disk["max_upload_mb"]) == ("dark", 7)
    assert sorted(p.name for p in config.data_dir.iterdir()) == [
        "credentials.json",
        "settings.json",
    ]


def test_the_file_is_pretty_printed_ascii_json(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    SettingsStore(config).save(AppSettings(theme="dark"))
    raw = config.settings_file.read_bytes()
    raw.decode("ascii")
    text = raw.decode("ascii")
    assert text.startswith('{\n  "storage_backend": "file",\n  "storage_connection": null,\n')
    assert '\n    "' in text  # nested objects are indented by two more spaces
    assert not text.endswith("\n\n")


def test_non_ascii_text_is_escaped_on_disk_and_round_trips(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    settings = AppSettings(
        mongo_connections=[
            MongoConnection(name="a", uri=SecretStr(SECRET_URI), default_database="caf\u00e9")
        ]
    )
    SettingsStore(config).save(settings)
    raw = config.settings_file.read_bytes()
    assert raw.isascii()
    assert b'"default_database": "caf\\u00e9"' in raw
    [conn] = SettingsStore(config_for(tmp_path)).load().mongo_connections
    assert conn.default_database == "caf\u00e9"


@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077])
def test_the_file_is_0600_whatever_the_umask(tmp_path: Path, mask: int) -> None:
    config = config_for(tmp_path)
    with umask(mask):
        SettingsStore(config).save(AppSettings())
    assert mode_of(config.settings_file) == 0o600


def test_a_second_instance_reads_what_the_first_saved(tmp_path: Path) -> None:
    first = SettingsStore(config_for(tmp_path))
    saved = first.save(settings_with(("a", SECRET_URI), ("b", OTHER_URI)))
    loaded = SettingsStore(config_for(tmp_path)).load()
    assert loaded == saved
    other = loaded.connection("b")
    assert other is not None
    assert other.uri.get_secret_value() == OTHER_URI


def test_save_replaces_the_previous_content(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(settings_with(("a", SECRET_URI)))
    store.save(AppSettings(theme="light"))
    assert json.loads(config.settings_file.read_text())["mongo_connections"] == []
    assert store.load().theme == "light"
    assert sorted(p.name for p in config.data_dir.iterdir()) == [
        "credentials.json",
        "settings.json",
    ]


def test_save_refuses_a_placeholder_secret_and_writes_nothing(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    with pytest.raises(SettingsError, match="Settings are invalid"):
        SettingsStore(config).save(placeholder_settings())
    assert not config.data_dir.exists()


def test_load_serves_what_save_returned_without_reading_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SettingsStore(config_for(tmp_path))
    saved = store.save(settings_with(("a", SECRET_URI)))

    def no_read(*_args: object) -> bytes:
        msg = "the cached settings must not be re-read"
        raise AssertionError(msg)

    monkeypatch.setattr(module, "read_file_nofollow", no_read)
    monkeypatch.setattr(module, "read_private_file", no_read)
    assert store.load() is saved


def test_nothing_secret_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        store = SettingsStore(config_for(tmp_path, SECRET_URI))
        store.load()
        store.save(settings_with(("a", SECRET_URI)))
        store.load()
    _no_secret(caplog.text)


# --------------------------------------------------------------------------- cache by signature


def test_an_external_change_is_picked_up_and_an_unchanged_file_is_not_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    SettingsStore(config).save(AppSettings(theme="dark"))
    reads: list[int] = []
    original = atomic.read_file_nofollow

    def counting(path: Path, limit: int) -> bytes:
        reads.append(limit)
        return original(path, limit)

    fresh = SettingsStore(config)
    monkeypatch.setattr(module, "read_file_nofollow", counting)
    assert fresh.load().theme == "dark"
    assert fresh.load().theme == "dark"
    assert reads == [1024 * 1024]  # read once, with the 1 MiB cap
    atomic.write_atomic(config.settings_file, json.dumps({"theme": "light"}).encode())
    assert fresh.load().theme == "light"
    assert len(reads) == 2


def test_a_deleted_file_brings_the_defaults_back(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(AppSettings(theme="dark"))
    config.settings_file.unlink()
    assert store.load() == AppSettings()


# --------------------------------------------------------------------------- threads


def test_concurrent_loads_and_saves_stay_consistent(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(AppSettings())
    barrier = threading.Barrier(24)
    errors: list[Exception] = []
    seen: list[int] = []

    def worker(index: int) -> None:
        barrier.wait()
        try:
            if index % 2:
                seen.append(store.save(AppSettings(max_links=1000 + index)).max_links)
            else:
                seen.append(store.load().max_links)
        except Exception as exc:  # noqa: BLE001 - any failure fails the test below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(seen) == 24
    final = SettingsStore(config).load().max_links
    assert final in {1000 + i for i in range(24) if i % 2}
    assert store.load().max_links == final
