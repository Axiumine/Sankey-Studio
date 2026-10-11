"""``storage.atomic``: short writes and reads, and every descriptor closed exactly once."""

from __future__ import annotations

import errno
import os
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.storage.atomic import read_file_nofollow, write_atomic

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _raiser(error: OSError) -> Callable[..., Any]:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    return fail


_REAL_WRITE = os.write  # ``atomic.os`` is the ``os`` module itself: the spy must not call itself


def test_a_short_write_is_continued_until_all_the_data_is_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[int] = []

    def three_bytes_at_a_time(fd: int, data: bytes) -> int:
        asked.append(len(data))
        return _REAL_WRITE(fd, bytes(data[:3]))

    monkeypatch.setattr("sankey_studio.storage.atomic.os.write", three_bytes_at_a_time)
    target = tmp_path / "f.json"
    write_atomic(target, b"0123456789")
    assert target.read_bytes() == b"0123456789"
    assert asked == [10, 7, 4, 1]


def test_an_empty_file_is_written_without_a_write_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sankey_studio.storage.atomic.os.write", _raiser(OSError(errno.EIO, "must not write"))
    )
    target = tmp_path / "f.json"
    write_atomic(target, b"")
    assert target.read_bytes() == b""


class _Descriptors:
    """Every descriptor ``os.open`` hands out and every ``os.close`` call, in order."""

    def __init__(self) -> None:
        self.opened: list[int] = []
        self.closed: list[int] = []

    def assert_each_closed_exactly_once(self) -> None:
        assert self.opened
        assert sorted(self.closed) == sorted(self.opened)


@pytest.fixture
def descriptors(monkeypatch: pytest.MonkeyPatch) -> _Descriptors:
    log = _Descriptors()
    real_open, real_close = os.open, os.close

    def opening(*args: Any, **kwargs: Any) -> int:
        fd: int = real_open(*args, **kwargs)
        log.opened.append(fd)
        return fd

    def closing(fd: int) -> None:
        log.closed.append(fd)
        real_close(fd)

    monkeypatch.setattr("sankey_studio.storage.atomic.os.open", opening)
    monkeypatch.setattr("sankey_studio.storage.atomic.os.close", closing)
    return log


class Fault(NamedTuple):
    target: str
    error: OSError


@pytest.mark.parametrize(
    "fault",
    [
        Fault("sankey_studio.storage.atomic.os.write", OSError(errno.ENOSPC, "full")),
        Fault("sankey_studio.storage.atomic.os.fsync", OSError(errno.EIO, "disk")),
        Fault("pathlib.Path.replace", PermissionError(errno.EACCES, "denied")),
    ],
)
def test_a_failed_write_closes_the_descriptor_once_and_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, descriptors: _Descriptors, fault: Fault
) -> None:
    monkeypatch.setattr(fault.target, _raiser(fault.error))
    with pytest.raises(OSError, match=str(fault.error.strerror)):
        write_atomic(tmp_path / "f.json", b"data")
    descriptors.assert_each_closed_exactly_once()
    assert list(tmp_path.iterdir()) == []


def test_a_write_closes_its_descriptors_once(tmp_path: Path, descriptors: _Descriptors) -> None:
    write_atomic(tmp_path / "f.json", b"data")
    assert len(descriptors.opened) == 2  # the temporary file and the directory
    descriptors.assert_each_closed_exactly_once()


def test_a_read_closes_its_descriptor_once(tmp_path: Path, descriptors: _Descriptors) -> None:
    (tmp_path / "f").write_bytes(b"data")
    assert read_file_nofollow(tmp_path / "f", 10) == b"data"
    assert len(descriptors.opened) == 1
    descriptors.assert_each_closed_exactly_once()


@pytest.mark.parametrize("kind", ["too large", "directory", "unreadable"])
def test_a_failed_read_closes_the_descriptor_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, descriptors: _Descriptors, kind: str
) -> None:
    path = tmp_path / "f"
    if kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" * 20)
    if kind == "unreadable":
        monkeypatch.setattr(
            "sankey_studio.storage.atomic.os.read", _raiser(OSError(errno.EIO, "disk"))
        )
    with pytest.raises(OSError, match=r"."):
        read_file_nofollow(path, 10)
    assert len(descriptors.opened) == 1
    descriptors.assert_each_closed_exactly_once()
