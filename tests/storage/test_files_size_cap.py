"""The size cap of a stored graph file: exactly the cap is readable and writable, one more is not.

The write side uses the read cap (``MAX_GRAPH_BYTES``), so a graph that was saved can always be
read back. The boundary tests set the cap to the exact size of a small graph (fast); the real cap
is exercised once at full scale in ``test_files_size_cap_scale.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.storage import FileGraphRepository
from sankey_studio.storage.files import codec
from sankey_studio.storage.files.codec import (
    MAX_GRAPH_BYTES,
    MSG_TOO_LARGE,
    encode_graph,
    graph_filename,
    read_graph,
)
from tests.storage.support import ID_A, Spec, create_data, definition, update_data

if TYPE_CHECKING:
    from pathlib import Path

TOO_LARGE = r"^The graph is too large to save$"


def _padded(tmp_path: Path, size: int) -> Path:
    """A valid graph file whose length is ``size`` bytes (JSON allows trailing whitespace)."""
    body = encode_graph(definition(ID_A))
    path = tmp_path / graph_filename(ID_A)
    path.write_bytes(body + b" " * (size - len(body)))
    return path


def test_the_cap_is_32_mib() -> None:
    assert MAX_GRAPH_BYTES == 32 * 1024 * 1024


@pytest.mark.parametrize(
    ("delta", "readable"),
    [(-1, True), (0, True), (1, False)],
    ids=["below-cap", "at-cap", "above-cap"],
)
def test_the_cap_boundary(tmp_path: Path, delta: int, readable: bool) -> None:
    path = _padded(tmp_path, MAX_GRAPH_BYTES + delta)
    assert path.stat().st_size == MAX_GRAPH_BYTES + delta
    if readable:
        assert read_graph(path).id == ID_A
        return
    with pytest.raises(StorageError, match=r"^Stored graph is unreadable$"):
        read_graph(path)


def test_an_oversized_file_is_skipped_by_the_listing_and_refused_by_get(tmp_path: Path) -> None:
    graphs = tmp_path / "graphs"
    repo = FileGraphRepository(graphs)
    _padded(graphs, MAX_GRAPH_BYTES + 1)
    assert repo.list_graphs() == []
    with pytest.raises(StorageError, match=r"^Stored graph is unreadable$"):
        repo.get(ID_A)


# --------------------------------------------------------------------------- the write side


def _cap_at_base_size(monkeypatch: pytest.MonkeyPatch) -> int:
    """Make the cap exactly the size of the plain test graph; one more byte is then too much."""
    size = len(encode_graph(definition(ID_A)))
    monkeypatch.setattr(codec, "MAX_GRAPH_BYTES", size)
    return size


def _padding(extra: int) -> Spec:
    """``extra`` more bytes than the plain graph (an ASCII description costs one byte a char)."""
    return Spec(description="d" * extra)


def test_the_message_of_a_graph_that_is_too_large() -> None:
    assert MSG_TOO_LARGE == "The graph is too large to save"


@pytest.mark.parametrize(
    ("extra", "fits"), [(0, True), (1, False)], ids=["at-cap", "one-byte-over"]
)
def test_encode_graph_refuses_what_read_graph_would_refuse(
    monkeypatch: pytest.MonkeyPatch, extra: int, fits: bool
) -> None:
    size = _cap_at_base_size(monkeypatch)
    graph = definition(ID_A, spec=_padding(extra))
    if fits:
        assert len(encode_graph(graph)) == size
        return
    with pytest.raises(StorageError, match=TOO_LARGE):
        encode_graph(graph)


@pytest.mark.parametrize("extra", [0, 1], ids=["at-cap", "one-byte-over"])
def test_create_stores_exactly_the_cap_and_refuses_one_byte_more(
    file_repo: FileGraphRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: int
) -> None:
    size = _cap_at_base_size(monkeypatch)
    data = create_data(spec=_padding(extra))
    if extra:
        with pytest.raises(StorageError, match=TOO_LARGE):
            file_repo.create(data)
        assert list((tmp_path / "graphs").iterdir()) == []  # no file, no temp file
        assert file_repo.list_graphs() == []
        assert file_repo.count() == 0
        return
    created = file_repo.create(data)
    assert (tmp_path / "graphs" / graph_filename(created.id)).stat().st_size == size
    assert file_repo.get(created.id) == created  # what was saved can be read back
    assert [row.id for row in file_repo.list_graphs()] == [created.id]


@pytest.mark.parametrize("extra", [0, 1], ids=["at-cap", "one-byte-over"])
def test_put_stores_exactly_the_cap_and_refuses_one_byte_more(
    file_repo: FileGraphRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: int
) -> None:
    size = _cap_at_base_size(monkeypatch)
    graph = definition(ID_A, spec=_padding(extra))
    if extra:
        with pytest.raises(StorageError, match=TOO_LARGE):
            file_repo.put(graph)
        assert list((tmp_path / "graphs").iterdir()) == []
        assert file_repo.list_graphs() == []
        return
    assert file_repo.put(graph) == graph
    assert (tmp_path / "graphs" / graph_filename(ID_A)).stat().st_size == size
    assert file_repo.get(ID_A) == graph


def test_a_too_large_put_over_an_existing_graph_keeps_the_old_file_untouched(
    file_repo: FileGraphRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_repo.put(definition(ID_A, "old"))
    path = tmp_path / "graphs" / graph_filename(ID_A)
    before = path.read_bytes()
    monkeypatch.setattr(codec, "MAX_GRAPH_BYTES", len(before))
    with pytest.raises(StorageError, match=TOO_LARGE):
        file_repo.put(definition(ID_A, "old", _padding(1)), overwrite=True)
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    assert [row.name for row in file_repo.list_graphs()] == ["old"]


@pytest.mark.parametrize("extra", [0, 1], ids=["at-cap", "one-byte-over"])
def test_update_stores_exactly_the_cap_and_refuses_one_byte_more(
    file_repo: FileGraphRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: int
) -> None:
    file_repo.put(definition(ID_A))
    path = tmp_path / "graphs" / graph_filename(ID_A)
    before = path.read_bytes()
    monkeypatch.setattr(codec, "MAX_GRAPH_BYTES", len(before))  # revision 2 has the same length
    data = update_data(1, spec=_padding(extra))
    if extra:
        with pytest.raises(StorageError, match=TOO_LARGE):
            file_repo.update(ID_A, data)
        assert path.read_bytes() == before  # the saved version is still there, byte for byte
        assert file_repo.get(ID_A).revision == 1
        assert [row.revision for row in file_repo.list_graphs()] == [1]
        return
    updated = file_repo.update(ID_A, data)
    assert (updated.revision, path.stat().st_size) == (2, len(before))
    assert file_repo.get(ID_A) == updated
