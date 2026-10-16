# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``save_stream`` accepts any ``IO[bytes]``: the upload route passes a ``SpooledTemporaryFile``."""

from __future__ import annotations

from contextlib import contextmanager
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import PayloadTooLargeError
from sankey_studio.sources.files import SaveRequest, list_files, save_stream
from sankey_studio.sources.files.store import CHUNK_BYTES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    return tmp_path / "sources"


@contextmanager
def spooled(data: bytes, max_size: int) -> Iterator[SpooledTemporaryFile[bytes]]:
    """A spooled upload holding ``data``, rewound like the web layer hands it over.

    Typed as the concrete class on purpose: mypy checks that ``save_stream`` takes it.
    """
    with SpooledTemporaryFile[bytes](max_size=max_size) as stream:
        stream.write(data)
        stream.seek(0)
        yield stream


class Spool(NamedTuple):
    size: int
    max_size: int  # data larger than this makes the stream roll over from memory to a real file


SPOOLS = [
    Spool(3, 1000),  # stays in memory
    Spool(1000, 1000),  # exactly at the rollover limit: still in memory
    Spool(1001, 1000),  # one byte over: rolled over to disk
    Spool(CHUNK_BYTES + 5, 16),  # on disk and read in two chunks
]


@pytest.mark.parametrize("case", SPOOLS, ids=["memory", "limit", "limit+1", "two-chunks"])
def test_a_spooled_temporary_file_is_stored_whole(text_root: Path, case: Spool) -> None:
    data = bytes(index % 251 for index in range(case.size))
    with spooled(data, case.max_size) as stream:
        info = save_stream(SaveRequest(text_root, "up.csv", CHUNK_BYTES * 2), stream)
    assert (info.name, info.size) == ("up.csv", case.size)
    assert (text_root / "up.csv").read_bytes() == data
    assert [stored.name for stored in list_files(text_root)] == ["up.csv"]


def test_the_stream_is_read_from_its_current_position(text_root: Path) -> None:
    with spooled(b"headbody", 1000) as stream:
        stream.seek(4)
        save_stream(SaveRequest(text_root, "up.csv", 100), stream)
    assert (text_root / "up.csv").read_bytes() == b"body"


@pytest.mark.parametrize("size", [100, 101], ids=["max_bytes", "max_bytes+1"])
def test_the_size_cap_applies_to_a_spooled_file(text_root: Path, size: int) -> None:
    with spooled(b"x" * size, 50) as stream:
        if size <= 100:
            assert save_stream(SaveRequest(text_root, "up.csv", 100), stream).size == size
            return
        with pytest.raises(PayloadTooLargeError):
            save_stream(SaveRequest(text_root, "up.csv", 100), stream)
    assert list(text_root.iterdir()) == []


def test_the_caller_keeps_the_stream_open(text_root: Path) -> None:
    with spooled(b"abc", 1000) as stream:
        save_stream(SaveRequest(text_root, "up.csv", 100), stream)
        assert not stream.closed
