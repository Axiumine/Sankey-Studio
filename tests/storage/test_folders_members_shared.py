# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Folder membership and deletion, run once per backend: ``list_in``, moves, re-parenting."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import FolderNameTakenError, NotFoundError
from sankey_studio.models import FolderUpdate, GraphDefinition
from sankey_studio.storage.common import PAGE_MAX
from tests.storage.folder_builders import body, fid
from tests.storage.support import ID_A, ID_B, ID_C, ID_D, NOW, create_data, definition, update_data

if TYPE_CHECKING:
    from sankey_studio.models import FolderDefinition
    from tests.storage.conftest import FolderEnv

ID_E = "e" * 32
UNKNOWN = fid(0xDEAD)
MISSING_GRAPH = "0" * 32


def _put(env: FolderEnv, graph_id: str, folder_id: str | None, age: int = 0) -> GraphDefinition:
    """Store a graph in ``folder_id``; a larger ``age`` means a later ``updated_at``."""
    base = definition(graph_id, graph_id[:1])
    graph = GraphDefinition.model_validate(
        {**base.model_dump(), "folder_id": folder_id, "updated_at": NOW + timedelta(minutes=age)}
    )
    return env.graphs.put(graph)


def _ids(env: FolderEnv, scope: str, **kwargs: int) -> list[str]:
    return [row.id for row in env.folders.list_in(scope, **kwargs)]


def _where(env: FolderEnv, graph_id: str) -> str | None:
    return env.graphs.get(graph_id).folder_id


def _folder(env: FolderEnv, name: str, parent: FolderDefinition | None = None) -> FolderDefinition:
    return env.folders.create_folder(body(name, None if parent is None else parent.id))


# --------------------------------------------------------------------------- list_in / count_in


def test_list_in_lists_the_graphs_directly_in_a_scope_newest_first(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    _put(folder_env, ID_A, None, age=1)
    _put(folder_env, ID_B, box.id, age=2)
    _put(folder_env, ID_C, box.id, age=3)
    _put(folder_env, ID_D, UNKNOWN, age=4)  # names no folder: reads as top level
    assert _ids(folder_env, "root") == [ID_D, ID_A]
    assert _ids(folder_env, box.id) == [ID_C, ID_B]
    assert (folder_env.folders.count_in("root"), folder_env.folders.count_in(box.id)) == (2, 2)


def test_the_rows_carry_the_folder_of_the_graph(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    _put(folder_env, ID_A, box.id)
    [row] = folder_env.folders.list_in(box.id)
    assert (row.id, row.folder_id, row.name) == (ID_A, box.id, "a")


def test_an_unknown_folder_lists_nothing(folder_env: FolderEnv) -> None:
    _put(folder_env, ID_A, UNKNOWN)
    assert _ids(folder_env, UNKNOWN) == []
    assert folder_env.folders.count_in(UNKNOWN) == 0


def test_an_empty_folder_lists_nothing(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    _put(folder_env, ID_A, None)
    assert _ids(folder_env, box.id) == []
    assert folder_env.folders.count_in(box.id) == 0


@pytest.mark.parametrize("scope", ["", "ROOT", "../x", "a" * 31, "a" * 32 + "\n"])
def test_a_malformed_scope_is_not_found(folder_env: FolderEnv, scope: str) -> None:
    with pytest.raises(NotFoundError):
        folder_env.folders.list_in(scope)
    with pytest.raises(NotFoundError):
        folder_env.folders.count_in(scope)


class Page(NamedTuple):
    limit: int
    offset: int
    expected: list[str]


IDS = [ID_C, ID_B, ID_A]  # newest first


@pytest.mark.parametrize(
    "case",
    [
        Page(200, 0, IDS),
        Page(2, 0, IDS[:2]),
        Page(2, 1, IDS[1:]),
        Page(1, 2, IDS[2:]),
        Page(1, 3, []),
        Page(0, 0, []),
        Page(-1, 0, []),
        Page(5, -3, IDS),
        Page(PAGE_MAX + 1, 0, IDS),
        Page(10**30, 1, IDS[1:]),
        Page(2, 10**30, []),
    ],
)
def test_list_in_pages_and_clamps_the_bounds(folder_env: FolderEnv, case: Page) -> None:
    box = _folder(folder_env, "box")
    for age, graph_id in enumerate([ID_A, ID_B, ID_C]):
        _put(folder_env, graph_id, box.id, age=age)
    assert _ids(folder_env, box.id, limit=case.limit, offset=case.offset) == case.expected


def test_list_in_returns_two_hundred_graphs_by_default(folder_env: FolderEnv) -> None:
    for number in range(201):
        _put(folder_env, f"{number:032x}", None, age=number)
    assert len(folder_env.folders.list_in("root")) == 200
    assert folder_env.folders.count_in("root") == 201


def test_list_folders_counts_graphs_directly_inside_only(folder_env: FolderEnv) -> None:
    outer = _folder(folder_env, "outer")
    inner = _folder(folder_env, "inner", outer)
    _put(folder_env, ID_A, outer.id)
    _put(folder_env, ID_B, inner.id)
    _put(folder_env, ID_C, inner.id)
    _put(folder_env, ID_D, UNKNOWN)
    counts = {
        row.id: (row.graph_count, row.child_count) for row in folder_env.folders.list_folders()
    }
    assert counts == {outer.id: (1, 1), inner.id: (2, 0)}


# --------------------------------------------------------------------------- move_graphs


def test_move_graphs_puts_them_in_a_folder_and_back_to_the_top(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    _put(folder_env, ID_A, None)
    _put(folder_env, ID_B, None)
    report = folder_env.folders.move_graphs([ID_A, ID_B], box.id)
    assert (report.moved, report.missing) == (2, [])
    assert (_where(folder_env, ID_A), _where(folder_env, ID_B)) == (box.id, box.id)
    assert _ids(folder_env, "root") == []
    assert folder_env.folders.move_graphs([ID_B], None).moved == 1
    assert (_where(folder_env, ID_A), _where(folder_env, ID_B)) == (box.id, None)


def test_a_move_changes_neither_the_revision_nor_the_timestamps_nor_the_content(
    folder_env: FolderEnv,
) -> None:
    box = _folder(folder_env, "box")
    before = _put(folder_env, ID_A, None, age=5)
    folder_env.folders.move_graphs([ID_A], box.id)
    after = folder_env.graphs.get(ID_A)
    assert after.folder_id == box.id
    assert after.model_dump(exclude={"folder_id"}) == before.model_dump(exclude={"folder_id"})


def test_move_graphs_reports_unknown_ids_in_order_and_counts_a_repeat_once(
    folder_env: FolderEnv,
) -> None:
    box = _folder(folder_env, "box")
    _put(folder_env, ID_A, None)
    report = folder_env.folders.move_graphs([ID_E, ID_A, MISSING_GRAPH, ID_A, ID_E], box.id)
    assert report.moved == 1
    assert report.missing == [ID_E, MISSING_GRAPH]
    assert _where(folder_env, ID_A) == box.id


def test_move_graphs_of_nothing_moves_nothing(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    report = folder_env.folders.move_graphs([], box.id)
    assert (report.moved, report.missing) == (0, [])


def test_a_move_into_the_folder_a_graph_is_in_changes_nothing(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    before = _put(folder_env, ID_A, box.id)
    assert folder_env.folders.move_graphs([ID_A], box.id).moved == 1
    assert folder_env.graphs.get(ID_A) == before


def test_a_dangling_graph_can_be_moved_to_the_top_level_explicitly(folder_env: FolderEnv) -> None:
    _put(folder_env, ID_A, UNKNOWN)
    assert folder_env.folders.move_graphs([ID_A], None).moved == 1
    assert _where(folder_env, ID_A) is None


@pytest.mark.parametrize("target", [UNKNOWN, "root", "../x", ""])
def test_a_move_into_an_unknown_folder_is_not_found_and_moves_nothing(
    folder_env: FolderEnv, target: str
) -> None:
    box = _folder(folder_env, "box")
    _put(folder_env, ID_A, box.id)
    with pytest.raises(NotFoundError) as info:
        folder_env.folders.move_graphs([ID_A], target)
    assert info.value.message == "Folder not found"
    assert _where(folder_env, ID_A) == box.id


def test_a_malformed_graph_id_is_not_found_and_nothing_moves(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    _put(folder_env, ID_A, None)
    with pytest.raises(NotFoundError) as info:
        folder_env.folders.move_graphs([ID_A, "../x"], box.id)
    assert info.value.message == "Graph not found"
    assert _where(folder_env, ID_A) is None


# --------------------------------------------------------------------------- graphs and folders


def test_a_graph_update_never_changes_its_folder(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    _put(folder_env, ID_A, box.id)
    updated = folder_env.graphs.update(ID_A, update_data(1, "renamed"))
    assert (updated.folder_id, updated.revision, updated.name) == (box.id, 2, "renamed")
    assert _where(folder_env, ID_A) == box.id


def test_a_graph_created_in_a_folder_lists_there(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    created = folder_env.graphs.create(create_data("in a box"), folder_id=box.id)
    assert created.folder_id == box.id
    assert _ids(folder_env, box.id) == [created.id]
    loose = folder_env.graphs.create(create_data("loose"))
    assert loose.folder_id is None
    assert _ids(folder_env, "root") == [loose.id]


# --------------------------------------------------------------------------- delete


def test_delete_moves_graphs_and_subfolders_up_and_deletes_no_graph(folder_env: FolderEnv) -> None:
    top = _folder(folder_env, "top")
    mid = _folder(folder_env, "mid", top)
    low = _folder(folder_env, "low", mid)
    _put(folder_env, ID_A, mid.id, age=1)
    _put(folder_env, ID_B, low.id, age=2)
    before = folder_env.graphs.get(ID_A)
    folder_env.folders.delete_folder(mid.id)
    assert _where(folder_env, ID_A) == top.id
    assert _where(folder_env, ID_B) == low.id  # not a direct member: stays where it is
    assert folder_env.graphs.get(ID_A).model_dump(exclude={"folder_id"}) == before.model_dump(
        exclude={"folder_id"}
    )
    moved = folder_env.folders.get_folder(low.id)
    assert (moved.parent_id, moved.revision) == (top.id, low.revision + 1)
    assert moved.updated_at > low.updated_at
    assert [row.id for row in folder_env.folders.list_folders()] == [low.id, top.id]
    with pytest.raises(NotFoundError):
        folder_env.folders.get_folder(mid.id)


def test_deleting_a_top_level_folder_moves_its_content_to_the_top(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    inner = _folder(folder_env, "inner", box)
    _put(folder_env, ID_A, box.id)
    folder_env.folders.delete_folder(box.id)
    assert _where(folder_env, ID_A) is None
    assert folder_env.folders.get_folder(inner.id).parent_id is None
    assert folder_env.folders.count_in("root") == 1


def test_delete_leaves_other_folders_and_their_graphs_alone(folder_env: FolderEnv) -> None:
    gone, kept = _folder(folder_env, "gone"), _folder(folder_env, "kept")
    _put(folder_env, ID_A, kept.id)
    _put(folder_env, ID_B, None)
    folder_env.folders.delete_folder(gone.id)
    assert (_where(folder_env, ID_A), _where(folder_env, ID_B)) == (kept.id, None)
    assert folder_env.folders.get_folder(kept.id).revision == 1


def test_a_delete_that_would_clash_by_name_changes_nothing(folder_env: FolderEnv) -> None:
    top = _folder(folder_env, "top")
    docs = _folder(folder_env, "Docs", top)
    _folder(folder_env, "docs", docs)  # would land beside a sibling named "docs" of `docs`
    sibling = _folder(folder_env, "Reports", top)
    inner = _folder(folder_env, "reports", docs)
    _put(folder_env, ID_A, docs.id)
    with pytest.raises(FolderNameTakenError):
        folder_env.folders.delete_folder(docs.id)
    assert _where(folder_env, ID_A) == docs.id
    assert folder_env.folders.get_folder(docs.id).revision == 1
    assert folder_env.folders.get_folder(inner.id).parent_id == docs.id
    assert sibling.id in [row.id for row in folder_env.folders.list_folders()]


def test_a_subfolder_may_take_the_name_of_the_folder_that_is_deleted(folder_env: FolderEnv) -> None:
    outer = _folder(folder_env, "same")
    inner = _folder(folder_env, "Same", outer)
    folder_env.folders.delete_folder(outer.id)
    assert folder_env.folders.get_folder(inner.id).parent_id is None


def test_delete_of_an_unknown_folder_is_not_found_and_moves_nothing(folder_env: FolderEnv) -> None:
    _put(folder_env, ID_A, UNKNOWN)
    with pytest.raises(NotFoundError):
        folder_env.folders.delete_folder(UNKNOWN)
    assert _where(folder_env, ID_A) == UNKNOWN


def test_a_deleted_folder_can_be_created_again_under_the_same_name(folder_env: FolderEnv) -> None:
    box = _folder(folder_env, "box")
    folder_env.folders.delete_folder(box.id)
    again = _folder(folder_env, "box")
    assert again.id != box.id
    update = FolderUpdate(name="box 2", parent_id=None, revision=again.revision)
    assert folder_env.folders.update_folder(again.id, update).name == "box 2"
