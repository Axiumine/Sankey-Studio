# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``FolderFile``: the folders file, its format, its cache and its failure modes."""

from __future__ import annotations

import errno
import json
import logging
import os
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.models import FOLDERS_MAX
from sankey_studio.storage.atomic import read_file_nofollow
from sankey_studio.storage.files import folder_file as ff
from sankey_studio.storage.files.folder_file import FOLDERS_FILENAME, FolderFile
from sankey_studio.storage.files.index import _FILE_RE
from tests.storage.folder_builders import fid, folder
from tests.storage.support import mode_of

if TYPE_CHECKING:
    from pathlib import Path

WARNING = "The collections file is unreadable"
DAMAGED = "The collections file is unreadable; fix or remove it (graphs are not affected)"


def _record(number: int = 1, **changes: Any) -> dict[str, Any]:
    return {**folder(number, f"f{number}").model_dump(mode="json"), **changes}


def _doc(*records: Any, **changes: Any) -> dict[str, Any]:
    return {"schema_version": 1, "folders": list(records), **changes}


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / FOLDERS_FILENAME


@pytest.fixture
def tree(tmp_path: Path) -> FolderFile:
    return FolderFile(tmp_path)


def _logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


# --------------------------------------------------------------------------- format


def test_the_file_is_named_so_that_the_graph_index_ignores_it() -> None:
    assert FOLDERS_FILENAME == "folders.json"
    assert _FILE_RE.fullmatch(FOLDERS_FILENAME) is None
    assert _FILE_RE.fullmatch(".folders.json.0123456789abcdef.tmp") is None


def test_a_missing_file_reads_as_no_folders_and_writes_as_a_fresh_start(
    tree: FolderFile, caplog: pytest.LogCaptureFixture
) -> None:
    assert tree.read() == []
    assert tree.read_for_write() == []
    assert _logged(caplog) == []


def test_save_writes_ascii_json_with_an_envelope_mode_0600_and_no_temp_file(
    tree: FolderFile, path: Path
) -> None:
    items = [folder(1, "Café ☃"), folder(2, "inner", 1)]
    tree.save(items)
    text = path.read_text(encoding="ascii")  # pure ASCII, or this raises
    doc = json.loads(text)
    assert list(doc) == ["schema_version", "folders"]
    assert doc["schema_version"] == 1
    assert [r["name"] for r in doc["folders"]] == ["Café ☃", "inner"]
    assert "\\u00e9" in text
    assert text.startswith('{\n  "schema_version": 1,\n  "folders": [\n    {\n      "name"')
    assert mode_of(path) == 0o600
    assert [p.name for p in path.parent.iterdir()] == [FOLDERS_FILENAME]
    assert tree.read() == items


def test_a_new_instance_reads_what_another_one_saved(tmp_path: Path) -> None:
    items = [folder(1, "a"), folder(2, "b", 1)]
    FolderFile(tmp_path).save(items)
    assert FolderFile(tmp_path).read() == items


def test_read_returns_a_copy_the_caller_may_change(tree: FolderFile) -> None:
    tree.save([folder(1, "a")])
    tree.read().clear()
    tree.read_for_write().append(folder(2, "b"))
    assert [item.id for item in tree.read()] == [fid(1)]


# --------------------------------------------------------------------------- damaged files


BIG = [_record(n) for n in range(1, FOLDERS_MAX + 2)]
DAMAGED_FILES = [
    pytest.param("", id="empty"),
    pytest.param("{broken", id="bad json"),
    pytest.param("[]", id="not an object"),
    pytest.param("null", id="null"),
    pytest.param("[" * 100_000, id="nested too deep"),
    pytest.param(json.dumps({"schema_version": 1}), id="no folders"),
    pytest.param(json.dumps({"folders": []}), id="no schema version"),
    pytest.param(json.dumps(_doc(schema_version=0)), id="schema version 0"),
    pytest.param(json.dumps(_doc(schema_version=2)), id="newer schema version"),
    pytest.param(json.dumps(_doc(schema_version="1")), id="schema version as text"),
    pytest.param(json.dumps({"schema_version": 1, "folders": {}}), id="folders not a list"),
    pytest.param(json.dumps(_doc(_record(), 5)), id="a record that is not an object"),
    pytest.param(json.dumps(_doc(_record(1, name=""))), id="an invalid record"),
    pytest.param(json.dumps(_doc(_record(1, schema_version=9))), id="a newer record"),
    pytest.param(json.dumps(_doc(_record(1), _record(1))), id="a repeated id"),
    pytest.param(json.dumps(_doc(*BIG)), id="over the count limit"),
]


@pytest.mark.parametrize("text", DAMAGED_FILES)
def test_a_damaged_file_reads_empty_with_one_warning_and_refuses_writes(
    tree: FolderFile, path: Path, text: str, caplog: pytest.LogCaptureFixture
) -> None:
    path.write_text(text)
    assert tree.read() == []
    assert tree.read() == []  # cached by the signature: no second warning
    assert _logged(caplog) == [WARNING]
    with pytest.raises(StorageError) as info:
        tree.read_for_write()
    assert info.value.message == DAMAGED
    assert path.read_text() == text  # nothing was touched


def test_the_count_limit_is_inclusive(tree: FolderFile, path: Path) -> None:
    path.write_text(json.dumps(_doc(*BIG[:FOLDERS_MAX])))
    assert len(tree.read()) == FOLDERS_MAX


def test_a_valid_file_with_many_records_in_one_envelope_is_read_whole(
    tree: FolderFile, path: Path
) -> None:
    path.write_text(json.dumps(_doc(*[_record(n) for n in range(1, 6)])))
    assert [item.id for item in tree.read()] == [fid(n) for n in range(1, 6)]


def test_a_symlink_is_never_followed(tree: FolderFile, path: Path, tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text(json.dumps(_doc(_record())))
    path.symlink_to(real)
    assert tree.read() == []
    with pytest.raises(StorageError):
        tree.read_for_write()


def test_a_directory_or_a_fifo_is_not_the_folders_file(tmp_path: Path) -> None:
    (tmp_path / FOLDERS_FILENAME).mkdir()
    assert FolderFile(tmp_path).read() == []
    other = tmp_path / "other"
    other.mkdir()
    os.mkfifo(other / FOLDERS_FILENAME)
    with pytest.raises(StorageError):
        FolderFile(other).read_for_write()


def test_a_damaged_file_can_be_repaired_by_replacing_it(tree: FolderFile, path: Path) -> None:
    path.write_text("{broken")
    assert tree.read() == []
    path.unlink()
    tree.save([folder(1, "fresh")])
    assert [item.name for item in tree.read()] == ["fresh"]


# --------------------------------------------------------------------------- the size cap


def test_the_cap_is_four_mebibytes() -> None:
    assert ff.MAX_FOLDERS_BYTES == 4 * 1024 * 1024
    assert ff.MSG_TOO_MANY == "Too many collections to save"
    assert ff.MSG_DAMAGED == DAMAGED


def test_a_file_larger_than_the_cap_is_damaged_and_one_at_the_cap_is_read(
    tree: FolderFile, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree.save([folder(1, "a")])
    size = path.stat().st_size
    monkeypatch.setattr(ff, "MAX_FOLDERS_BYTES", size)
    assert len(FolderFile(path.parent).read()) == 1
    monkeypatch.setattr(ff, "MAX_FOLDERS_BYTES", size - 1)
    assert FolderFile(path.parent).read() == []


def test_save_refuses_more_than_the_cap_and_writes_nothing(
    tree: FolderFile, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree.save([folder(1, "a")])
    size = path.stat().st_size
    before = path.read_bytes()
    monkeypatch.setattr(ff, "MAX_FOLDERS_BYTES", size)
    tree.save([folder(1, "a")])  # exactly at the cap is fine
    monkeypatch.setattr(ff, "MAX_FOLDERS_BYTES", size - 1)
    with pytest.raises(StorageError) as info:
        tree.save([folder(1, "a")])
    assert info.value.message == "Too many collections to save"
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- failures


def test_a_failed_write_is_a_storage_error_and_keeps_the_old_file(
    tree: FolderFile, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree.save([folder(1, "old")])

    def fail(*_args: object) -> None:
        raise OSError(errno.EIO, "disk")

    monkeypatch.setattr(ff, "write_atomic", fail)
    with pytest.raises(StorageError) as info:
        tree.save([folder(1, "new")])
    assert info.value.message == "The collections could not be saved: disk"
    monkeypatch.undo()
    assert [item.name for item in tree.read()] == ["old"]
    assert [p.name for p in path.parent.iterdir()] == [FOLDERS_FILENAME]


def test_an_error_without_text_is_named_by_its_class(
    tree: FolderFile, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object) -> None:
        raise OSError

    monkeypatch.setattr(ff, "write_atomic", fail)
    with pytest.raises(StorageError, match="could not be saved: OSError"):
        tree.save([])


def test_a_file_that_cannot_be_opened_is_damaged(
    tree: FolderFile, path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path.write_text(json.dumps(_doc(_record())))

    def refuse(*_args: object) -> bytes:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(ff, "read_file_nofollow", refuse)
    assert tree.read() == []
    assert _logged(caplog) == [WARNING]


def test_a_file_that_vanishes_between_stat_and_open_reads_as_missing(
    tree: FolderFile, path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path.write_text(json.dumps(_doc(_record())))

    def gone(*_args: object) -> bytes:
        raise FileNotFoundError(errno.ENOENT, "gone")

    monkeypatch.setattr(ff, "read_file_nofollow", gone)
    assert tree.read() == []
    assert _logged(caplog) == []
    monkeypatch.undo()
    assert len(tree.read()) == 1  # the next look re-reads, nothing stale was kept


# --------------------------------------------------------------------------- the cache


class Reads:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        original = read_file_nofollow

        def counting(file: Path, limit: int) -> bytes:
            self.count += 1
            return original(file, limit)

        monkeypatch.setattr(ff, "read_file_nofollow", counting)


def test_the_file_is_read_again_only_when_its_signature_changed(
    tree: FolderFile, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FolderFile(path.parent).save([folder(1, "a")])
    reads = Reads(monkeypatch)
    assert len(tree.read()) == 1
    assert len(tree.read_for_write()) == 1
    assert len(tree.read()) == 1
    assert reads.count == 1


def test_a_save_remembers_what_it_wrote(tree: FolderFile, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = Reads(monkeypatch)
    tree.save([folder(1, "a")])
    assert [item.name for item in tree.read()] == ["a"]
    assert reads.count == 0


def test_another_instance_replacing_the_file_is_noticed(tmp_path: Path) -> None:
    first, second = FolderFile(tmp_path), FolderFile(tmp_path)
    first.save([folder(1, "one")])
    assert [item.name for item in second.read()] == ["one"]
    second.save([folder(1, "two")])
    assert [item.name for item in first.read()] == ["two"]


def test_a_file_that_is_removed_or_damaged_behind_the_cache_is_noticed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tree = FolderFile(tmp_path)
    tree.save([folder(1, "a")])
    (tmp_path / FOLDERS_FILENAME).unlink()
    assert tree.read() == []
    (tmp_path / FOLDERS_FILENAME).write_text("{broken")
    assert tree.read() == []
    assert _logged(caplog) == [WARNING]
    with pytest.raises(StorageError):
        tree.read_for_write()
