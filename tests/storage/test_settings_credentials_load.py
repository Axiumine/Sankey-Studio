# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Loading with a missing, broken, unreadable or loose ``credentials.json``, and the pair copies.

An unusable secrets file is reported and left where it is; only a ``settings.json`` that is
unusable is moved aside, and then ``credentials.json`` goes with it under the same number.
"""

from __future__ import annotations

import errno
import json
import logging
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings
from sankey_studio.storage import SettingsStore
from sankey_studio.storage import settings_store as module
from tests.storage.support import OTHER_URI, SECRET_URI, config_for, mode_of, settings_with

if TYPE_CHECKING:
    from sankey_studio.config import BootstrapConfig

SECRETS = ("hunter2", "s3cret-pass", "mongo.invalid", "other.invalid", "/etc/")
CAP = 1024 * 1024
NOT_JSON = "credentials.json is not valid JSON"
INVALID = "credentials.json is invalid"
MISSING = "credentials.json has no connection string for some connections"
NOT_A_MAPPING = "credentials: Input should be a valid dictionary or instance of StoredCredentials"
A_URI = "mongo_connections.a.uri"
NAME_RULE = "connection name: 1-64 chars of letters, digits, '_', '.', '-'"
MOVED = r"moved to settings\.json\.corrupt-1"


def _no_secret(*texts: object) -> None:
    for text in texts:
        for secret in SECRETS:
            assert secret not in str(text)


def _stored(tmp_path: Path) -> BootstrapConfig:
    """A data directory saved with one connection, ``a``."""
    config = config_for(tmp_path)
    SettingsStore(config).save(settings_with(("a", SECRET_URI)))
    return config


def _aside(config: BootstrapConfig) -> list[str]:
    return sorted(p.name for p in config.data_dir.iterdir() if ".corrupt-" in p.name)


def _with(content: dict[str, Any]) -> bytes:
    return json.dumps(content).encode()


# --------------------------------------------------------------------------- no entry


def test_a_connection_without_a_string_is_reported_and_nothing_is_moved(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    SettingsStore(config).save(settings_with(("a", SECRET_URI), ("b", OTHER_URI)))
    config.credentials_file.unlink()
    before = config.settings_file.read_bytes()
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.message == MISSING
    assert info.value.details == [
        "a: no entry in credentials.json",
        "b: no entry in credentials.json",
    ]
    assert (info.value.status_code, info.value.code) == (422, "settings_error")
    assert config.settings_file.read_bytes() == before
    assert _aside(config) == []
    _no_secret(info.value, repr(info.value))


def test_only_the_connections_without_a_string_are_named(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    SettingsStore(config).save(settings_with(("a", SECRET_URI), ("b", OTHER_URI)))
    config.credentials_file.write_bytes(_with({"mongo_connections": {"b": {"uri": OTHER_URI}}}))
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.details == ["a: no entry in credentials.json"]


class Count(NamedTuple):
    connections: int
    shown: int


@pytest.mark.parametrize(
    "case", [Count(1, 1), Count(19, 19), Count(20, 20), Count(21, 20), Count(40, 20)]
)
def test_at_most_twenty_names_are_reported(tmp_path: Path, case: Count) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir(parents=True)
    config.data_dir.chmod(0o700)
    names = [{"name": f"c{i}", "default_database": None} for i in range(case.connections)]
    config.settings_file.write_text(json.dumps({"mongo_connections": names}), encoding="utf-8")
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert len(info.value.details) == case.shown
    assert info.value.details[0] == "c0: no entry in credentials.json"


def test_a_name_that_is_not_a_valid_name_is_never_put_in_the_message(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir(parents=True)
    config.data_dir.chmod(0o700)
    doc = {"mongo_connections": [{"name": "mongodb://u:hunter2@h/"}]}
    config.settings_file.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SettingsError, match="Settings file is corrupt") as info:
        SettingsStore(config).load()
    _no_secret(info.value, repr(info.value))
    assert _aside(config) == ["settings.json.corrupt-1"]


# --------------------------------------------------------------------------- unusable content


class BadFile(NamedTuple):
    label: str
    content: bytes
    message: str
    details: list[str]


UNSAFE = SECRET_URI + "&tlsCAFile=/etc/hunter2"
BAD = [
    BadFile("not json", b"{broken", NOT_JSON, []),
    BadFile("empty", b"", NOT_JSON, []),
    BadFile("bad utf-8", b"\xff\xfe\xfd", NOT_JSON, []),
    BadFile("too deep", b"[" * 200_000, NOT_JSON, []),
    BadFile("a list", b"[]", INVALID, [NOT_A_MAPPING]),
    BadFile("null", b"null", INVALID, [NOT_A_MAPPING]),
    BadFile(
        "the flat form", _with({"a": SECRET_URI}), INVALID, ["a: Extra inputs are not permitted"]
    ),
    BadFile("version 2", b'{"version": 2}', INVALID, ["version: Input should be 1"]),
    BadFile(
        "masked",
        _with({"mongo_connections": {"a": {"uri": "**********"}}}),
        INVALID,
        [f"{A_URI}: Value error, uri is a masked placeholder; enter the real connection string"],
    ),
    BadFile(
        "unsafe option",
        _with({"mongo_connections": {"a": {"uri": UNSAFE}}}),
        INVALID,
        [f"{A_URI}: Value error, uri option 'tlsCAFile' is not allowed"],
    ),
    BadFile(
        "no uri", _with({"mongo_connections": {"a": {}}}), INVALID, [f"{A_URI}: Field required"]
    ),
    BadFile(
        "extra field",
        _with({"mongo_connections": {"a": {"uri": SECRET_URI, "token": "x"}}}),
        INVALID,
        ["mongo_connections.a.token: Extra inputs are not permitted"],
    ),
    BadFile(
        "bad name",
        _with({"mongo_connections": {"bad name!": {"uri": SECRET_URI}}}),
        INVALID,
        [f"mongo_connections: Value error, {NAME_RULE}"],
    ),
]


@pytest.mark.parametrize("case", BAD, ids=[c.label for c in BAD])
def test_an_unusable_credentials_file_is_reported_and_left_in_place(
    tmp_path: Path, case: BadFile
) -> None:
    config = _stored(tmp_path)
    config.credentials_file.write_bytes(case.content)
    settings_before = config.settings_file.read_bytes()
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert (info.value.message, info.value.details) == (case.message, case.details)
    assert (info.value.status_code, info.value.code) == (422, "settings_error")
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__
    _no_secret(info.value, info.value.details, repr(info.value))
    assert config.credentials_file.read_bytes() == case.content
    assert config.settings_file.read_bytes() == settings_before
    assert _aside(config) == []


def test_twenty_one_entries_are_refused(tmp_path: Path) -> None:
    config = _stored(tmp_path)
    entries = {f"c{i}": {"uri": SECRET_URI} for i in range(21)}
    config.credentials_file.write_bytes(_with({"mongo_connections": entries}))
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.details[0].startswith(
        "mongo_connections: Dictionary should have at most 20 items"
    )


def test_a_legacy_file_does_not_hide_a_broken_credentials_file(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir(parents=True)
    config.data_dir.chmod(0o700)
    legacy = {"mongo_connections": [{"name": "a", "uri": SECRET_URI}]}
    config.settings_file.write_text(json.dumps(legacy), encoding="utf-8")
    config.credentials_file.write_bytes(b"{broken")
    with pytest.raises(SettingsError, match=NOT_JSON):
        SettingsStore(config).load()
    assert config.credentials_file.read_bytes() == b"{broken"


# --------------------------------------------------------------------------- unreadable


def test_a_symlinked_credentials_file_is_refused_and_left_in_place(tmp_path: Path) -> None:
    config = _stored(tmp_path)
    real = tmp_path / "elsewhere.json"
    real.write_bytes(config.credentials_file.read_bytes())
    config.credentials_file.unlink()
    config.credentials_file.symlink_to(real)
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.message == (
        "Credentials file cannot be read: Too many levels of symbolic links"
    )
    assert config.credentials_file.is_symlink()
    assert _aside(config) == []


def test_a_directory_in_place_of_the_credentials_file_is_unreadable(tmp_path: Path) -> None:
    config = _stored(tmp_path)
    config.credentials_file.unlink()
    config.credentials_file.mkdir()
    with pytest.raises(SettingsError, match="Credentials file cannot be read: not a regular file"):
        SettingsStore(config).load()
    assert config.credentials_file.is_dir()


@pytest.mark.parametrize("extra", [0, 1], ids=["at-the-cap", "one-byte-over"])
def test_the_size_cap_of_the_credentials_file_is_one_mebibyte_inclusive(
    tmp_path: Path, extra: int
) -> None:
    config = _stored(tmp_path)
    body = _with({"mongo_connections": {"a": {"uri": SECRET_URI}}})
    config.credentials_file.write_bytes(body + b" " * (CAP - len(body) + extra))
    if extra == 0:
        assert SettingsStore(config).load().connection("a") is not None
        return
    with pytest.raises(SettingsError, match="cannot be read: the file is too large"):
        SettingsStore(config).load()
    assert config.credentials_file.exists()
    assert _aside(config) == []


@pytest.mark.parametrize("reason", ["the file is owned by another user", "Permission denied"])
def test_a_read_failure_is_reported_with_its_reason_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    config = _stored(tmp_path)

    def refuse(_path: Path, _limit: int) -> bytes:
        raise OSError(errno.EPERM, reason)

    monkeypatch.setattr(module, "read_private_file", refuse)
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.message == f"Credentials file cannot be read: {reason}"
    assert info.value.__cause__ is not None  # the OSError is the cause, not a copy of any path


# --------------------------------------------------------------------------- permissions


class Perm(NamedTuple):
    before: int
    after: int


@pytest.mark.parametrize(
    "case", [Perm(0o600, 0o600), Perm(0o400, 0o400), Perm(0o644, 0o600), Perm(0o640, 0o600)]
)
def test_loose_permissions_are_tightened_on_load_and_the_file_still_loads(
    tmp_path: Path, case: Perm
) -> None:
    config = _stored(tmp_path)
    config.credentials_file.chmod(case.before)
    loaded = SettingsStore(config).load()
    assert loaded.connection("a") is not None
    assert mode_of(config.credentials_file) == case.after


def test_a_tightened_file_is_not_seen_as_a_change(tmp_path: Path) -> None:
    config = _stored(tmp_path)
    store = SettingsStore(config)
    config.credentials_file.chmod(0o644)
    first = store.load()
    assert stat.S_IMODE(config.credentials_file.stat().st_mode) == 0o600
    assert store.load() is first


# --------------------------------------------------------------------------- the pair copies


def test_a_corrupt_settings_file_takes_credentials_json_with_it(tmp_path: Path) -> None:
    config = _stored(tmp_path)
    secret_bytes = config.credentials_file.read_bytes()
    config.settings_file.write_bytes(b"{broken")
    store = SettingsStore(config)
    with pytest.raises(SettingsError) as info:
        store.load()
    assert info.value.message == "Settings file is corrupt; it was moved to settings.json.corrupt-1"
    moved = config.data_dir / "credentials.json.corrupt-1"
    assert moved.read_bytes() == secret_bytes
    assert mode_of(moved) == mode_of(config.data_dir / "settings.json.corrupt-1") == 0o600
    assert not config.credentials_file.exists()
    assert not config.settings_file.exists()
    assert store.load() == AppSettings()  # the next call starts from the defaults


def test_after_the_pair_is_set_aside_a_new_save_starts_again_and_the_copies_stay(
    tmp_path: Path,
) -> None:
    config = _stored(tmp_path)
    config.settings_file.write_bytes(b"{broken")
    store = SettingsStore(config)
    with pytest.raises(SettingsError):
        store.load()
    saved = store.save(settings_with(("n", OTHER_URI)))
    assert SettingsStore(config).load() == saved
    assert _aside(config) == ["credentials.json.corrupt-1", "settings.json.corrupt-1"]


@pytest.mark.parametrize("content", [b'{"max_links": 1}', b"[]", b"null"])
def test_settings_that_are_not_valid_take_a_valid_credentials_file_with_them(
    tmp_path: Path, content: bytes
) -> None:
    config = _stored(tmp_path)
    config.settings_file.write_bytes(content)
    with pytest.raises(SettingsError, match=MOVED):
        SettingsStore(config).load()
    assert _aside(config) == ["credentials.json.corrupt-1", "settings.json.corrupt-1"]


def test_broken_settings_win_over_a_broken_credentials_file(tmp_path: Path) -> None:
    config = _stored(tmp_path)
    config.settings_file.write_bytes(b"{broken")
    config.credentials_file.write_bytes(b"{also broken")
    with pytest.raises(SettingsError, match="Settings file is corrupt"):
        SettingsStore(config).load()
    moved = config.data_dir / "credentials.json.corrupt-1"
    assert moved.read_bytes() == b"{also broken"


def test_without_a_credentials_file_only_the_settings_are_moved(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir(parents=True)
    config.data_dir.chmod(0o700)
    config.settings_file.write_bytes(b"{broken")
    with pytest.raises(SettingsError, match=MOVED):
        SettingsStore(config).load()
    assert _aside(config) == ["settings.json.corrupt-1"]


@pytest.mark.parametrize("kind", ["symlink", "dangling", "directory"])
def test_only_a_regular_credentials_file_goes_with_the_settings(tmp_path: Path, kind: str) -> None:
    config = _stored(tmp_path)
    real = tmp_path / "elsewhere.json"
    real.write_bytes(config.credentials_file.read_bytes())
    real.chmod(0o644)
    config.credentials_file.unlink()
    if kind == "directory":
        config.credentials_file.mkdir()
    else:
        config.credentials_file.symlink_to(real if kind == "symlink" else tmp_path / "nowhere")
    config.settings_file.write_bytes(b"{broken")
    with pytest.raises(SettingsError, match=MOVED):
        SettingsStore(config).load()
    assert _aside(config) == ["settings.json.corrupt-1"]
    assert config.credentials_file.is_symlink() or config.credentials_file.is_dir()
    assert mode_of(real) == 0o644  # nothing followed the link


class Pair(NamedTuple):
    settings: tuple[int, ...]
    credentials: tuple[int, ...]
    target: int


@pytest.mark.parametrize(
    "case",
    [
        Pair((), (), 1),
        Pair((1,), (), 2),
        Pair((), (1,), 2),  # a number is free only when BOTH names are free
        Pair((1,), (2,), 3),
        Pair((2,), (), 1),
        Pair(tuple(range(1, 20)), (), 20),
        Pair((), tuple(range(1, 20)), 20),
        Pair(tuple(range(1, 21)), (), 20),  # all taken: the last pair is reused
        Pair((), tuple(range(1, 21)), 20),
    ],
)
def test_the_pair_gets_the_first_number_that_is_free_for_both(tmp_path: Path, case: Pair) -> None:
    config = _stored(tmp_path)
    secret_bytes = config.credentials_file.read_bytes()
    for number in case.settings:
        (config.data_dir / f"settings.json.corrupt-{number}").write_text(f"old {number}")
    for number in case.credentials:
        (config.data_dir / f"credentials.json.corrupt-{number}").write_text(f"old {number}")
    config.settings_file.write_bytes(b"{broken")
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.message.endswith(f"settings.json.corrupt-{case.target}")
    assert (config.data_dir / f"settings.json.corrupt-{case.target}").read_bytes() == b"{broken"
    moved = config.data_dir / f"credentials.json.corrupt-{case.target}"
    assert moved.read_bytes() == secret_bytes
    for number in (n for n in case.settings if n != case.target):
        assert (config.data_dir / f"settings.json.corrupt-{number}").read_text() == f"old {number}"
    assert not (config.data_dir / "settings.json.corrupt-21").exists()
    assert not (config.data_dir / "credentials.json.corrupt-21").exists()


def test_a_failed_move_of_credentials_json_leaves_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _stored(tmp_path)
    config.settings_file.write_bytes(b"{broken")
    original = Path.replace

    def refuse_credentials(self: Path, target: Path) -> Path:
        if self == config.credentials_file:
            raise PermissionError(errno.EACCES, "Permission denied")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", refuse_credentials)
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.message == "Credentials file cannot be moved: Permission denied"
    assert config.settings_file.read_bytes() == b"{broken"  # the next load tries again
    assert config.credentials_file.exists()


def test_a_failed_chmod_of_the_moved_credentials_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _stored(tmp_path)
    config.settings_file.write_bytes(b"{broken")

    def refuse(*_args: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(Path, "chmod", refuse)
    with pytest.raises(SettingsError, match="Credentials file cannot be moved: Operation not"):
        SettingsStore(config).load()


# --------------------------------------------------------------------------- logs


def test_no_failure_path_logs_a_secret(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        for case in BAD:
            config = _stored(tmp_path / case.label.replace(" ", "-"))
            config.credentials_file.write_bytes(case.content)
            with pytest.raises(SettingsError):
                SettingsStore(config).load()
    _no_secret(caplog.text)
