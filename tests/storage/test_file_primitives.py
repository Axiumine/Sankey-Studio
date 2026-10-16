# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Error numbers, read sizes and the on-disk format of the file primitives."""

from __future__ import annotations

import errno
import json
import math
import os
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.models import Link, ManualSource
from sankey_studio.storage.atomic import ensure_private_dir, read_file_nofollow, write_atomic
from sankey_studio.storage.files.codec import encode_graph, graph_filename
from sankey_studio.storage.files.index import DirectoryIndex
from tests.storage.support import ID_A, definition

if TYPE_CHECKING:
    from pathlib import Path

# --------------------------------------------------------------------------- error numbers


def test_a_regular_file_is_refused_with_enotdir(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x")
    with pytest.raises(NotADirectoryError) as info:
        ensure_private_dir(tmp_path / "f")
    assert info.value.errno == errno.ENOTDIR
    assert info.value.strerror == "not a directory"


def test_running_out_of_temporary_names_is_eexist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".f.json.dead.tmp").write_text("taken")
    monkeypatch.setattr("sankey_studio.storage.atomic.secrets.token_hex", lambda _nbytes: "dead")
    with pytest.raises(FileExistsError) as info:
        write_atomic(tmp_path / "f.json", b"data")
    assert info.value.errno == errno.EEXIST
    assert info.value.strerror == "no free temporary file name"


# --------------------------------------------------------------------------- read size


_REAL_READ = os.read  # ``atomic.os`` is the ``os`` module itself: the spy must not call itself


class _Reads:
    """Replaces ``os.read``: records every requested size and returns at most ``chunk`` bytes."""

    def __init__(self, chunk: int | None) -> None:
        self.chunk = chunk
        self.asked: list[int] = []
        self.got: list[int] = []

    def __call__(self, fd: int, size: int) -> bytes:
        self.asked.append(size)
        data = _REAL_READ(fd, size if self.chunk is None else min(size, self.chunk))
        self.got.append(len(data))
        return data


class Limit(NamedTuple):
    limit: int
    file_size: int


@pytest.mark.parametrize("case", [Limit(0, 50), Limit(1, 50), Limit(7, 8), Limit(7, 50)])
def test_a_too_large_file_is_never_read_beyond_the_limit_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: Limit
) -> None:
    path = tmp_path / "big"
    path.write_bytes(b"x" * case.file_size)
    reads = _Reads(None)
    monkeypatch.setattr("sankey_studio.storage.atomic.os.read", reads)
    with pytest.raises(OSError, match="too large") as info:
        read_file_nofollow(path, case.limit)
    assert info.value.errno == errno.EFBIG
    assert reads.asked == [case.limit + 1]
    assert reads.got == [case.limit + 1]


class Short(NamedTuple):
    """A read in pieces of ``chunk`` bytes: what ``os.read`` is asked and how much it returns."""

    file_size: int
    limit: int
    chunk: int
    asked: list[int]
    got: list[int]
    ok: bool


@pytest.mark.parametrize(
    "case",
    [
        Short(10, 10, 3, [11, 8, 5, 2, 1], [3, 3, 3, 1, 0], True),
        Short(10, 10, 100, [11, 1], [10, 0], True),
        Short(4, 10, 3, [11, 8, 7], [3, 1, 0], True),
        Short(0, 10, 3, [11], [0], True),
        Short(11, 10, 3, [11, 8, 5, 2], [3, 3, 3, 2], False),
        Short(50, 10, 3, [11, 8, 5, 2], [3, 3, 3, 2], False),
        Short(50, 10, 1, [11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1], [1] * 11, False),
    ],
)
def test_a_read_in_pieces_is_reassembled_and_stops_at_the_limit_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: Short
) -> None:
    content = bytes(range(65, 65 + case.file_size))
    path = tmp_path / "f"
    path.write_bytes(content)
    reads = _Reads(case.chunk)
    monkeypatch.setattr("sankey_studio.storage.atomic.os.read", reads)
    if case.ok:
        assert read_file_nofollow(path, case.limit) == content
    else:
        with pytest.raises(OSError, match="too large") as info:
            read_file_nofollow(path, case.limit)
        assert info.value.errno == errno.EFBIG
    assert reads.asked == case.asked
    assert reads.got == case.got


# --------------------------------------------------------------------------- graph file format


def test_a_graph_file_is_two_space_indented_ascii_json() -> None:
    graph = definition(ID_A, "Café")
    data = encode_graph(graph)
    lines = data.split(b"\n")
    assert lines[0] == b"{"
    assert lines[1].startswith(b'  "')
    assert not lines[1].startswith(b"   ")
    assert b'"name": "Caf\\u00e9"' in data
    assert data.isascii()
    assert json.loads(data) == graph.model_dump(mode="json")


def test_a_lone_surrogate_is_escaped_not_encoded() -> None:
    graph = definition(ID_A).model_copy(update={"name": "a\ud800b"})  # unvalidated, as a bug would
    data = encode_graph(graph)
    assert data.isascii()
    assert b'"name": "a\\ud800b"' in data
    assert json.loads(data)["name"] == "a\ud800b"


def test_a_non_finite_number_is_refused_instead_of_written_as_nan() -> None:
    link = Link.model_construct(source="a", target="b", value=math.nan, category=None)
    source = ManualSource.model_construct(type="manual", links=[link])
    graph = definition(ID_A).model_copy(update={"source": source})
    with pytest.raises(ValueError, match="not JSON compliant"):
        encode_graph(graph)


# --------------------------------------------------------------------------- directory index


def test_a_damaged_file_that_is_deleted_leaves_no_trace(tmp_path: Path) -> None:
    damaged = tmp_path / graph_filename(ID_A)
    damaged.write_text("{not json")
    index = DirectoryIndex(tmp_path)
    assert index.select(None, None) == []
    damaged.unlink()
    assert index.select(None, None) == []
    assert index.tags() == []
