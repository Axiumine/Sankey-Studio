# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``save_stream`` under OS failures: StorageError, no leftovers, no leaked descriptors."""

from __future__ import annotations

import errno
import io
import os
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.sources.files import SaveRequest, save_stream
from tests.sources.text_support import open_fd_count

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

MESSAGE = "the upload could not be stored"


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    return root


def upload(root: Path, *, overwrite: bool = False) -> None:
    save_stream(SaveRequest(root, "a.csv", 1000, overwrite), io.BytesIO(b"data"))


def raising(error: OSError) -> Callable[..., Any]:
    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return fail


class Failing(NamedTuple):
    target: str
    overwrite: bool


FAILING = [
    Failing("os.fsync", False),
    Failing("os.link", False),
    Failing("os.replace", True),
    Failing("os.listdir", False),
]


@pytest.mark.parametrize("case", FAILING, ids=[c.target for c in FAILING])
def test_an_os_failure_is_a_storage_error_without_leftovers(
    text_root: Path, monkeypatch: pytest.MonkeyPatch, case: Failing
) -> None:
    before = open_fd_count()
    monkeypatch.setattr(case.target, raising(OSError(errno.EIO, "secret os detail")))
    with pytest.raises(StorageError) as info:
        upload(text_root, overwrite=case.overwrite)
    monkeypatch.undo()
    assert str(info.value) == MESSAGE
    assert info.value.status_code == 503
    assert not [p for p in text_root.iterdir() if p.name.endswith(".part")]
    assert open_fd_count() == before


def test_a_failing_stat_after_the_link_leaves_the_published_file(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if kwargs.get("dir_fd") is not None:
            raise OSError(errno.EIO, "x")
        return real(path, *args, **kwargs)

    monkeypatch.setattr("os.stat", stat)
    with pytest.raises(StorageError):
        upload(text_root)
    monkeypatch.undo()
    assert [p.name for p in text_root.iterdir()] == ["a.csv"]


def test_a_failing_open_of_the_directory_is_a_storage_error(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("os.open", raising(PermissionError(errno.EACCES, "denied")))
    with pytest.raises(StorageError, match=f"^{MESSAGE}$"):
        upload(text_root)


def test_a_failing_mkdir_is_a_storage_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    with pytest.raises(StorageError, match=f"^{MESSAGE}$"):
        upload(blocker / "sources")


def test_a_failing_part_file_open_is_a_storage_error(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.open

    def deny_part(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if str(path).endswith(".part"):
            raise PermissionError(errno.EACCES, "denied")
        return real(path, flags, *args, **kwargs)

    before = open_fd_count()
    monkeypatch.setattr("os.open", deny_part)
    with pytest.raises(StorageError, match=f"^{MESSAGE}$"):
        upload(text_root)
    monkeypatch.undo()
    assert list(text_root.iterdir()) == []
    assert open_fd_count() == before


def test_a_failing_read_of_the_upload_is_a_storage_error(text_root: Path) -> None:
    class Broken(io.BytesIO):
        def read(self, _size: int | None = -1, /) -> bytes:
            raise OSError(errno.ECONNRESET, "client went away")

    with pytest.raises(StorageError, match=f"^{MESSAGE}$"):
        save_stream(SaveRequest(text_root, "a.csv", 1000), Broken())
    assert list(text_root.iterdir()) == []


def test_a_temporary_file_that_cannot_be_removed_does_not_fail_a_good_upload(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("os.unlink", raising(PermissionError(errno.EACCES, "denied")))
    upload(text_root)
    monkeypatch.undo()
    names = sorted(p.name for p in text_root.iterdir())
    assert "a.csv" in names
    assert (text_root / "a.csv").read_bytes() == b"data"


def test_the_error_never_carries_the_os_detail(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("os.fsync", raising(OSError(errno.EIO, f"leak {text_root}")))
    with pytest.raises(StorageError) as info:
        upload(text_root)
    assert str(text_root) not in str(info.value)
    assert info.value.__cause__ is None
