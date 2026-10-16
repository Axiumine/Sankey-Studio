# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``SettingsStore.save`` never writes a file that ``load`` would refuse (1 MiB cap, inclusive)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.storage import SettingsStore, dump_settings
from sankey_studio.storage.settings_store import MSG_TOO_LARGE, SETTINGS_MAX_BYTES
from tests.storage.support import config_for, settings_with

if TYPE_CHECKING:
    from pathlib import Path

CAP = 1024 * 1024
FILLER = "p"  # one ASCII character is one byte of the file, so the size is easy to steer


def _settings(password_chars: int) -> AppSettings:
    uri = f"mongodb://user:{FILLER * password_chars}@host.invalid:27017/"
    return AppSettings(mongo_connections=[MongoConnection(name="a", uri=SecretStr(uri))])


def _file_size(settings: AppSettings) -> int:
    return len(json.dumps(dump_settings(settings), indent=2).encode("ascii"))


def _settings_of_size(size: int) -> AppSettings:
    """Settings whose ``settings.json`` is exactly ``size`` bytes."""
    settings = _settings(size - _file_size(_settings(0)))
    assert _file_size(settings) == size
    return settings


def test_the_cap_is_one_mebibyte() -> None:
    assert SETTINGS_MAX_BYTES == CAP
    assert MSG_TOO_LARGE == "Settings are too large to save"


@pytest.mark.parametrize("size", [CAP - 1, CAP])
def test_a_file_up_to_the_cap_is_saved_and_loads_back(tmp_path: Path, size: int) -> None:
    config = config_for(tmp_path)
    settings = _settings_of_size(size)
    saved = SettingsStore(config).save(settings)
    assert config.settings_file.stat().st_size == size
    assert SettingsStore(config).load() == saved == settings  # a fresh store reads the file


def test_a_file_one_byte_over_the_cap_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path)
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).save(_settings_of_size(CAP + 1))
    assert info.value.message == "Settings are too large to save"
    assert (info.value.status_code, info.value.code, info.value.details) == (
        422,
        "settings_error",
        [],
    )
    assert not config.data_dir.exists()  # not even the directory was created


def test_a_one_mebibyte_uri_is_refused_and_the_old_file_stays_loadable(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    old = store.save(settings_with(("a", "mongodb://small:pw@host.invalid:27017/"), theme="dark"))
    before = config.settings_file.read_bytes()
    with pytest.raises(SettingsError, match=r"^Settings are too large to save$") as info:
        store.save(_settings(CAP))
    assert FILLER * 20 not in info.value.message  # the URI is never echoed
    assert FILLER * 20 not in repr(info.value)
    assert config.settings_file.read_bytes() == before
    assert [p.name for p in config.data_dir.iterdir()] == ["settings.json"]  # no temp file
    assert store.load() is old  # the cache still serves the old settings
    assert SettingsStore(config).load() == old  # and so does the file


def test_a_refused_save_leaves_no_corrupt_copy_and_the_store_stays_usable(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    with pytest.raises(SettingsError, match="too large"):
        store.save(_settings(CAP))
    smaller = store.save(_settings_of_size(CAP))
    assert SettingsStore(config).load() == smaller
    assert sorted(p.name for p in config.data_dir.iterdir()) == ["settings.json"]
