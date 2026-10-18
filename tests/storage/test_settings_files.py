# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``SettingsStore`` file handling: corrupt files, unreadable files, directory safety, failures."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings
from sankey_studio.storage import SettingsStore, atomic
from sankey_studio.storage import settings_store as module
from tests.storage.support import SECRET_URI, config_for, mode_of, settings_with, umask

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.config import BootstrapConfig

MASKED_DOC = {"mongo_connections": [{"name": "a", "uri": "**********"}]}


def _write(config: BootstrapConfig, content: bytes) -> Path:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.chmod(0o700)  # whatever the umask of the developer running the tests is
    config.settings_file.write_bytes(content)
    return config.settings_file


def _raiser(error: OSError) -> Callable[..., Any]:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    return fail


def _corrupt_files(config: BootstrapConfig) -> list[str]:
    return sorted(p.name for p in config.data_dir.iterdir() if ".corrupt-" in p.name)


# --------------------------------------------------------------------------- corrupt files


class Corrupt(NamedTuple):
    label: str
    content: bytes


CORRUPT = [
    Corrupt("not json", b"{broken"),
    Corrupt("empty", b""),
    Corrupt("bad utf-8", b"\xff\xfe\xfd"),
    Corrupt("a list", b"[]"),
    Corrupt("null", b"null"),
    Corrupt("unknown field", b'{"sources_dir": "/"}'),
    Corrupt("out of range", b'{"max_links": 1}'),
    Corrupt("masked secret", json.dumps(MASKED_DOC).encode()),
    Corrupt("too deep", b"[" * 200_000),
]


@pytest.mark.parametrize("case", CORRUPT, ids=[c.label for c in CORRUPT])
def test_a_corrupt_file_is_moved_aside_and_reported(tmp_path: Path, case: Corrupt) -> None:
    config = config_for(tmp_path)
    _write(config, case.content)
    store = SettingsStore(config)
    with pytest.raises(SettingsError) as info:
        store.load()
    assert info.value.message == "Settings file is corrupt; it was moved to settings.json.corrupt-1"
    assert info.value.status_code == 422
    assert not config.settings_file.exists()
    moved = config.data_dir / "settings.json.corrupt-1"
    assert moved.read_bytes() == case.content
    assert store.load() == AppSettings()  # the next call starts from the defaults


def test_the_moved_copy_is_private_even_when_the_original_was_not(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    path = _write(config, b"{broken")
    path.chmod(0o644)
    with umask(0o022), pytest.raises(SettingsError):
        SettingsStore(config).load()
    assert mode_of(config.data_dir / "settings.json.corrupt-1") == 0o600


def test_a_private_original_stays_private_after_the_move(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(settings_with(("a", SECRET_URI)))
    config.settings_file.write_bytes(b"{broken")  # same inode, same 0600 mode
    store._cached = None
    with umask(0o022), pytest.raises(SettingsError):
        store.load()
    assert mode_of(config.data_dir / "settings.json.corrupt-1") == 0o600


class Existing(NamedTuple):
    present: tuple[int, ...]
    target: int


@pytest.mark.parametrize(
    "case",
    [
        Existing((), 1),
        Existing((1,), 2),
        Existing((1, 2), 3),
        Existing((2,), 1),  # the first free number, not the next after the highest
        Existing((1, 3), 2),
        Existing(tuple(range(1, 19)), 19),
        Existing(tuple(range(1, 20)), 20),
        Existing(tuple(range(1, 21)), 20),  # all taken: the last one is reused
        Existing((20,), 1),
    ],
)
def test_the_first_free_number_is_used_and_at_most_twenty_copies_are_kept(
    tmp_path: Path, case: Existing
) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir(parents=True)
    for number in case.present:
        (config.data_dir / f"settings.json.corrupt-{number}").write_text(f"old {number}")
    _write(config, b"{broken")
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.message.endswith(f"settings.json.corrupt-{case.target}")
    assert (config.data_dir / f"settings.json.corrupt-{case.target}").read_bytes() == b"{broken"
    others = {n for n in case.present if n != case.target}
    for number in others:
        assert (config.data_dir / f"settings.json.corrupt-{number}").read_text() == f"old {number}"
    assert len(_corrupt_files(config)) == len(others | {case.target})
    assert not (config.data_dir / "settings.json.corrupt-21").exists()


def test_a_dangling_symlink_counts_as_a_taken_name(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    _write(config, b"{broken")
    taken = config.data_dir / "settings.json.corrupt-1"
    taken.symlink_to(tmp_path / "nowhere")
    with pytest.raises(SettingsError, match=r"moved to settings\.json\.corrupt-2"):
        SettingsStore(config).load()
    assert taken.is_symlink()
    assert not (tmp_path / "nowhere").exists()  # nothing was written through the link
    assert (config.data_dir / "settings.json.corrupt-2").read_bytes() == b"{broken"


def test_two_corrupt_files_in_a_row_make_two_copies(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    for expected, content in enumerate((b"{one", b"{two"), start=1):
        _write(config, content)
        with pytest.raises(SettingsError, match=f"corrupt-{expected}"):
            store.load()
    assert (config.data_dir / "settings.json.corrupt-1").read_bytes() == b"{one"
    assert (config.data_dir / "settings.json.corrupt-2").read_bytes() == b"{two"


def test_a_failed_move_is_reported_and_leaves_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    _write(config, b"{broken")
    monkeypatch.setattr(
        Path, "replace", _raiser(PermissionError(errno.EACCES, "Permission denied"))
    )
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.message == "Corrupt settings file cannot be moved: Permission denied"
    assert config.settings_file.read_bytes() == b"{broken"


def test_a_failed_chmod_after_the_move_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    _write(config, b"{broken")
    monkeypatch.setattr(
        Path, "chmod", _raiser(PermissionError(errno.EPERM, "Operation not permitted"))
    )
    with pytest.raises(SettingsError, match="cannot be moved: Operation not permitted"):
        SettingsStore(config).load()


# --------------------------------------------------------------------------- unreadable files


def test_a_symlinked_settings_file_is_refused_and_not_moved(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir()
    real = tmp_path / "elsewhere.json"
    real.write_text(json.dumps({"theme": "dark"}))
    config.settings_file.symlink_to(real)
    with pytest.raises(SettingsError) as info:
        SettingsStore(config).load()
    assert info.value.message == "Settings file cannot be read: Too many levels of symbolic links"
    assert config.settings_file.is_symlink()
    assert _corrupt_files(config) == []


def test_a_directory_in_place_of_the_file_is_unreadable_not_corrupt(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir()
    config.settings_file.mkdir()
    with pytest.raises(SettingsError, match="Settings file cannot be read: not a regular file"):
        SettingsStore(config).load()
    assert config.settings_file.is_dir()


def test_the_size_cap_is_one_mebibyte_inclusive(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    body = b'{"theme": "dark"}'
    _write(config, body + b" " * (1024 * 1024 - len(body)))
    assert SettingsStore(config).load().theme == "dark"
    _write(config, body + b" " * (1024 * 1024 - len(body) + 1))
    with pytest.raises(SettingsError, match="cannot be read: the file is too large"):
        SettingsStore(config).load()
    assert config.settings_file.exists()  # too big is not "corrupt": it is left alone


# --------------------------------------------------------------------------- the data directory


def test_a_world_writable_data_directory_is_repaired_on_load(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir()
    config.data_dir.chmod(0o777)
    SettingsStore(config).load()
    assert mode_of(config.data_dir) == 0o755


def test_a_foreign_owned_data_directory_is_refused_on_load_and_on_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    config.data_dir.mkdir()
    monkeypatch.setattr(atomic, "current_uid", lambda: os.getuid() + 1)
    store = SettingsStore(config)
    with pytest.raises(SettingsError) as load_info:
        store.load()
    assert load_info.value.message == (
        "The data directory is not safe: the directory is owned by another user"
    )
    with pytest.raises(SettingsError) as save_info:
        store.save(AppSettings())
    assert save_info.value.message == (
        "Settings could not be saved: the directory is owned by another user"
    )
    assert list(config.data_dir.iterdir()) == []


def test_a_file_in_place_of_the_data_directory_is_refused(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.data_dir.write_text("not a directory")
    with pytest.raises(SettingsError, match="The data directory is not safe: not a directory"):
        SettingsStore(config).load()
    with pytest.raises(SettingsError, match="Settings could not be saved: not a directory"):
        SettingsStore(config).save(AppSettings())


# --------------------------------------------------------------------------- failures while saving


def test_a_failed_write_is_a_settings_error_and_keeps_the_old_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    old = store.save(AppSettings(theme="dark"))
    monkeypatch.setattr(module, "write_atomic", _raiser(OSError(errno.EIO, "disk")))
    with pytest.raises(SettingsError) as info:
        store.save(AppSettings(theme="light"))
    assert info.value.message == "Settings could not be saved: disk"
    monkeypatch.undo()
    assert store.load() is old
    assert json.loads(config.settings_file.read_text())["theme"] == "dark"


def test_an_fsync_failure_leaves_the_old_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(AppSettings(theme="dark"))
    monkeypatch.setattr(
        "sankey_studio.storage.atomic.os.fsync", _raiser(OSError(errno.EIO, "disk"))
    )
    with pytest.raises(SettingsError, match="Settings could not be saved: disk"):
        store.save(AppSettings(theme="light"))
    monkeypatch.undo()
    assert json.loads(config.settings_file.read_text())["theme"] == "dark"
    assert sorted(p.name for p in config.data_dir.iterdir()) == [
        "credentials.json",
        "settings.json",
    ]


def test_a_replace_failure_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    store = SettingsStore(config)
    store.save(AppSettings(theme="dark"))
    monkeypatch.setattr(Path, "replace", _raiser(OSError(errno.EXDEV, "Invalid cross-device link")))
    with pytest.raises(SettingsError, match="Invalid cross-device link"):
        store.save(AppSettings(theme="light"))
    monkeypatch.undo()
    assert sorted(p.name for p in config.data_dir.iterdir()) == [
        "credentials.json",
        "settings.json",
    ]
