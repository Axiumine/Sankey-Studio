# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``open_binary`` and ``BoundedReader``: size caps, growth, read errors and closing."""

from __future__ import annotations

import errno
import io
import os
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import SourceError, UnsafeSourceError
from sankey_studio.sources.files.paths import (
    MIB,
    UNLIMITED,
    BoundedReader,
    format_limit,
    open_binary,
)
from tests.sources.text_support import open_fd_count

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    return root


def test_constants() -> None:
    assert MIB == 1024 * 1024
    assert UNLIMITED > 2**40


class Limit(NamedTuple):
    size: int
    text: str


LIMITS = [
    Limit(MIB, "1 MB"),
    Limit(25 * MIB, "25 MB"),
    Limit(100 * MIB, "100 MB"),
    Limit(0, "0 MB"),
    Limit(MIB + 1, "1048577 bytes"),
    Limit(MIB - 1, "1048575 bytes"),
    Limit(10, "10 bytes"),
    Limit(MIB // 2, "524288 bytes"),
]


@pytest.mark.parametrize("case", LIMITS, ids=[c.text for c in LIMITS])
def test_format_limit(case: Limit) -> None:
    assert format_limit(case.size) == case.text


def test_open_binary_reads_the_whole_file(text_root: Path) -> None:
    (text_root / "a.csv").write_bytes(b"hello\nworld\n")
    with open_binary(text_root, "a.csv") as stream:
        assert stream.read() == b"hello\nworld\n"


def test_open_binary_with_a_limit_equal_to_the_size_reads_everything(text_root: Path) -> None:
    (text_root / "a.csv").write_bytes(b"x" * 100)
    with open_binary(text_root, "a.csv", 100) as stream:
        assert stream.read() == b"x" * 100


def test_open_binary_refuses_a_file_over_the_limit_up_front(text_root: Path) -> None:
    (text_root / "a.csv").write_bytes(b"x" * 101)
    before = open_fd_count()
    with pytest.raises(SourceError) as info:
        open_binary(text_root, "a.csv", 100)
    assert str(info.value) == "a.csv: file is larger than 100 bytes"
    assert open_fd_count() == before


def test_open_binary_names_whole_megabytes(text_root: Path) -> None:
    (text_root / "a.csv").write_bytes(b"x" * (MIB + 1))
    with pytest.raises(SourceError, match=r"^a\.csv: file is larger than 1 MB$"):
        open_binary(text_root, "a.csv", MIB)


def test_open_binary_applies_every_path_check(text_root: Path) -> None:
    with pytest.raises(UnsafeSourceError):
        open_binary(text_root, "../a.csv")
    with pytest.raises(UnsafeSourceError):
        open_binary(text_root, "a.exe")


def test_a_file_that_grows_after_the_check_is_cut_off(text_root: Path) -> None:
    path = text_root / "a.csv"
    path.write_bytes(b"x" * 10)
    stream = open_binary(text_root, "a.csv", 10)
    with path.open("ab") as handle:
        handle.write(b"y")
    try:
        with pytest.raises(SourceError) as info:
            stream.read()
        assert str(info.value) == "a.csv: file is larger than 10 bytes"
    finally:
        stream.close()


def test_a_file_that_grows_but_stays_within_the_limit_is_read_fully(text_root: Path) -> None:
    path = text_root / "a.csv"
    path.write_bytes(b"x" * 10)
    with open_binary(text_root, "a.csv", 12) as stream:
        with path.open("ab") as handle:
            handle.write(b"yy")
        assert stream.read() == b"x" * 10 + b"yy"


def test_closing_the_reader_closes_the_descriptor_once(text_root: Path) -> None:
    (text_root / "a.csv").write_bytes(b"abc")
    before = open_fd_count()
    stream = open_binary(text_root, "a.csv")
    assert open_fd_count() == before + 1
    stream.close()
    assert open_fd_count() == before
    stream.close()  # idempotent: must not close an unrelated descriptor
    assert open_fd_count() == before


def test_text_wrapping_closes_the_descriptor(text_root: Path) -> None:
    (text_root / "a.csv").write_bytes(b"abc")
    before = open_fd_count()
    with io.TextIOWrapper(open_binary(text_root, "a.csv"), encoding="utf-8") as text:
        assert text.read() == "abc"
    assert open_fd_count() == before


def test_bounded_reader_is_a_readable_non_seekable_raw_stream(text_root: Path) -> None:
    path = text_root / "a.csv"
    path.write_bytes(b"abcdef")
    fd = os.open(path, os.O_RDONLY)
    reader = BoundedReader(fd, 100, "a.csv")
    try:
        assert reader.readable()
        assert not reader.seekable()
        assert not reader.writable()
        buffer = bytearray(4)
        assert reader.readinto(buffer) == 4
        assert bytes(buffer) == b"abcd"
        assert reader.readinto(buffer) == 2
        assert bytes(buffer[:2]) == b"ef"
        assert reader.readinto(buffer) == 0
    finally:
        reader.close()


def test_bounded_reader_allows_exactly_the_limit_and_refuses_one_more(text_root: Path) -> None:
    path = text_root / "a.csv"
    path.write_bytes(b"abcde")
    fd = os.open(path, os.O_RDONLY)
    reader = BoundedReader(fd, 4, "a.csv")
    try:
        buffer = bytearray(4)
        assert reader.readinto(buffer) == 4  # 4 of 4 allowed
        with pytest.raises(SourceError, match=r"^a\.csv: file is larger than 4 bytes$"):
            reader.readinto(buffer)  # the 5th byte
    finally:
        reader.close()


def test_a_read_error_is_a_source_error_without_the_os_text(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (text_root / "a.csv").write_bytes(b"abc")
    stream = open_binary(text_root, "a.csv")

    def boom(_fd: int, _size: int) -> bytes:
        raise OSError(errno.EIO, "secret os detail")

    monkeypatch.setattr(os, "read", boom)
    try:
        with pytest.raises(SourceError) as info:
            stream.read()
        assert str(info.value) == "a.csv: cannot be read"
    finally:
        monkeypatch.undo()
        stream.close()


def test_closing_a_bounded_reader_twice_closes_its_descriptor_once(text_root: Path) -> None:
    path = text_root / "a.csv"
    path.write_bytes(b"abc")
    before = open_fd_count()
    reader = BoundedReader(os.open(path, os.O_RDONLY), 100, "a.csv")
    assert open_fd_count() == before + 1
    reader.close()
    assert reader.closed
    assert open_fd_count() == before
    keep = os.open(path, os.O_RDONLY)  # a new descriptor may reuse the number just freed
    try:
        reader.close()
        os.fstat(keep)  # still open: the second close did not touch it
    finally:
        os.close(keep)
