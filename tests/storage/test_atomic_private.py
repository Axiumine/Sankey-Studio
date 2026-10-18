# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``read_private_file``: ``read_file_nofollow`` plus the owner and mode rules of a secrets file."""

from __future__ import annotations

import contextlib
import errno
import os
import stat
from pathlib import Path
from typing import NamedTuple

import pytest

from sankey_studio.storage import atomic
from sankey_studio.storage.atomic import read_private_file


def _file(tmp_path: Path, mode: int, content: bytes = b"data") -> Path:
    path = tmp_path / "secret.json"
    path.write_bytes(content)
    path.chmod(mode)
    return path


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _open_descriptors() -> int:
    return len(list(Path("/proc/self/fd").iterdir()))


class Fix(NamedTuple):
    before: int
    after: int


@pytest.mark.parametrize(
    "case",
    [
        Fix(0o600, 0o600),
        Fix(0o400, 0o400),
        Fix(0o700, 0o700),
        Fix(0o500, 0o500),
        Fix(0o644, 0o600),
        Fix(0o640, 0o600),
        Fix(0o604, 0o600),
        Fix(0o660, 0o600),
        Fix(0o606, 0o600),
        Fix(0o750, 0o600),
        Fix(0o777, 0o600),
        Fix(0o444, 0o400),
        Fix(0o440, 0o400),
        Fix(0o404, 0o400),
    ],
    ids=lambda c: f"{c.before:o}-to-{c.after:o}",
)
def test_group_and_other_bits_are_dropped_and_the_owner_bits_kept(
    tmp_path: Path, case: Fix
) -> None:
    path = _file(tmp_path, case.before)
    assert read_private_file(path, 100) == b"data"
    assert _mode(path) == case.after


class Size(NamedTuple):
    size: int
    limit: int
    ok: bool


@pytest.mark.parametrize(
    "case",
    [
        Size(0, 10, True),
        Size(9, 10, True),
        Size(10, 10, True),
        Size(11, 10, False),
        Size(100, 10, False),
    ],
)
def test_the_size_cap_is_inclusive(tmp_path: Path, case: Size) -> None:
    path = _file(tmp_path, 0o600, b"x" * case.size)
    if case.ok:
        assert read_private_file(path, case.limit) == b"x" * case.size
        return
    with pytest.raises(OSError, match="too large") as info:
        read_private_file(path, case.limit)
    assert info.value.errno == errno.EFBIG


def test_a_missing_file_is_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_private_file(tmp_path / "missing", 10)


@pytest.mark.parametrize("target", ["real", "nowhere"], ids=["symlink", "dangling-symlink"])
def test_a_symlink_is_refused(tmp_path: Path, target: str) -> None:
    (tmp_path / "real").write_text("secret")
    (tmp_path / "link").symlink_to(tmp_path / target)
    with pytest.raises(OSError, match="symbolic links") as info:
        read_private_file(tmp_path / "link", 100)
    assert info.value.errno == errno.ELOOP


def test_a_directory_is_not_a_regular_file(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    with pytest.raises(OSError, match="not a regular file") as info:
        read_private_file(tmp_path / "d", 100)
    assert info.value.errno == errno.EINVAL


def test_a_fifo_is_refused_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(OSError, match="not a regular file"):
        read_private_file(tmp_path / "pipe", 100)


def test_a_file_of_another_user_is_refused_and_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _file(tmp_path, 0o644)
    monkeypatch.setattr(atomic, "current_uid", lambda: os.getuid() + 1)
    with pytest.raises(OSError, match="the file is owned by another user") as info:
        read_private_file(path, 100)
    assert info.value.errno == errno.EPERM
    assert _mode(path) == 0o644  # not even the permissions were touched


def test_a_failed_fchmod_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _file(tmp_path, 0o644)

    def refuse(*_args: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr("sankey_studio.storage.atomic.os.fchmod", refuse)
    with pytest.raises(OSError, match="Operation not permitted"):
        read_private_file(path, 100)
    assert _mode(path) == 0o644


@pytest.mark.parametrize("kind", ["ok", "too large", "directory", "foreign", "loose"])
def test_the_descriptor_is_closed_on_every_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    size = 20 if kind == "too large" else 4
    path = _file(tmp_path, 0o644 if kind == "loose" else 0o600, b"x" * size)
    if kind == "directory":
        path = tmp_path
    if kind == "foreign":
        monkeypatch.setattr(atomic, "current_uid", lambda: os.getuid() + 1)
    before = _open_descriptors()
    with contextlib.suppress(OSError):
        read_private_file(path, 10)
    assert _open_descriptors() == before
