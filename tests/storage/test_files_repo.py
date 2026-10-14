"""``FileGraphRepository``: layout, modes, damaged files, failure injection."""

from __future__ import annotations

import errno
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import ConflictError, NotFoundError, StorageError
from sankey_studio.storage import FileGraphRepository, atomic
from sankey_studio.storage.files import locks as locks_module
from sankey_studio.storage.files import repo as repo_module
from tests.storage.support import (
    ID_A,
    ID_B,
    ID_C,
    ID_D,
    NOW,
    Spec,
    Ticker,
    create_data,
    definition,
    mode_of,
    umask,
    update_data,
)

if TYPE_CHECKING:
    from collections.abc import Callable

UNREADABLE = "Stored graph is unreadable"


def _file(repo_dir: Path, graph_id: str) -> Path:
    return repo_dir / f"{graph_id}.json"


@pytest.fixture
def graphs_dir(tmp_path: Path) -> Path:
    return tmp_path / "graphs"


def _raiser(error: OSError) -> Callable[..., Any]:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    return fail


# --------------------------------------------------------------------------- layout


def test_each_graph_is_one_private_json_file_in_a_private_directory(
    graphs_dir: Path, clock: Ticker
) -> None:
    with umask(0o022):
        repo = FileGraphRepository(graphs_dir, clock=clock)
        created = repo.create(create_data("Zürich ☃", Spec(tags=("t",))))
    assert mode_of(graphs_dir) == 0o700
    assert [p.name for p in graphs_dir.iterdir()] == [f"{created.id}.json"]
    path = _file(graphs_dir, created.id)
    assert mode_of(path) == 0o600
    raw = path.read_bytes()
    raw.decode("ascii")  # escaped, never raw UTF-8
    stored = json.loads(raw)
    assert stored["id"] == created.id
    assert stored["name"] == "Zürich ☃"
    assert stored["revision"] == 1
    assert stored["schema_version"] == 1
    assert stored["created_at"] == "2025-05-01T12:00:00Z"


def test_the_directory_is_created_on_demand_with_its_parents(tmp_path: Path) -> None:
    target = tmp_path / "x" / "y" / "graphs"
    FileGraphRepository(target)
    assert target.is_dir()
    assert mode_of(target) == 0o700


def test_a_loose_graphs_directory_is_repaired(graphs_dir: Path) -> None:
    graphs_dir.mkdir()
    graphs_dir.chmod(0o777)
    FileGraphRepository(graphs_dir)
    assert mode_of(graphs_dir) == 0o755


def test_a_foreign_owned_directory_is_refused(
    graphs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(atomic, "current_uid", lambda: os.getuid() + 1)
    with pytest.raises(StorageError) as info:
        FileGraphRepository(graphs_dir)
    assert info.value.message == (
        "The graphs directory is not usable: the directory is owned by another user"
    )


def test_a_file_in_place_of_the_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "graphs").write_text("x")
    with pytest.raises(StorageError, match="The graphs directory is not usable"):
        FileGraphRepository(tmp_path / "graphs")


# --------------------------------------------------------------------------- traversal


@pytest.mark.parametrize(
    "bad", ["../x", "..%2f", "../" + "a" * 29, "a" * 31 + "\x00", "/etc/passwd"]
)
def test_a_path_like_id_never_touches_the_file_system(
    tmp_path: Path, graphs_dir: Path, bad: str
) -> None:
    repo = FileGraphRepository(graphs_dir)
    (tmp_path / "x.json").write_text("outside")
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    for call in (
        lambda: repo.get(bad),
        lambda: repo.delete(bad),
        lambda: repo.update(bad, update_data(1)),
    ):
        with pytest.raises(NotFoundError):
            call()
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    assert (tmp_path / "x.json").read_text() == "outside"


# --------------------------------------------------------------------------- damaged files


class Damage(NamedTuple):
    label: str
    content: bytes


DAMAGE = [
    Damage("not json", b"{not json"),
    Damage("bad utf-8", b"\xff\xfe\xfd"),
    Damage("a list", b"[]"),
    Damage("a string", b'"text"'),
    Damage("empty", b""),
    Damage("invalid model", b'{"id": "' + b"a" * 32 + b'", "name": ""}'),
    Damage("too deep", b"[" * 200_000),
    Damage("newer schema", b""),  # filled in by the test (needs a valid document)
]


def _newer_schema_document() -> bytes:
    doc = json.loads(definition(ID_A, "future").model_dump_json())
    doc["schema_version"] = 99
    return json.dumps(doc).encode()


@pytest.mark.parametrize("case", DAMAGE, ids=[d.label for d in DAMAGE])
def test_a_damaged_file_is_skipped_in_listings_but_get_raises(
    graphs_dir: Path, caplog: pytest.LogCaptureFixture, case: Damage
) -> None:
    repo = FileGraphRepository(graphs_dir)
    repo.put(definition(ID_B, "healthy"))
    content = _newer_schema_document() if case.label == "newer schema" else case.content
    _file(graphs_dir, ID_A).write_bytes(content)
    with caplog.at_level(logging.WARNING):
        assert [s.id for s in repo.list_graphs()] == [ID_B]
    assert repo.count() == 1
    assert [g.id for g in repo.iter_definitions()] == [ID_B]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [f"Skipping unreadable stored graph {ID_A}"]
    with pytest.raises(StorageError) as info:
        repo.get(ID_A)
    assert info.value.status_code == 503
    expected = (
        "Stored graph was written by a newer version of sankey-studio"
        if case.label == "newer schema"
        else UNREADABLE
    )
    assert info.value.message == expected


def test_a_file_holding_another_graphs_id_is_refused(graphs_dir: Path) -> None:
    repo = FileGraphRepository(graphs_dir)
    _file(graphs_dir, ID_A).write_text(definition(ID_B, "impostor").model_dump_json())
    assert repo.list_graphs() == []
    with pytest.raises(StorageError, match=UNREADABLE):
        repo.get(ID_A)


def test_a_symlinked_graph_file_is_neither_listed_nor_read(
    graphs_dir: Path, tmp_path: Path
) -> None:
    repo = FileGraphRepository(graphs_dir)
    outside = tmp_path / "outside.json"
    outside.write_text(definition(ID_A, "outside").model_dump_json())
    _file(graphs_dir, ID_A).symlink_to(outside)
    assert repo.list_graphs() == []
    with pytest.raises(StorageError, match=UNREADABLE):
        repo.get(ID_A)
    assert repo.put(definition(ID_A, "mine"), overwrite=True).name == "mine"
    assert not _file(graphs_dir, ID_A).is_symlink()
    assert json.loads(outside.read_text())["name"] == "outside"  # the target was never written


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_a_directory_or_fifo_named_like_a_graph_is_ignored(graphs_dir: Path, kind: str) -> None:
    repo = FileGraphRepository(graphs_dir)
    odd = _file(graphs_dir, ID_A)
    if kind == "directory":
        odd.mkdir()
    else:
        os.mkfifo(odd)
    assert repo.list_graphs() == []
    with pytest.raises(StorageError, match=UNREADABLE):
        repo.get(ID_A)


def test_stray_files_are_not_graphs(graphs_dir: Path) -> None:
    repo = FileGraphRepository(graphs_dir)
    repo.put(definition(ID_A, "real"))
    valid = definition(ID_B, "stray").model_dump_json()
    for name in (
        "notes.json",
        "README.txt",
        ID_B,
        f"{ID_B}.json.bak",
        f".{ID_B}.json.tmp",
        f"{'B' * 32}.json",
        f"{ID_B[:-1]}.json",
        f"{ID_B}x.json",
    ):
        (graphs_dir / name).write_text(valid)
    assert [s.id for s in repo.list_graphs()] == [ID_A]


# --------------------------------------------------------------------------- put / update edges


def test_put_conflict_on_a_damaged_file_has_no_details_and_overwrite_repairs_it(
    graphs_dir: Path,
) -> None:
    repo = FileGraphRepository(graphs_dir)
    _file(graphs_dir, ID_A).write_text("{broken")
    with pytest.raises(ConflictError) as info:
        repo.put(definition(ID_A, "new"))
    assert info.value.details == []
    assert (info.value.current_revision, info.value.current_updated_at) == (None, None)
    repo.put(definition(ID_A, "new"), overwrite=True)
    assert repo.get(ID_A).name == "new"


def test_a_conflicting_put_does_not_touch_the_file(graphs_dir: Path) -> None:
    repo = FileGraphRepository(graphs_dir)
    repo.put(definition(ID_A, "first"))
    before = _file(graphs_dir, ID_A).read_bytes()
    stat_before = _file(graphs_dir, ID_A).stat()
    with pytest.raises(ConflictError):
        repo.put(definition(ID_A, "second"))
    assert _file(graphs_dir, ID_A).read_bytes() == before
    assert _file(graphs_dir, ID_A).stat().st_ino == stat_before.st_ino


def test_a_put_over_a_dangling_symlink_conflicts_instead_of_following_it(
    graphs_dir: Path, tmp_path: Path
) -> None:
    repo = FileGraphRepository(graphs_dir)
    _file(graphs_dir, ID_A).symlink_to(tmp_path / "nowhere")
    with pytest.raises(ConflictError):
        repo.put(definition(ID_A, "x"))
    assert not (tmp_path / "nowhere").exists()


def test_update_of_a_damaged_graph_is_a_storage_error(graphs_dir: Path) -> None:
    repo = FileGraphRepository(graphs_dir)
    _file(graphs_dir, ID_A).write_text("{broken")
    with pytest.raises(StorageError, match=UNREADABLE):
        repo.update(ID_A, update_data(1))


# --------------------------------------------------------------------------- failures


def test_a_failed_create_raises_a_storage_error_and_stores_nothing(
    graphs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FileGraphRepository(graphs_dir)
    monkeypatch.setattr(locks_module, "write_atomic", _raiser(OSError(errno.EIO, "disk")))
    with pytest.raises(StorageError) as info:
        repo.create(create_data("g"))
    assert info.value.message == "The graph could not be saved: disk"
    monkeypatch.undo()
    assert repo.count() == 0


def test_a_failed_update_keeps_the_old_graph(
    graphs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FileGraphRepository(graphs_dir)
    created = repo.create(create_data("old"))
    monkeypatch.setattr(
        "sankey_studio.storage.atomic.os.fsync", _raiser(OSError(errno.ENOSPC, "No space left"))
    )
    with pytest.raises(StorageError, match="could not be saved: No space left"):
        repo.update(created.id, update_data(1, "new"))
    monkeypatch.undo()
    assert repo.get(created.id).name == "old"
    assert repo.get(created.id).revision == 1
    assert [p.name for p in graphs_dir.iterdir()] == [f"{created.id}.json"]


def test_a_failed_index_stat_after_the_write_is_a_storage_error(
    graphs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FileGraphRepository(graphs_dir)
    state = repo._state
    monkeypatch.setattr(state.index, "remember", _raiser(OSError(errno.EIO, "stat failed")))
    with pytest.raises(StorageError, match="could not be saved: stat failed"):
        repo.create(create_data("g"))


def test_a_failed_unlink_is_a_storage_error_and_the_graph_stays_listed(
    graphs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FileGraphRepository(graphs_dir)
    created = repo.create(create_data("g"))
    monkeypatch.setattr(Path, "unlink", _raiser(PermissionError(errno.EACCES, "Permission denied")))
    with pytest.raises(StorageError) as info:
        repo.delete(created.id)
    assert info.value.message == "The graph could not be deleted: Permission denied"
    monkeypatch.undo()
    assert [s.id for s in repo.list_graphs()] == [created.id]


def test_a_failed_directory_sync_after_the_unlink_is_reported_but_the_graph_is_gone(
    graphs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FileGraphRepository(graphs_dir)
    created = repo.create(create_data("g"))
    monkeypatch.setattr(repo_module, "fsync_dir", _raiser(OSError(errno.EIO, "sync")))
    with pytest.raises(StorageError, match="could not be deleted: sync"):
        repo.delete(created.id)
    monkeypatch.undo()
    assert repo.list_graphs() == []


def test_ping_reports_an_unwritable_directory(
    graphs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FileGraphRepository(graphs_dir)
    repo.ping()
    monkeypatch.setattr(
        repo_module, "check_writable", _raiser(PermissionError(errno.EACCES, "Permission denied"))
    )
    with pytest.raises(StorageError) as info:
        repo.ping()
    assert info.value.message == "The graphs directory is not writable: Permission denied"


def test_a_directory_that_disappears_makes_listing_a_storage_error(graphs_dir: Path) -> None:
    repo = FileGraphRepository(graphs_dir)
    graphs_dir.rmdir()
    with pytest.raises(StorageError, match="cannot be listed"):
        repo.list_graphs()


# --------------------------------------------------------------------------- streaming


def test_iter_definitions_skips_what_vanishes_or_breaks_mid_stream(
    graphs_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repo = FileGraphRepository(graphs_dir)
    for graph_id, name in [(ID_A, "a"), (ID_B, "b"), (ID_C, "c"), (ID_D, "d")]:
        repo.put(definition(graph_id, name))
    stream = repo.iter_definitions()
    assert next(stream).id == ID_A
    _file(graphs_dir, ID_B).write_text("{broken")
    _file(graphs_dir, ID_C).unlink()
    with caplog.at_level(logging.WARNING):
        assert [g.id for g in stream] == [ID_D]
    assert [r.getMessage() for r in caplog.records] == [f"Skipping unreadable stored graph {ID_B}"]


def test_the_creation_time_is_the_clock_not_the_wall(graphs_dir: Path) -> None:
    clock = Ticker(start=NOW.replace(year=2030))
    repo = FileGraphRepository(graphs_dir, clock=clock)
    assert repo.create(create_data("g")).created_at.year == 2030
