"""Error numbers, read sizes and the on-disk format of the file primitives."""

from __future__ import annotations

import errno
import json
import math
import os
from typing import IO, TYPE_CHECKING, Any, NamedTuple, Self

import pytest

from sankey_studio.models import Link, ManualSource
from sankey_studio.storage.atomic import ensure_private_dir, read_file_nofollow, write_atomic
from sankey_studio.storage.files.codec import encode_graph, graph_filename
from sankey_studio.storage.files.index import DirectoryIndex
from tests.storage.support import ID_A, definition

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

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


class _SpyHandle:
    """Wraps a real binary file and records every ``read`` size."""

    def __init__(self, inner: IO[Any], sizes: list[int | None]) -> None:
        self._inner = inner
        self._sizes = sizes

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._inner.__exit__(kind, value, trace)

    def read(self, size: int | None = None) -> bytes:
        self._sizes.append(size)
        data: bytes = self._inner.read(-1 if size is None else size)
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
    sizes: list[int | None] = []
    real = os.fdopen

    def spying(fd: int, mode: str, **kwargs: Any) -> _SpyHandle:
        return _SpyHandle(real(fd, mode, **kwargs), sizes)

    monkeypatch.setattr("sankey_studio.storage.atomic.os.fdopen", spying)
    with pytest.raises(OSError, match="too large") as info:
        read_file_nofollow(path, case.limit)
    assert info.value.errno == errno.EFBIG
    assert sizes == [case.limit + 1]


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
