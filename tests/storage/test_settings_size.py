# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``SettingsStore.save`` never writes a file that ``load`` would refuse (1 MiB cap, inclusive).

The two files have a cap each: ``credentials.json`` grows with the connection strings (a URI has no
length limit of its own), ``settings.json`` with the style (5000 node names of 200 characters).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings, MongoConnection, StyleSpec
from sankey_studio.storage import SettingsStore, dump_settings
from sankey_studio.storage.credentials import split_credentials
from sankey_studio.storage.settings_store import (
    CREDENTIALS_MAX_BYTES,
    MSG_CREDENTIALS_TOO_LARGE,
    MSG_TOO_LARGE,
    SETTINGS_MAX_BYTES,
)
from tests.storage.support import config_for, settings_with

if TYPE_CHECKING:
    from pathlib import Path

CAP = 1024 * 1024
FILLER = "p"  # one ASCII character is one byte of the file, so the size is easy to steer
NAMES = 5000  # the longest node_order a style may hold
NAME_CHARS = 199  # a name may have 200: one more character per name is one more byte


def _settings(password_chars: int) -> AppSettings:
    uri = f"mongodb://user:{FILLER * password_chars}@host.invalid:27017/"
    return AppSettings(mongo_connections=[MongoConnection(name="a", uri=SecretStr(uri))])


def _file_size(settings: AppSettings, *, secrets: bool) -> int:
    public, secret = split_credentials(dump_settings(settings))
    return len(json.dumps(secret if secrets else public, indent=2).encode("ascii"))


def _settings_of_size(size: int) -> AppSettings:
    """Settings whose ``credentials.json`` is exactly ``size`` bytes."""
    settings = _settings(size - _file_size(_settings(0), secrets=True))
    assert _file_size(settings, secrets=True) == size
    return settings


def _ordered(longer: int) -> AppSettings:
    """Settings with ``longer`` node names of 200 characters and the rest of 199."""
    names = [f"{i:04d}".ljust(NAME_CHARS + (i < longer), "x") for i in range(NAMES)]
    return AppSettings(default_style=StyleSpec(node_order=names))


def _settings_json_of_size(size: int) -> AppSettings:
    """Settings whose ``settings.json`` is exactly ``size`` bytes."""
    settings = _ordered(size - _file_size(_ordered(0), secrets=False))
    assert _file_size(settings, secrets=False) == size
    return settings


def test_the_caps_are_one_mebibyte() -> None:
    assert SETTINGS_MAX_BYTES == CREDENTIALS_MAX_BYTES == CAP
    assert MSG_TOO_LARGE == "Settings are too large to save"
    assert MSG_CREDENTIALS_TOO_LARGE == "Credentials are too large to save"


# --------------------------------------------------------------------------- credentials.json


@pytest.mark.parametrize("size", [CAP - 1, CAP])
def test_a_credentials_file_up_to_the_cap_is_saved_and_loads_back(
    tmp_path: Path, size: int
) -> None:
    config = config_for(tmp_path)
    settings = _settings_of_size(size)
    saved = SettingsStore(config).save(settings)
    assert config.credentials_file.stat().st_size == size
    assert SettingsStore(config).load() == saved == settings  # a fresh store reads the files


def test_a_credentials_file_one_byte_over_the_cap_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path)
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).save(_settings_of_size(CAP + 1))
    assert info.value.message == "Credentials are too large to save"
    assert (info.value.status_code, info.value.code, info.value.details) == (
        422,
        "settings_error",
        [],
    )
    assert not config.data_dir.exists()  # not even the directory was created


def test_a_one_mebibyte_uri_is_refused_and_the_old_files_stay_loadable(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    old = store.save(settings_with(("a", "mongodb://small:pw@host.invalid:27017/"), theme="dark"))
    before = (config.settings_file.read_bytes(), config.credentials_file.read_bytes())
    with pytest.raises(SettingsError, match=r"^Credentials are too large to save$") as info:
        store.save(_settings(CAP))
    assert FILLER * 20 not in info.value.message  # the URI is never echoed
    assert FILLER * 20 not in repr(info.value)
    assert (config.settings_file.read_bytes(), config.credentials_file.read_bytes()) == before
    names = sorted(p.name for p in config.data_dir.iterdir())
    assert names == ["credentials.json", "settings.json"]  # no temporary file
    assert store.load() is old  # the cache still serves the old settings
    assert SettingsStore(config).load() == old  # and so does the file


def test_a_refused_save_leaves_no_corrupt_copy_and_the_store_stays_usable(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    with pytest.raises(SettingsError, match="too large"):
        store.save(_settings(CAP))
    smaller = store.save(_settings_of_size(CAP))
    assert SettingsStore(config).load() == smaller
    assert sorted(p.name for p in config.data_dir.iterdir()) == [
        "credentials.json",
        "settings.json",
    ]


# --------------------------------------------------------------------------- settings.json


@pytest.mark.parametrize("size", [CAP - 1, CAP])
def test_a_settings_file_up_to_the_cap_is_saved_and_loads_back(tmp_path: Path, size: int) -> None:
    config = config_for(tmp_path)
    settings = _settings_json_of_size(size)
    saved = SettingsStore(config).save(settings)
    assert config.settings_file.stat().st_size == size
    assert SettingsStore(config).load() == saved == settings


def test_a_settings_file_one_byte_over_the_cap_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path)
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).save(_settings_json_of_size(CAP + 1))
    assert info.value.message == "Settings are too large to save"
    assert (info.value.status_code, info.value.code, info.value.details) == (
        422,
        "settings_error",
        [],
    )
    assert not config.data_dir.exists()
