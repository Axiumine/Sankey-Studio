# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``copy_folders`` and ``copy_library``: moving a whole library between stores."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import FolderRuleError, StorageError
from sankey_studio.models import GraphDefinition
from sankey_studio.storage import (
    CopyReport,
    FileFolderRepository,
    FileGraphRepository,
    FolderCopy,
    Stores,
    copy_folders,
    copy_graphs,
    copy_library,
)
from sankey_studio.storage import folder_tree as folder_tree_module
from tests.storage.folder_builders import fid, folder
from tests.storage.support import ID_A, ID_B, ID_C, definition

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.models import FolderDefinition
    from sankey_studio.storage import MongoFolderRepository, MongoGraphRepository
    from sankey_studio.storage.folders_base import FolderRepository

# `Q3` sorts before `Work`, so the child comes first in a name-ordered listing.
WORK, Q3, MISC = fid(1), fid(2), fid(3)


def _tree() -> list[FolderDefinition]:
    return [folder(1, "Work", revision=4), folder(2, "Q3", 1, revision=2), folder(3, "Misc")]


def _seed_folders(repo: FolderRepository) -> list[FolderDefinition]:
    tree = _tree()
    for item in tree:
        repo.put_folder(item)
    return tree


def _in_folder(graph_id: str, name: str, folder_id: str | None) -> GraphDefinition:
    return GraphDefinition.model_validate(
        {**definition(graph_id, name).model_dump(), "folder_id": folder_id}
    )


def _seed_library(stores: Stores) -> list[GraphDefinition]:
    _seed_folders(stores.folders)
    graphs = [_in_folder(ID_A, "a", Q3), _in_folder(ID_B, "b", WORK), _in_folder(ID_C, "c", None)]
    for graph in graphs:
        stores.graphs.put(graph)
    return graphs


def _other_files(tmp_path: Path) -> Stores:
    """A second, empty file library (another directory)."""
    return Stores(FileGraphRepository(tmp_path / "other"), FileFolderRepository(tmp_path / "other"))


class SpyFolders:
    """Delegates to a real folder repository and remembers the order of the writes."""

    def __init__(self, real: FolderRepository, log: list[str]) -> None:
        self._real = real
        self._log = log

    def put_folder(self, item: FolderDefinition, *, overwrite: bool = False) -> FolderDefinition:
        self._log.append(f"folder:{item.name}")
        return self._real.put_folder(item, overwrite=overwrite)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class SpyGraphs:
    def __init__(self, real: FileGraphRepository, log: list[str]) -> None:
        self._real = real
        self._log = log

    def put(self, item: GraphDefinition, *, overwrite: bool = False) -> GraphDefinition:
        self._log.append(f"graph:{item.name}")
        return self._real.put(item, overwrite=overwrite)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


# --------------------------------------------------------------------------- copy_folders


def test_every_folder_is_copied_verbatim_to_mongo_and_back(
    file_folders: FileFolderRepository,
    mongo_folders: MongoFolderRepository,
    tmp_path: Path,
) -> None:
    tree = _seed_folders(file_folders)
    assert copy_folders(file_folders, mongo_folders) == FolderCopy(copied=3, skipped=0)
    assert mongo_folders.list_definitions() == file_folders.list_definitions()  # ids, revisions
    assert mongo_folders.get_folder(WORK).revision == 4
    back = FileFolderRepository(tmp_path / "back")
    assert copy_folders(mongo_folders, back) == FolderCopy(3, 0)
    assert back.list_definitions() == sorted(tree, key=lambda f: f.name.casefold())
    assert file_folders.list_definitions() == mongo_folders.list_definitions()  # source untouched


def test_an_empty_source_copies_no_folders(
    file_folders: FileFolderRepository, mongo_folders: MongoFolderRepository
) -> None:
    assert copy_folders(file_folders, mongo_folders) == FolderCopy(0, 0)
    assert mongo_folders.list_folders() == []


def test_parents_are_written_before_their_children(
    file_folders: FileFolderRepository, mongo_folders: MongoFolderRepository
) -> None:
    _seed_folders(file_folders)
    assert [f.name for f in file_folders.list_definitions()][:2] == ["Misc", "Q3"]  # child first
    log: list[str] = []
    copy_folders(file_folders, SpyFolders(mongo_folders, log))
    assert log.index("folder:Work") < log.index("folder:Q3")
    assert sorted(log) == ["folder:Misc", "folder:Q3", "folder:Work"]


def test_a_folder_the_destination_already_has_is_skipped_and_counted(
    file_folders: FileFolderRepository, mongo_folders: MongoFolderRepository
) -> None:
    _seed_folders(file_folders)
    mongo_folders.put_folder(folder(3, "Misc", revision=9))
    report = copy_folders(file_folders, mongo_folders)
    assert report == FolderCopy(copied=2, skipped=1)
    assert mongo_folders.get_folder(MISC).revision == 9  # left alone


def test_overwrite_replaces_what_the_destination_has(
    file_folders: FileFolderRepository, mongo_folders: MongoFolderRepository
) -> None:
    _seed_folders(file_folders)
    mongo_folders.put_folder(folder(3, "Misc", revision=9))
    report = copy_folders(file_folders, mongo_folders, on_conflict="overwrite")
    assert report == FolderCopy(copied=3, skipped=0)
    assert mongo_folders.get_folder(MISC).revision == 1


def test_a_folder_whose_name_another_folder_has_there_is_skipped_not_fatal(
    file_folders: FileFolderRepository, mongo_folders: MongoFolderRepository
) -> None:
    _seed_folders(file_folders)
    mongo_folders.put_folder(folder(9, "work"))  # same name, other id, same (top) place
    report = copy_folders(file_folders, mongo_folders)
    assert report == FolderCopy(copied=2, skipped=1)
    names = {f.id: f.name for f in mongo_folders.list_definitions()}
    assert names == {fid(9): "work", Q3: "Q3", MISC: "Misc"}  # `Q3` keeps its (now missing) parent


def test_an_unknown_conflict_policy_is_refused_before_anything_is_copied(
    file_folders: FileFolderRepository, mongo_folders: MongoFolderRepository
) -> None:
    _seed_folders(file_folders)
    with pytest.raises(KeyError):
        copy_folders(file_folders, mongo_folders, on_conflict="merge")  # type: ignore[arg-type]
    assert mongo_folders.list_folders() == []


def test_the_folder_count_limit_aborts_the_copy_with_its_own_error(
    file_folders: FileFolderRepository,
    mongo_folders: MongoFolderRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_folders(file_folders)
    monkeypatch.setattr(folder_tree_module, "FOLDERS_MAX", 2)
    with pytest.raises(FolderRuleError):
        copy_folders(file_folders, mongo_folders)
    assert len(mongo_folders.list_folders()) == 2  # what was copied stays; a retry is safe


def test_a_backend_failure_aborts_the_copy(
    file_folders: FileFolderRepository,
    mongo_folders: MongoFolderRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_folders(file_folders)
    real_put = mongo_folders.put_folder
    calls: list[str] = []

    def flaky(item: FolderDefinition, *, overwrite: bool = False) -> FolderDefinition:
        calls.append(item.id)
        if len(calls) == 2:
            raise StorageError("connection lost")
        return real_put(item, overwrite=overwrite)

    monkeypatch.setattr(mongo_folders, "put_folder", flaky)
    with pytest.raises(StorageError, match="connection lost"):
        copy_folders(file_folders, mongo_folders)
    assert len(calls) == 2  # nothing is attempted after the failure
    monkeypatch.undo()
    assert copy_folders(file_folders, mongo_folders) == FolderCopy(copied=2, skipped=1)


# --------------------------------------------------------------------------- copy_library


def test_the_whole_library_moves_from_files_to_mongo(
    file_repo: FileGraphRepository,
    file_folders: FileFolderRepository,
    mongo_repo: MongoGraphRepository,
    mongo_folders: MongoFolderRepository,
) -> None:
    source, destination = Stores(file_repo, file_folders), Stores(mongo_repo, mongo_folders)
    graphs = _seed_library(source)
    report = copy_library(source, destination)
    assert report == CopyReport(copied=3, skipped=0, folders=3, folders_skipped=0)
    assert list(mongo_repo.iter_definitions()) == graphs  # the graphs keep their folder ids
    assert [g.id for g in mongo_folders.list_in(Q3)] == [ID_A]
    assert [g.id for g in mongo_folders.list_in(WORK)] == [ID_B]
    assert [g.id for g in mongo_folders.list_in("root")] == [ID_C]
    assert [(f.name, f.graph_count) for f in mongo_folders.list_folders()] == [
        ("Misc", 0),
        ("Q3", 1),
        ("Work", 1),
    ]


def test_the_whole_library_moves_from_mongo_to_files(
    mongo_repo: MongoGraphRepository, mongo_folders: MongoFolderRepository, tmp_path: Path
) -> None:
    source, destination = Stores(mongo_repo, mongo_folders), _other_files(tmp_path)
    graphs = _seed_library(source)
    report = copy_library(source, destination)
    assert report == CopyReport(3, 0, folders=3)
    assert list(destination.graphs.iter_definitions()) == graphs
    assert [g.id for g in destination.folders.list_in(Q3)] == [ID_A]
    assert destination.folders.get_folder(Q3).parent_id == WORK
    assert (tmp_path / "other" / "folders.json").is_file()


def test_the_folders_are_written_before_the_first_graph(
    file_repo: FileGraphRepository,
    file_folders: FileFolderRepository,
    tmp_path: Path,
) -> None:
    _seed_library(Stores(file_repo, file_folders))
    other = _other_files(tmp_path)
    log: list[str] = []
    spied = Stores(SpyGraphs(other.graphs, log), SpyFolders(other.folders, log))  # type: ignore[arg-type]
    copy_library(Stores(file_repo, file_folders), spied)
    kinds = [entry.split(":")[0] for entry in log]
    assert kinds == ["folder"] * 3 + ["graph"] * 3


def test_skipped_folders_and_graphs_are_counted_separately(
    file_repo: FileGraphRepository,
    file_folders: FileFolderRepository,
    tmp_path: Path,
) -> None:
    _seed_library(Stores(file_repo, file_folders))
    other = _other_files(tmp_path)
    other.folders.put_folder(folder(3, "Misc", revision=7))
    other.graphs.put(definition(ID_C, "c"))
    report = copy_library(Stores(file_repo, file_folders), other)
    assert report == CopyReport(copied=2, skipped=1, folders=2, folders_skipped=1)


def test_the_conflict_policy_applies_to_folders_and_graphs(
    file_repo: FileGraphRepository,
    file_folders: FileFolderRepository,
    tmp_path: Path,
) -> None:
    _seed_library(Stores(file_repo, file_folders))
    other = _other_files(tmp_path)
    other.folders.put_folder(folder(3, "Misc", revision=7))
    other.graphs.put(definition(ID_C, "old name"))
    report = copy_library(Stores(file_repo, file_folders), other, on_conflict="overwrite")
    assert report == CopyReport(copied=3, skipped=0, folders=3, folders_skipped=0)
    assert other.folders.get_folder(MISC).revision == 1
    assert other.graphs.get(ID_C).name == "c"


def test_unreadable_graphs_are_still_reported_next_to_the_folder_counts(
    file_repo: FileGraphRepository,
    file_folders: FileFolderRepository,
    tmp_path: Path,
) -> None:
    _seed_library(Stores(file_repo, file_folders))
    damaged = tmp_path / "graphs" / f"{'d' * 32}.json"
    damaged.write_text("{not json")
    report = copy_library(Stores(file_repo, file_folders), _other_files(tmp_path))
    assert (report.copied, report.unreadable, report.unreadable_ids) == (3, 1, ("d" * 32,))
    assert (report.folders, report.folders_skipped) == (3, 0)


def test_copying_graphs_alone_reports_no_folders(
    file_repo: FileGraphRepository, file_folders: FileFolderRepository, tmp_path: Path
) -> None:
    _seed_library(Stores(file_repo, file_folders))
    report = copy_graphs(file_repo, _other_files(tmp_path).graphs)
    assert (report.copied, report.folders, report.folders_skipped) == (3, 0, 0)


def test_an_empty_library_copies_nothing(
    file_repo: FileGraphRepository,
    file_folders: FileFolderRepository,
    mongo_repo: MongoGraphRepository,
    mongo_folders: MongoFolderRepository,
) -> None:
    report = copy_library(Stores(file_repo, file_folders), Stores(mongo_repo, mongo_folders))
    assert report == CopyReport(0, 0)
