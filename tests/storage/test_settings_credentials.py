# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``credentials.json``: the connection strings apart from ``settings.json``, and the migration.

Failure modes of the secrets file are in ``test_settings_credentials_load.py``.
"""

from __future__ import annotations

import errno
import json
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings
from sankey_studio.storage import SettingsStore, atomic
from sankey_studio.storage import settings_store as module
from tests.storage.support import (
    OTHER_URI,
    SECRET_URI,
    config_for,
    mode_of,
    settings_with,
    umask,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.config import BootstrapConfig

NEW_URI = "mongodb://tester:n3w-pass@new.invalid:27017/"
SECRETS = ("hunter2", "s3cret-pass", "n3w-pass", "mongo.invalid", "other.invalid", "new.invalid")
LEGACY: dict[str, Any] = {
    "theme": "dark",
    "mongo_connections": [
        {"name": "a", "uri": SECRET_URI, "default_database": "flows"},
        {"name": "b", "uri": OTHER_URI, "default_database": None},
    ],
}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _uri(settings: AppSettings, name: str) -> str:
    conn = settings.connection(name)
    assert conn is not None
    return conn.uri.get_secret_value()


def _no_secret(*texts: object) -> None:
    for text in texts:
        for secret in SECRETS:
            assert secret not in str(text)


def _write_legacy(config: BootstrapConfig) -> bytes:
    """A ``settings.json`` as the version before ``credentials.json`` wrote it."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.chmod(0o700)
    raw = json.dumps(LEGACY).encode()
    config.settings_file.write_bytes(raw)
    return raw


# --------------------------------------------------------------------------- save


def test_save_puts_the_strings_in_credentials_json_and_none_in_settings_json(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path)
    settings = settings_with(("a", SECRET_URI), ("b", OTHER_URI), theme="dark", max_upload_mb=7)
    with umask(0o022):
        assert SettingsStore(config).save(settings) == settings
    assert mode_of(config.data_dir) == 0o700
    assert mode_of(config.settings_file) == mode_of(config.credentials_file) == 0o600
    public = _json(config.settings_file)
    assert public["mongo_connections"] == [
        {"name": "a", "default_database": None},
        {"name": "b", "default_database": None},
    ]
    assert (public["theme"], public["max_upload_mb"]) == ("dark", 7)
    assert _json(config.credentials_file) == {
        "version": 1,
        "mongo_connections": {"a": {"uri": SECRET_URI}, "b": {"uri": OTHER_URI}},
    }
    _no_secret(config.settings_file.read_text())
    assert sorted(p.name for p in config.data_dir.iterdir()) == [
        "credentials.json",
        "settings.json",
    ]


def test_the_credentials_file_is_pretty_printed_ascii_json(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    SettingsStore(config).save(settings_with(("a", "mongodb://u:pw@h.invalid/")))
    assert config.credentials_file.read_bytes().decode("ascii") == (
        '{\n  "version": 1,\n  "mongo_connections": {\n    "a": {\n'
        '      "uri": "mongodb://u:pw@h.invalid/"\n    }\n  }\n}'
    )


@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077])
def test_the_credentials_file_is_0600_whatever_the_umask(tmp_path: Path, mask: int) -> None:
    config = config_for(tmp_path)
    with umask(mask):
        SettingsStore(config).save(settings_with(("a", SECRET_URI)))
    assert mode_of(config.credentials_file) == 0o600


def test_settings_without_connections_still_write_an_empty_credentials_file(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path)
    SettingsStore(config).save(AppSettings())
    assert _json(config.credentials_file) == {"version": 1, "mongo_connections": {}}
    assert mode_of(config.credentials_file) == 0o600


def test_a_second_instance_reads_both_files(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    saved = SettingsStore(config).save(settings_with(("a", SECRET_URI), ("b", OTHER_URI)))
    loaded = SettingsStore(config_for(tmp_path)).load()
    assert loaded == saved
    assert (_uri(loaded, "a"), _uri(loaded, "b")) == (SECRET_URI, OTHER_URI)


def test_a_removed_connection_takes_its_string_out_of_the_file(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(settings_with(("a", SECRET_URI), ("b", OTHER_URI)))
    store.save(settings_with(("a", SECRET_URI)))
    assert list(_json(config.credentials_file)["mongo_connections"]) == ["a"]
    assert "s3cret-pass" not in config.credentials_file.read_text()


def test_a_renamed_connection_keeps_its_string_under_the_new_name(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(settings_with(("a", SECRET_URI)))
    store.save(settings_with(("z", SECRET_URI)))
    assert _json(config.credentials_file)["mongo_connections"] == {"z": {"uri": SECRET_URI}}
    assert _uri(SettingsStore(config).load(), "z") == SECRET_URI


def test_the_credentials_are_replaced_before_the_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    original = atomic.write_atomic

    def recording(path: Path, data: bytes) -> None:
        order.append(path.name)
        original(path, data)

    monkeypatch.setattr(module, "write_atomic", recording)
    SettingsStore(config_for(tmp_path)).save(settings_with(("a", SECRET_URI)))
    assert order == ["credentials.json", "settings.json"]


def test_when_the_settings_write_fails_the_new_strings_are_already_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(settings_with(("a", SECRET_URI), theme="dark"))
    original = atomic.write_atomic

    def fail_for_settings(path: Path, data: bytes) -> None:
        if path == config.settings_file:
            raise OSError(errno.EIO, "disk")
        original(path, data)

    monkeypatch.setattr(module, "write_atomic", fail_for_settings)
    with pytest.raises(SettingsError, match="Settings could not be saved: disk"):
        store.save(settings_with(("a", OTHER_URI), theme="light"))
    monkeypatch.undo()
    loaded = SettingsStore(config).load()
    assert loaded.theme == "dark"  # the old settings...
    assert _uri(loaded, "a") == OTHER_URI  # ...and the rotated string: a crash loses no secret


# --------------------------------------------------------------------------- the seed


def test_the_seed_is_stored_in_credentials_json_by_the_first_save(tmp_path: Path) -> None:
    config = config_for(tmp_path, SECRET_URI)
    store = SettingsStore(config)
    seeded = store.load()
    assert not config.data_dir.exists()  # seeding writes nothing
    store.save(seeded)
    _no_secret(config.settings_file.read_text())
    assert _json(config.credentials_file)["mongo_connections"] == {"default": {"uri": SECRET_URI}}


def test_the_seed_is_ignored_once_a_settings_file_exists(tmp_path: Path) -> None:
    SettingsStore(config_for(tmp_path, SECRET_URI)).save(AppSettings())
    assert SettingsStore(config_for(tmp_path, OTHER_URI)).load().mongo_connections == []


# --------------------------------------------------------------------------- migration


def test_a_legacy_file_is_read_and_a_load_changes_nothing_on_disk(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    raw = _write_legacy(config)
    store = SettingsStore(config)
    loaded = store.load()
    assert (_uri(loaded, "a"), _uri(loaded, "b")) == (SECRET_URI, OTHER_URI)
    assert (loaded.theme, [c.default_database for c in loaded.mongo_connections]) == (
        "dark",
        ["flows", None],
    )
    assert config.settings_file.read_bytes() == raw
    assert not config.credentials_file.exists()
    assert store.load() is loaded  # cached


def test_the_next_save_moves_the_strings_out_of_a_legacy_file(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    _write_legacy(config)
    store = SettingsStore(config)
    saved = store.save(store.load().model_copy(update={"max_links": 500}))
    _no_secret(config.settings_file.read_text())
    assert _json(config.credentials_file)["mongo_connections"] == {
        "a": {"uri": SECRET_URI},
        "b": {"uri": OTHER_URI},
    }
    assert mode_of(config.credentials_file) == 0o600
    assert SettingsStore(config).load() == saved
    assert saved.max_links == 500


def test_a_legacy_file_survives_a_crash_between_the_two_writes(tmp_path: Path) -> None:
    """The credentials are written first; the settings still hold the strings: both agree."""
    config = config_for(tmp_path)
    raw = _write_legacy(config)
    loaded = SettingsStore(config).load()
    uris = {c.name: {"uri": c.uri.get_secret_value()} for c in loaded.mongo_connections}
    both = {"version": 1, "mongo_connections": uris}
    atomic.write_atomic(config.credentials_file, json.dumps(both).encode())
    assert config.settings_file.read_bytes() == raw
    assert SettingsStore(config).load() == loaded


def test_a_string_still_in_settings_json_wins_over_the_credentials_file(tmp_path: Path) -> None:
    """A hand edit, or a downgrade and upgrade: the newer string is the one in the old place."""
    config = config_for(tmp_path)
    SettingsStore(config).save(settings_with(("a", SECRET_URI), ("b", OTHER_URI)))
    doc = _json(config.settings_file)
    doc["mongo_connections"][0]["uri"] = NEW_URI
    config.settings_file.write_text(json.dumps(doc), encoding="utf-8")
    loaded = SettingsStore(config).load()
    assert (_uri(loaded, "a"), _uri(loaded, "b")) == (NEW_URI, OTHER_URI)


# --------------------------------------------------------------------------- replacing the file


def test_a_hand_replaced_credentials_file_applies_without_a_restart(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(settings_with(("a", SECRET_URI)))
    assert _uri(store.load(), "a") == SECRET_URI
    replacement = {"version": 1, "mongo_connections": {"a": {"uri": NEW_URI}}}
    atomic.write_atomic(config.credentials_file, json.dumps(replacement).encode())
    assert _uri(store.load(), "a") == NEW_URI


def test_an_entry_without_a_connection_is_ignored_and_dropped_by_the_next_save(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(settings_with(("a", SECRET_URI), ("b", OTHER_URI)))
    doc = _json(config.settings_file)
    doc["mongo_connections"] = doc["mongo_connections"][:1]  # "b" is gone from the settings
    config.settings_file.write_text(json.dumps(doc), encoding="utf-8")
    loaded = SettingsStore(config).load()
    assert [c.name for c in loaded.mongo_connections] == ["a"]
    store2 = SettingsStore(config)
    store2.save(loaded)
    assert list(_json(config.credentials_file)["mongo_connections"]) == ["a"]
