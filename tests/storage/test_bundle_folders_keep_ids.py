"""``keep_ids`` imports store the folders of a bundle verbatim (the library-level mode)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.storage.bundle import import_bundle
from sankey_studio.storage.folder_tree import MSG_NAME_TAKEN
from tests.storage.bundle_builders import bundle_of, folder_dump, graph_dump, home_of, tree_of
from tests.storage.folder_builders import body, fid, folder
from tests.storage.support import ID_A, ID_B, definition

if TYPE_CHECKING:
    from tests.storage.conftest import FolderEnv


def test_folders_and_graphs_keep_their_ids(folder_env: FolderEnv) -> None:
    bundle = bundle_of([graph_dump(ID_A, "g", 2)], [folder_dump(1, "A"), folder_dump(2, "B", 1)])
    report = import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    assert (report.imported, report.failed, report.folders, report.errors) == (1, 0, 2, [])
    assert report.ids == [ID_A]
    assert folder_env.folders.get_folder(fid(2)).parent_id == fid(1)
    assert folder_env.graphs.get(ID_A).folder_id == fid(2)
    assert home_of(folder_env.graphs, folder_env.folders) == {"g": "B"}


def test_a_child_listed_before_its_parent_is_stored_after_it(folder_env: FolderEnv) -> None:
    bundle = bundle_of([], [folder_dump(2, "B", 1), folder_dump(1, "A")])
    assert import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders).folders == 2
    assert tree_of(folder_env.folders) == {"A": None, "B": "A"}


def test_a_folder_id_the_store_already_has_is_used_not_reported(folder_env: FolderEnv) -> None:
    bundle = bundle_of([graph_dump(ID_A, "g", 1)], [folder_dump(1, "A")])
    first = import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    again = import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    assert (first.folders, again.folders) == (1, 0)
    assert again.errors == ["graph 1: A graph with this id already exists"]  # only the graph
    assert len(folder_env.folders.list_folders()) == 1


def test_a_name_another_folder_already_uses_is_reported_and_the_graph_still_imports(
    folder_env: FolderEnv,
) -> None:
    folder_env.folders.create_folder(body("A"))
    bundle = bundle_of([graph_dump(ID_A, "g", 1)], [folder_dump(1, "a")])
    report = import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    assert report.errors == [f"collection 1: {MSG_NAME_TAKEN}"]
    assert (report.imported, report.failed, report.folders) == (1, 0, 0)
    # the folder was not stored: the graph falls back to the top level
    assert folder_env.graphs.get(ID_A).folder_id is None
    assert [g.id for g in folder_env.folders.list_in("root")] == [ID_A]


def test_a_graph_of_a_refused_folder_lands_in_the_nearest_stored_ancestor(
    folder_env: FolderEnv,
) -> None:
    folder_env.folders.put_folder(folder(1, "A"))
    folder_env.folders.put_folder(folder(9, "b", 1))
    items = [folder_dump(1, "A"), folder_dump(2, "B", 1), folder_dump(3, "C", 2)]
    bundle = bundle_of([graph_dump(ID_A, "g", 2), graph_dump(ID_B, "h", 3)], items)
    report = import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    assert report.errors == [f"collection 2: {MSG_NAME_TAKEN}"]
    assert folder_env.graphs.get(ID_A).folder_id == fid(1)
    assert folder_env.folders.get_folder(fid(3)).parent_id == fid(1)  # C sits where B's graphs do
    assert folder_env.graphs.get(ID_B).folder_id == fid(3)


def test_a_folder_the_bundle_does_not_list_is_left_as_it_is(folder_env: FolderEnv) -> None:
    folder_env.folders.put_folder(folder(1, "A"))
    bundle = bundle_of([graph_dump(ID_A, "g", 1)], [folder_dump(2, "B", 1)])
    import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    assert folder_env.graphs.get(ID_A).folder_id == fid(1)
    assert folder_env.folders.get_folder(fid(2)).parent_id == fid(1)


def test_a_cycle_is_reported_in_this_mode_too(folder_env: FolderEnv) -> None:
    bundle = bundle_of([], [folder_dump(1, "A", 2), folder_dump(2, "B", 1)])
    report = import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    assert report.folders == 0
    assert len(report.errors) == 2
    assert folder_env.folders.list_folders() == []


def test_a_graph_that_conflicts_does_not_hide_the_folders(folder_env: FolderEnv) -> None:
    folder_env.graphs.put(definition(ID_B, "taken"))
    bundle = bundle_of([graph_dump(ID_B, "again", 1)], [folder_dump(1, "A")])
    report = import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    assert (report.imported, report.failed, report.folders) == (0, 1, 1)


def test_a_backend_failure_while_storing_a_folder_aborts(
    folder_env: FolderEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(_folder: Any, **_options: Any) -> Any:
        raise StorageError("backend down")

    monkeypatch.setattr(folder_env.folders, "put_folder", down)
    bundle = bundle_of([graph_dump(ID_A, "g")], [folder_dump(1, "A")])
    with pytest.raises(StorageError, match="backend down"):
        import_bundle(folder_env.graphs, bundle, "keep_ids", folder_env.folders)
    assert folder_env.graphs.count() == 0
