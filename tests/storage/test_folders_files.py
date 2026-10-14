"""``FileFolderRepository``: shared state with the graph repository, locking, damaged files."""

from __future__ import annotations

import errno
import logging
import threading
from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import FolderNameTakenError, NotFoundError, StorageError
from sankey_studio.storage import FileGraphRepository
from sankey_studio.storage.files import FileFolderRepository, folder_members
from sankey_studio.storage.files import folder_file as ff
from sankey_studio.storage.files import folders as folders_module
from sankey_studio.storage.files.folder_file import FOLDERS_FILENAME, FolderFile
from sankey_studio.storage.files.locks import DirState
from tests.storage.folder_builders import body, folder
from tests.storage.support import ID_A, ID_B, ID_C, ID_D, create_data, mode_of

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.models import FolderDefinition
    from tests.storage.support import Ticker

DAMAGED = "The collections file is unreadable; fix or remove it (graphs are not affected)"
THREADS = 30


@pytest.fixture
def folders(file_folders: FileFolderRepository) -> FileFolderRepository:
    return file_folders


@pytest.fixture
def graphs(file_repo: FileGraphRepository) -> FileGraphRepository:
    return file_repo


@pytest.fixture
def graphs_dir(tmp_path: Path) -> Path:
    return tmp_path / "graphs"


def _make(repo: FileFolderRepository, name: str, parent: FolderDefinition | None = None) -> Any:
    return repo.create_folder(body(name, None if parent is None else parent.id))


# --------------------------------------------------------------------------- layout


def test_the_folders_live_in_one_file_next_to_the_graphs(
    folders: FileFolderRepository, graphs: FileGraphRepository, tmp_path: Path
) -> None:
    created = folders.create_folder(body("Finance"))
    graph = graphs.create(create_data("g"), folder_id=created.id)
    names = sorted(p.name for p in (tmp_path / "graphs").iterdir())
    assert names == sorted([FOLDERS_FILENAME, f"{graph.id}.json"])
    assert mode_of(tmp_path / "graphs" / FOLDERS_FILENAME) == 0o600


def test_the_graph_repository_ignores_the_folders_file(
    folders: FileFolderRepository, graphs: FileGraphRepository
) -> None:
    folders.create_folder(body("Finance"))
    assert graphs.count() == 0
    assert graphs.list_graphs() == []
    assert graphs.unreadable_ids() == []
    assert list(graphs.iter_definitions()) == []


def test_both_repositories_of_one_directory_share_one_state(graphs_dir: Path) -> None:
    graphs, folders = FileGraphRepository(graphs_dir), FileFolderRepository(graphs_dir)
    assert graphs._state is folders._state
    assert isinstance(folders._state, DirState)
    assert isinstance(folders._state.tree, FolderFile)


def test_a_second_repository_sees_the_folders_of_the_first(graphs_dir: Path) -> None:
    one, two = FileFolderRepository(graphs_dir), FileFolderRepository(graphs_dir)
    created = one.create_folder(body("shared"))
    assert two.get_folder(created.id) == created
    two.delete_folder(created.id)
    assert one.list_folders() == []


def test_the_default_clock_gives_aware_millisecond_times(graphs_dir: Path) -> None:
    created = FileFolderRepository(graphs_dir).create_folder(body("now"))
    assert created.created_at == created.updated_at
    assert created.created_at.utcoffset() == timedelta(0)
    assert created.created_at.microsecond % 1000 == 0
    assert created.created_at.tzinfo is not None
    assert created.created_at.astimezone(UTC).year >= 2026


def test_a_directory_that_is_not_usable_is_a_storage_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(StorageError, match="The graphs directory is not usable: "):
        FileFolderRepository(blocker / "graphs")


def test_ping_checks_that_the_directory_is_writable(
    graphs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FileFolderRepository(graphs_dir)
    repo.ping()
    assert [p.name for p in graphs_dir.iterdir()] == []

    def refuse(_directory: object) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(folders_module, "check_writable", refuse)
    with pytest.raises(StorageError) as info:
        repo.ping()
    assert info.value.message == "The graphs directory is not writable: Permission denied"


# --------------------------------------------------------------------------- locking


def test_every_write_of_the_folders_file_happens_under_the_directory_lock(
    folders: FileFolderRepository, graphs: FileGraphRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = folders
    held: list[bool] = []
    original = FolderFile.save

    def watching(self: FolderFile, items: list[Any]) -> None:
        held.append(repo._state.lock.locked())
        original(self, items)

    monkeypatch.setattr(FolderFile, "save", watching)
    box = repo.create_folder(body("box"))
    inner = repo.create_folder(body("inner", box.id))
    graphs.create(create_data("g"), folder_id=inner.id)
    repo.delete_folder(inner.id)
    repo.put_folder(folder(9, "put"))
    assert held == [True] * 4


def test_the_graphs_are_rewritten_one_lock_hold_each_not_under_the_callers_lock(
    folders: FileFolderRepository, graphs: FileGraphRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = folders
    box = repo.create_folder(body("box"))
    for _ in range(3):
        graphs.create(create_data("g"), folder_id=box.id)
    held: list[bool] = []
    original = DirState.store

    def watching(self: DirState, graph: Any) -> None:
        held.append(self.lock.locked())
        original(self, graph)

    monkeypatch.setattr(DirState, "store", watching)
    repo.delete_folder(box.id)
    assert held == [True, True, True]  # each store ran under its own hold of the lock
    assert repo.count_in("root") == 3


def test_concurrent_creates_from_two_repositories_lose_nothing(graphs_dir: Path) -> None:
    repos = [FileFolderRepository(graphs_dir), FileFolderRepository(graphs_dir)]
    barrier = threading.Barrier(THREADS)
    errors: list[Exception] = []

    def work(index: int) -> None:
        barrier.wait()
        try:
            repos[index % 2].create_folder(body(f"folder {index}"))
        except Exception as exc:  # noqa: BLE001 - the test fails below if any thread failed
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(repos[0].list_folders()) == THREADS


def test_concurrent_creates_of_one_name_have_exactly_one_winner(graphs_dir: Path) -> None:
    repos = [FileFolderRepository(graphs_dir), FileFolderRepository(graphs_dir)]
    barrier = threading.Barrier(THREADS)
    outcomes: list[object] = [None] * THREADS

    def work(index: int) -> None:
        barrier.wait()
        try:
            outcomes[index] = repos[index % 2].create_folder(body("same"))
        except Exception as exc:  # noqa: BLE001 - every outcome is inspected below
            outcomes[index] = exc

    threads = [threading.Thread(target=work, args=(i,)) for i in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    losers = [o for o in outcomes if isinstance(o, FolderNameTakenError)]
    assert len(losers) == THREADS - 1
    assert len(repos[0].list_folders()) == 1


# --------------------------------------------------------------------------- a damaged file


def test_a_damaged_file_shows_every_graph_at_the_top_and_refuses_writes(
    folders: FileFolderRepository,
    graphs: FileGraphRepository,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    box = folders.create_folder(body("box"))
    graph = graphs.create(create_data("g"), folder_id=box.id)
    path = tmp_path / "graphs" / FOLDERS_FILENAME
    path.write_text("{broken")
    caplog.set_level(logging.WARNING)
    assert folders.list_folders() == []
    assert [row.id for row in folders.list_in("root")] == [graph.id]
    assert folders.count_in("root") == 1
    assert folders.list_in(box.id) == []
    assert [r.getMessage() for r in caplog.records].count("The collections file is unreadable") == 1
    for write in (
        lambda: folders.create_folder(body("x")),
        lambda: folders.delete_folder(box.id),
        lambda: folders.put_folder(folder(5, "x")),
    ):
        with pytest.raises(StorageError) as info:
            write()
        assert info.value.message == DAMAGED
    assert path.read_text() == "{broken"
    assert graphs.get(graph.id).folder_id == box.id  # nothing was moved


def test_moves_with_a_damaged_file_work_for_the_top_level_only(
    folders: FileFolderRepository, graphs: FileGraphRepository, tmp_path: Path
) -> None:
    box = folders.create_folder(body("box"))
    graph = graphs.create(create_data("g"), folder_id=box.id)
    (tmp_path / "graphs" / FOLDERS_FILENAME).write_text("{broken")
    with pytest.raises(NotFoundError):
        folders.move_graphs([graph.id], box.id)
    assert folders.move_graphs([graph.id], None).moved == 1


def test_a_failed_save_leaves_the_tree_as_it_was(
    folders: FileFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = folders
    box = repo.create_folder(body("box"))

    def fail(*_args: object) -> None:
        raise OSError(errno.ENOSPC, "No space left")

    monkeypatch.setattr(ff, "write_atomic", fail)
    with pytest.raises(StorageError, match="could not be saved: No space left"):
        repo.create_folder(body("two"))
    with pytest.raises(StorageError):
        repo.delete_folder(box.id)
    monkeypatch.undo()
    assert [row.name for row in repo.list_folders()] == ["box"]


# --------------------------------------------------------------------------- delete, step by step


def _tree(
    folders: FileFolderRepository, graphs: FileGraphRepository
) -> tuple[FolderDefinition, list[str]]:
    """A folder `box` with sub-folder `inner` and three graphs directly inside."""
    box = folders.create_folder(body("box"))
    folders.create_folder(body("inner", box.id))
    ids = [graphs.create(create_data(f"g{i}"), folder_id=box.id).id for i in range(3)]
    return box, ids


def test_a_failure_halfway_leaves_a_consistent_tree_and_a_retry_finishes(
    folders: FileFolderRepository, graphs: FileGraphRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    box, ids = _tree(folders, graphs)
    original = DirState.store
    calls: list[str] = []

    def flaky(self: DirState, graph: Any) -> None:
        calls.append(graph.id)
        if len(calls) == 2:
            raise StorageError("The graph could not be saved: disk")
        original(self, graph)

    monkeypatch.setattr(DirState, "store", flaky)
    with pytest.raises(StorageError):
        folders.delete_folder(box.id)
    monkeypatch.undo()
    assert folders.get_folder(box.id).name == "box"  # the record is still there
    assert len([g for g in ids if graphs.get(g).folder_id is None]) == 1  # the first one moved
    folders.delete_folder(box.id)  # the retry finishes
    assert all(graphs.get(g).folder_id is None for g in ids)
    assert [row.name for row in folders.list_folders()] == ["inner"]


def test_a_folder_deleted_by_someone_else_meanwhile_is_not_found(
    folders: FileFolderRepository, graphs: FileGraphRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    box, _ids = _tree(folders, graphs)
    other = FileFolderRepository(folders._dir)
    original = folder_members.move_up

    def and_then_it_vanishes(*args: Any) -> None:
        original(*args)
        if other.list_definitions() and any(f.id == box.id for f in other.list_definitions()):
            other.delete_folder(box.id)

    monkeypatch.setattr(folder_members, "move_up", and_then_it_vanishes)
    with pytest.raises(NotFoundError):
        folders.delete_folder(box.id)


def test_a_name_taken_meanwhile_stops_the_delete_before_the_record_goes(
    folders: FileFolderRepository, graphs: FileGraphRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    box, ids = _tree(folders, graphs)
    other = FileFolderRepository(folders._dir)
    original = folder_members.move_up

    def and_a_clash_appears(*args: Any) -> None:
        original(*args)
        if not [f for f in other.list_definitions() if f.name == "INNER"]:
            other.create_folder(body("INNER"))  # now `inner` would clash at the top level

    monkeypatch.setattr(folder_members, "move_up", and_a_clash_appears)
    with pytest.raises(FolderNameTakenError):
        folders.delete_folder(box.id)
    monkeypatch.undo()
    assert folders.get_folder(box.id).revision == 1
    assert all(graphs.get(g).folder_id is None for g in ids)  # already moved up


# --------------------------------------------------------------------------- members helpers


def test_move_up_leaves_a_graph_that_is_elsewhere_by_now(
    folders: FileFolderRepository, graphs: FileGraphRepository
) -> None:
    state = folders._state
    here = folders.create_folder(body("here"))
    there = folders.create_folder(body("there"))
    moved = graphs.create(create_data("a"), folder_id=here.id)
    stays = graphs.create(create_data("b"), folder_id=there.id)
    folder_members.move_up(state, moved.id, here.id, None)
    folder_members.move_up(state, stays.id, here.id, None)
    assert graphs.get(moved.id).folder_id is None
    assert graphs.get(stays.id).folder_id == there.id


def test_assign_reports_a_missing_or_malformed_or_damaged_graph(
    folders: FileFolderRepository, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state = folders._state
    (tmp_path / "graphs" / f"{ID_D}.json").write_text("{broken")
    caplog.set_level(logging.WARNING)
    assert folder_members.assign(state, ID_A, None) is False
    assert folder_members.assign(state, "../x", None) is False
    assert folder_members.assign(state, ID_D, None) is False
    assert f"Skipping unreadable stored graph {ID_D}" in [r.getMessage() for r in caplog.records]


def test_a_damaged_graph_file_is_reported_missing_by_a_move(
    folders: FileFolderRepository, graphs: FileGraphRepository, tmp_path: Path
) -> None:
    box = folders.create_folder(body("box"))
    good = graphs.create(create_data("good"))
    (tmp_path / "graphs" / f"{ID_B}.json").write_text("{broken")
    report = folders.move_graphs([good.id, ID_B, ID_C], box.id)
    assert (report.moved, report.missing) == (1, [ID_B, ID_C])


def test_the_move_keeps_the_exact_graph(
    folders: FileFolderRepository, graphs: FileGraphRepository
) -> None:
    box = folders.create_folder(body("box"))
    graph = graphs.create(create_data("g", None))
    folders.move_graphs([graph.id], box.id)
    after = graphs.get(graph.id)
    assert after.model_dump(exclude={"folder_id"}) == graph.model_dump(exclude={"folder_id"})
    assert after.updated_at == graph.updated_at
    assert (after.revision, after.folder_id) == (1, box.id)


def test_the_clock_is_not_read_by_a_move_or_a_delete(
    folders: FileFolderRepository, graphs: FileGraphRepository, clock: Ticker
) -> None:
    box = folders.create_folder(body("box"))
    graph = graphs.create(create_data("g"), folder_id=box.id)
    calls = clock.calls
    folders.move_graphs([graph.id], None)
    assert clock.calls == calls
