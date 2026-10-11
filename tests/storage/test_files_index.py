"""``DirectoryIndex``: stat-validated listing cache of one graphs directory."""

from __future__ import annotations

import errno
import logging
import os
import stat
import types
from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.storage.atomic import write_atomic
from sankey_studio.storage.files import index as index_module
from sankey_studio.storage.files.codec import encode_graph, graph_filename
from sankey_studio.storage.files.index import DirectoryIndex, IndexEntry, entry_of, matches
from tests.storage.support import ID_A, ID_B, ID_C, NOW, Reads, Spec, definition

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.models import GraphDefinition


def _signature_of(path: Path) -> tuple[int, int, int]:
    info = path.stat()
    return (info.st_mtime_ns, info.st_size, info.st_ino)


def _store(directory: Path, graph: GraphDefinition) -> None:
    write_atomic(directory / graph_filename(graph.id), encode_graph(graph))


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Reads:
    return Reads(monkeypatch)


# --------------------------------------------------------------------------- matching


class Match(NamedTuple):
    term: str | None
    tag: str | None
    expected: bool


ENTRY = entry_of(definition(ID_A, "Straße Plan", spec=Spec("Quarterly REPORT", ("Alpha", "beta"))))


@pytest.mark.parametrize(
    "case",
    [
        Match(None, None, True),
        Match("strasse", None, True),  # case folding, not just lower()
        Match("STRASSE PLAN", None, True),
        Match("report", None, True),
        Match("alp", None, True),
        Match("BETA", None, True),
        Match("gamma", None, False),
        Match("plan quarterly", None, False),  # fields are searched one by one
        Match(None, "Alpha", True),
        Match(None, "alpha", False),  # tags are exact and case-sensitive
        Match(None, "Alph", False),
        Match(None, "", True),
        Match("report", "beta", True),
        Match("report", "gamma", False),
        Match("gamma", "beta", False),
    ],
)
def test_matches(case: Match) -> None:
    assert matches(ENTRY, case.term, case.tag) is case.expected


def test_an_entry_holds_the_summary_and_the_folded_search_fields() -> None:
    assert isinstance(ENTRY, IndexEntry)
    assert ENTRY.summary.id == ID_A
    assert ENTRY.folded == ("strasse plan", "quarterly report", "alpha", "beta")


# --------------------------------------------------------------------------- refresh


def test_refresh_picks_up_additions_changes_and_removals(tmp_path: Path) -> None:
    index = DirectoryIndex(tmp_path)
    assert index.select(None, None) == []
    _store(tmp_path, definition(ID_A, "one"))
    _store(tmp_path, definition(ID_B, "two"))
    assert [s.name for s in index.select(None, None)] == ["one", "two"]
    _store(tmp_path, definition(ID_A, "one renamed", Spec(updated_at=NOW + timedelta(days=1))))
    assert [s.name for s in index.select(None, None)] == ["one renamed", "two"]
    (tmp_path / graph_filename(ID_B)).unlink()
    assert [s.name for s in index.select(None, None)] == ["one renamed"]
    assert index.tags() == []


def test_only_changed_files_are_parsed_again(tmp_path: Path, reads: Reads) -> None:
    index = DirectoryIndex(tmp_path)
    for graph_id in (ID_A, ID_B, ID_C):
        _store(tmp_path, definition(graph_id, graph_id[0]))
    index.select(None, None)
    assert sorted(reads.paths) == sorted(graph_filename(i) for i in (ID_A, ID_B, ID_C))
    reads.paths.clear()
    index.select(None, None)
    index.tags()
    assert reads.paths == []
    _store(tmp_path, definition(ID_B, "b changed"))
    index.select(None, None)
    assert reads.paths == [graph_filename(ID_B)]


def test_a_rewrite_with_the_same_size_and_time_is_still_noticed(tmp_path: Path) -> None:
    """Atomic replace gives the file a new inode, which is part of the signature."""
    index = DirectoryIndex(tmp_path)
    _store(tmp_path, definition(ID_A, "aaaa"))
    index.select(None, None)
    path = tmp_path / graph_filename(ID_A)
    before = path.stat()
    _store(tmp_path, definition(ID_A, "bbbb"))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # same mtime, same size
    assert path.stat().st_size == before.st_size
    assert [s.name for s in index.select(None, None)] == ["bbbb"]


def test_remember_writes_through_without_a_rescan(tmp_path: Path, reads: Reads) -> None:
    index = DirectoryIndex(tmp_path)
    graph = definition(ID_A, "mine", spec=Spec(tags=("t",)))
    _store(tmp_path, graph)
    index.remember(graph)
    assert [s.name for s in index.select(None, None)] == ["mine"]
    assert reads.paths == []  # the write-through entry matched the file's signature
    assert index._entries[ID_A].summary.name == "mine"
    assert index._signatures[ID_A] == _signature_of(tmp_path / graph_filename(ID_A))


def test_select_orders_by_time_then_id_and_filters(tmp_path: Path) -> None:
    index = DirectoryIndex(tmp_path)
    for graph_id, stamp in [(ID_C, NOW), (ID_A, NOW), (ID_B, NOW + timedelta(seconds=1))]:
        _store(tmp_path, definition(graph_id, f"g{graph_id[0]}", Spec(updated_at=stamp)))
    assert [s.id for s in index.select(None, None)] == [ID_B, ID_A, ID_C]
    assert [s.id for s in index.select("ga", None)] == [ID_A]
    assert [s.id for s in index.select("G", "nope")] == []


def test_tags_are_distinct_and_sorted(tmp_path: Path) -> None:
    index = DirectoryIndex(tmp_path)
    _store(tmp_path, definition(ID_A, "a", spec=Spec(tags=("b", "a"))))
    _store(tmp_path, definition(ID_B, "b", spec=Spec(tags=("a", "C"))))
    assert index.tags() == ["C", "a", "b"]


# --------------------------------------------------------------------------- damaged files


def test_a_damaged_file_is_warned_about_once_per_version(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    index = DirectoryIndex(tmp_path)
    bad = tmp_path / graph_filename(ID_A)
    bad.write_text("{broken")
    with caplog.at_level(logging.WARNING):
        assert index.select(None, None) == []
        assert index.select(None, None) == []
        assert len(caplog.records) == 1
        write_atomic(bad, b"{still broken")
        assert index.select(None, None) == []
    assert [r.getMessage() for r in caplog.records] == [
        f"Skipping unreadable stored graph {ID_A}"
    ] * 2


def test_a_good_file_that_turns_bad_leaves_the_listing(tmp_path: Path) -> None:
    index = DirectoryIndex(tmp_path)
    _store(tmp_path, definition(ID_A, "fine"))
    assert len(index.select(None, None)) == 1
    write_atomic(tmp_path / graph_filename(ID_A), b"{broken")
    assert index.select(None, None) == []


def test_a_bad_file_that_is_repaired_joins_the_listing(tmp_path: Path) -> None:
    index = DirectoryIndex(tmp_path)
    (tmp_path / graph_filename(ID_A)).write_text("{broken")
    assert index.select(None, None) == []
    _store(tmp_path, definition(ID_A, "fixed"))
    assert [s.name for s in index.select(None, None)] == ["fixed"]


def test_a_file_that_vanishes_before_it_is_read_is_skipped_quietly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    index = DirectoryIndex(tmp_path)
    _store(tmp_path, definition(ID_A, "a"))

    def gone(_path: Path) -> GraphDefinition:
        raise FileNotFoundError

    monkeypatch.setattr(index_module, "read_graph", gone)
    with caplog.at_level(logging.WARNING):
        assert index.select(None, None) == []
    assert caplog.records == []


# --------------------------------------------------------------------------- the scan itself


class _Item:
    """A ``DirEntry`` stand-in."""

    def __init__(self, name: str, error: OSError | None = None) -> None:
        self.name = name
        self._error = error

    def stat(self, *, follow_symlinks: bool) -> types.SimpleNamespace:
        assert follow_symlinks is False  # a symlink is looked at, never followed
        if self._error is not None:
            raise self._error
        return types.SimpleNamespace(
            st_mode=stat.S_IFREG | 0o644, st_mtime_ns=5, st_size=10, st_ino=7
        )


class _FakeScandir:
    def __init__(self, items: list[_Item]) -> None:
        self.items = items

    def __enter__(self) -> list[_Item]:
        return self.items

    def __exit__(self, *_exc: object) -> None:
        return None


def test_a_file_deleted_during_the_scan_is_not_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = [_Item(graph_filename(ID_A), FileNotFoundError()), _Item(graph_filename(ID_B))]
    fake = types.SimpleNamespace(scandir=lambda _path: _FakeScandir(items))
    monkeypatch.setattr(index_module, "os", fake)
    assert DirectoryIndex(tmp_path)._scan() == {ID_B: (5, 10, 7)}


def test_other_stat_errors_fail_the_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = [_Item(graph_filename(ID_A), PermissionError(errno.EACCES, "denied"))]
    fake = types.SimpleNamespace(scandir=lambda _path: _FakeScandir(items))
    monkeypatch.setattr(index_module, "os", fake)
    with pytest.raises(PermissionError):
        DirectoryIndex(tmp_path)._scan()


def test_a_missing_directory_is_a_storage_error(tmp_path: Path) -> None:
    with pytest.raises(StorageError) as info:
        DirectoryIndex(tmp_path / "missing").select(None, None)
    assert info.value.message == "The graphs directory cannot be listed"
    assert isinstance(info.value.__cause__, FileNotFoundError)
