# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Folders in a v2 bundle: what an export carries and how a ``new_ids`` import places them."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import (
    BundleError,
    FolderNameTakenError,
    FolderRuleError,
    NotFoundError,
    StorageError,
)
from sankey_studio.storage import bundle_folders
from sankey_studio.storage.bundle import ImportReport, export_bundle, import_bundle
from sankey_studio.storage.bundle_folders import MSG_CYCLE
from sankey_studio.storage.folder_tree import MSG_DEPTH
from tests.storage.bundle_builders import bundle_of, folder_dump, graph_dump, home_of, tree_of
from tests.storage.folder_builders import body, fid
from tests.storage.support import ID_A, ID_B, ID_C, ID_D, create_data

if TYPE_CHECKING:
    from sankey_studio.storage.base import GraphRepository
    from sankey_studio.storage.folders_base import FolderRepository
    from tests.storage.conftest import FolderEnv


@pytest.fixture
def other_side(
    folder_env: FolderEnv, request: pytest.FixtureRequest
) -> tuple[GraphRepository, FolderRepository]:
    """The graph and folder repositories of the OTHER backend (empty)."""
    other = "mongo" if folder_env.kind == "file" else "file"
    return request.getfixturevalue(f"{other}_repo"), request.getfixturevalue(f"{other}_folders")


def seed(env: FolderEnv) -> dict[str, str]:
    """Finance > Q3 and Travel at the top, one empty top folder, graphs in Q3 and Travel."""
    folders, graphs = env.folders, env.graphs
    finance = folders.create_folder(body("Finance")).id
    q3 = folders.create_folder(body("Q3", finance)).id
    travel = folders.create_folder(body("Travel")).id
    empty = folders.create_folder(body("Empty")).id
    graphs.create(create_data("In Q3"), folder_id=q3)
    graphs.create(create_data("In Travel"), folder_id=travel)
    graphs.create(create_data("Loose"))
    return {"finance": finance, "q3": q3, "travel": travel, "empty": empty}


def graph_named(env: FolderEnv, name: str) -> str:
    return next(g.id for g in env.graphs.iter_definitions() if g.name == name)


# --------------------------------------------------------------------------- export


def test_the_whole_library_exports_every_folder_empty_ones_too_and_parents_first(
    folder_env: FolderEnv,
) -> None:
    ids = seed(folder_env)
    out = export_bundle(folder_env.graphs, None, folder_env.folders)
    exported = [f["id"] for f in out["folders"]]
    assert sorted(exported) == sorted(ids.values())
    assert exported.index(ids["finance"]) < exported.index(ids["q3"])
    assert list(out) == ["format", "version", "graphs", "folders"]
    assert out["folders"][0].keys() >= {"id", "name", "parent_id", "revision", "created_at"}


def test_graphs_by_id_carry_their_folders_and_the_ancestors_and_no_others(
    folder_env: FolderEnv,
) -> None:
    ids = seed(folder_env)
    out = export_bundle(folder_env.graphs, [graph_named(folder_env, "In Q3")], folder_env.folders)
    assert [f["id"] for f in out["folders"]] == [ids["finance"], ids["q3"]]
    assert [g["folder_id"] for g in out["graphs"]] == [ids["q3"]]


def test_a_graph_at_the_top_level_carries_no_folder(folder_env: FolderEnv) -> None:
    seed(folder_env)
    out = export_bundle(folder_env.graphs, [graph_named(folder_env, "Loose")], folder_env.folders)
    assert out["folders"] == []


def test_a_folder_id_that_names_no_folder_adds_none(folder_env: FolderEnv) -> None:
    seed(folder_env)
    folder_env.graphs.create(create_data("Dangling"), folder_id=fid(99))
    out = export_bundle(
        folder_env.graphs, [graph_named(folder_env, "Dangling")], folder_env.folders
    )
    assert out["folders"] == []
    assert out["graphs"][0]["folder_id"] == fid(99)


def test_without_a_folder_repository_the_folder_list_is_empty(folder_env: FolderEnv) -> None:
    seed(folder_env)
    out = export_bundle(folder_env.graphs)
    assert out["folders"] == []
    assert len(out["graphs"]) == 3


def test_an_export_survives_a_json_round_trip_into_the_other_backend(
    folder_env: FolderEnv, other_side: tuple[GraphRepository, FolderRepository]
) -> None:
    seed(folder_env)
    graphs, folders = other_side
    text = json.dumps(export_bundle(folder_env.graphs, None, folder_env.folders))
    report = import_bundle(graphs, json.loads(text), "new_ids", folders)
    assert (report.imported, report.failed, report.folders, report.errors) == (3, 0, 4, [])
    assert tree_of(folders) == tree_of(folder_env.folders)
    assert home_of(graphs, folders) == home_of(folder_env.graphs, folder_env.folders)


# --------------------------------------------------------------------------- the list itself


class BadList(NamedTuple):
    label: str
    value: Any


BAD_LISTS = [
    BadList("object", {}),
    BadList("text", "folders"),
    BadList("number", 5),
    BadList("null", None),
]


@pytest.mark.parametrize("case", BAD_LISTS, ids=[c.label for c in BAD_LISTS])
def test_a_folder_list_that_is_not_a_list_refuses_the_whole_bundle(
    folder_env: FolderEnv, case: BadList
) -> None:
    bundle = {**bundle_of([graph_dump(ID_A, "g")]), "folders": case.value}
    with pytest.raises(BundleError) as info:
        import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert info.value.message == "The bundle has no list of collections"
    assert folder_env.graphs.count() == 0


def test_a_folder_list_is_not_even_looked_at_without_a_folder_repository(
    folder_env: FolderEnv,
) -> None:
    bundle = {**bundle_of([graph_dump(ID_A, "g", 7)]), "folders": "nonsense"}
    report = import_bundle(folder_env.graphs, bundle)
    assert (report.imported, report.folders, report.errors) == (1, 0, [])
    assert home_of(folder_env.graphs, folder_env.folders) == {"g": None}


def test_a_bundle_without_the_folders_key_has_no_folders(folder_env: FolderEnv) -> None:
    bundle = bundle_of([graph_dump(ID_A, "g", 7)])
    del bundle["folders"]
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert report == ImportReport(1, 0, report.ids, [], 0)
    assert folder_env.folders.list_folders() == []


@pytest.mark.parametrize(("count", "ok"), [(2, True), (3, True), (4, False)])
def test_the_folder_count_cap_is_inclusive(
    folder_env: FolderEnv, monkeypatch: pytest.MonkeyPatch, count: int, ok: bool
) -> None:
    monkeypatch.setattr(bundle_folders, "FOLDERS_MAX", 3)
    items = [folder_dump(n, f"F{n}") for n in range(1, count + 1)]
    bundle = bundle_of([graph_dump(ID_A, "g")], items)
    if ok:
        report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
        assert report.folders == count
        return
    with pytest.raises(BundleError) as info:
        import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert info.value.message == "A bundle may hold at most 3 collections"
    assert folder_env.graphs.count() == 0  # refused before anything was stored


# --------------------------------------------------------------------------- new_ids import


def test_the_tree_is_created_with_new_ids_and_the_graphs_move_into_it(
    folder_env: FolderEnv,
) -> None:
    bundle = bundle_of(
        [graph_dump(ID_A, "In B", 2), graph_dump(ID_B, "In A", 1), graph_dump(ID_C, "Loose")],
        [folder_dump(1, "A"), folder_dump(2, "B", 1)],
    )
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert (report.imported, report.failed, report.folders, report.errors) == (3, 0, 2, [])
    assert tree_of(folder_env.folders) == {"A": None, "B": "A"}
    assert home_of(folder_env.graphs, folder_env.folders) == {
        "In B": "B",
        "In A": "A",
        "Loose": None,
    }
    assert not {fid(1), fid(2)} & {f.id for f in folder_env.folders.list_definitions()}


def test_a_child_listed_before_its_parent_is_still_created_below_it(
    folder_env: FolderEnv,
) -> None:
    bundle = bundle_of([], [folder_dump(2, "B", 1), folder_dump(1, "A")])
    assert import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders).folders == 2
    assert tree_of(folder_env.folders) == {"A": None, "B": "A"}


def test_importing_the_same_bundle_again_reuses_the_folders_and_adds_the_graphs(
    folder_env: FolderEnv,
) -> None:
    bundle = bundle_of([graph_dump(ID_A, "g", 2)], [folder_dump(1, "A"), folder_dump(2, "B", 1)])
    first = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    again = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert (first.folders, again.folders) == (2, 0)
    assert len(folder_env.folders.list_folders()) == 2
    (inner,) = [f for f in folder_env.folders.list_folders() if f.name == "B"]
    assert inner.graph_count == 2


@pytest.mark.parametrize("stored", ["finance", "FINANCE", "Finance"])
def test_a_same_named_folder_is_reused_ignoring_case(folder_env: FolderEnv, stored: str) -> None:
    existing = folder_env.folders.create_folder(body(stored)).id
    bundle = bundle_of([graph_dump(ID_A, "g", 1)], [folder_dump(1, "Finance")])
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert report.folders == 0
    assert [g.folder_id for g in folder_env.graphs.iter_definitions()] == [existing]


def test_a_composed_and_a_decomposed_letter_are_the_same_name(folder_env: FolderEnv) -> None:
    existing = folder_env.folders.create_folder(body("Café")).id
    bundle = bundle_of([graph_dump(ID_A, "g", 1)], [folder_dump(1, "Café")])
    assert import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders).folders == 0
    assert [g.folder_id for g in folder_env.graphs.iter_definitions()] == [existing]


def test_the_same_name_below_another_parent_is_another_folder(folder_env: FolderEnv) -> None:
    top = folder_env.folders.create_folder(body("B")).id
    bundle = bundle_of([graph_dump(ID_A, "g", 2)], [folder_dump(1, "A"), folder_dump(2, "B", 1)])
    assert import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders).folders == 2
    (graph,) = folder_env.graphs.iter_definitions()
    assert graph.folder_id not in {top, None}


def test_two_bundle_folders_that_differ_only_in_case_become_one(folder_env: FolderEnv) -> None:
    bundle = bundle_of(
        [graph_dump(ID_A, "one", 1), graph_dump(ID_B, "two", 2)],
        [folder_dump(1, "Q3"), folder_dump(2, "q3")],
    )
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert report.folders == 1
    assert len({g.folder_id for g in folder_env.graphs.iter_definitions()}) == 1


def test_a_folder_whose_parent_is_not_in_the_bundle_lands_at_the_top_level(
    folder_env: FolderEnv,
) -> None:
    bundle = bundle_of([graph_dump(ID_A, "g", 2)], [folder_dump(2, "Orphan", 1)])
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert (report.folders, report.errors) == (1, [])
    assert tree_of(folder_env.folders) == {"Orphan": None}
    assert home_of(folder_env.graphs, folder_env.folders) == {"g": "Orphan"}


def test_a_graph_whose_folder_is_not_in_the_bundle_lands_at_the_top_level(
    folder_env: FolderEnv,
) -> None:
    bundle = bundle_of([graph_dump(ID_A, "g", 5)], [folder_dump(1, "A")])
    import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert home_of(folder_env.graphs, folder_env.folders) == {"g": None}


def test_a_duplicated_folder_id_in_the_bundle_is_stored_once(folder_env: FolderEnv) -> None:
    bundle = bundle_of([], [folder_dump(1, "A"), folder_dump(1, "A")])
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert (report.folders, report.errors) == (1, [])


def test_of_two_folders_with_one_id_the_first_is_the_one_stored(folder_env: FolderEnv) -> None:
    bundle = bundle_of([], [folder_dump(1, "First"), folder_dump(1, "Second")])
    assert import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders).folders == 1
    assert tree_of(folder_env.folders) == {"First": None}


# --------------------------------------------------------------------------- what goes wrong


def test_a_cycle_is_reported_and_its_graphs_land_at_the_top_level(folder_env: FolderEnv) -> None:
    bundle = bundle_of(
        [graph_dump(ID_A, "in cycle", 2), graph_dump(ID_B, "below it", 3)],
        [
            folder_dump(1, "Fine"),
            folder_dump(2, "A", 3),
            folder_dump(3, "B", 2),
            folder_dump(4, "Self", 4),
        ],
    )
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert report.folders == 1
    assert report.errors == [f"collection {n}: {MSG_CYCLE}" for n in (2, 3, 4)]
    assert report.failed == 0  # no graph failed
    assert home_of(folder_env.graphs, folder_env.folders) == {"in cycle": None, "below it": None}


def test_invalid_folders_are_reported_by_position_and_the_others_still_import(
    folder_env: FolderEnv,
) -> None:
    newer = {**folder_dump(3, "Newer"), "schema_version": 99}
    bundle = bundle_of(
        [graph_dump(ID_A, "g", 4)],
        ["just text", {**folder_dump(2, "x"), "name": ""}, newer, folder_dump(4, "Good")],
    )
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert report.folders == 1
    assert report.errors == [
        "collection 1: not an object",
        "collection 2: name: String should have at least 1 character",
        "collection 3: Stored folder was written by a newer version of sankey-studio",
    ]
    assert (report.imported, report.failed) == (1, 0)
    assert home_of(folder_env.graphs, folder_env.folders) == {"g": "Good"}


def test_the_lines_of_the_report_follow_the_order_of_the_bundle(folder_env: FolderEnv) -> None:
    bundle = bundle_of([], [folder_dump(1, "A", 2), "not a folder", folder_dump(2, "B", 1)])
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert report.errors == [
        f"collection 1: {MSG_CYCLE}",
        "collection 2: not an object",
        f"collection 3: {MSG_CYCLE}",
    ]


def test_two_problems_of_one_folder_are_one_line(folder_env: FolderEnv) -> None:
    broken = {**folder_dump(1, "x"), "name": "", "revision": 0}
    report = import_bundle(
        folder_env.graphs, bundle_of([], [broken]), "new_ids", folder_env.folders
    )
    assert report.errors == [
        "collection 1: name: String should have at least 1 character (+1 more)"
    ]


def test_a_folder_error_never_echoes_the_input(folder_env: FolderEnv) -> None:
    broken = {**folder_dump(1, "x"), "name": "", "parent_id": "SECRET-TEXT"}
    report = import_bundle(
        folder_env.graphs, bundle_of([], [broken]), "new_ids", folder_env.folders
    )
    assert report.errors
    assert "SECRET" not in " ".join(report.errors)


def test_a_folder_over_the_depth_limit_is_reported_and_its_graphs_go_one_level_up(
    folder_env: FolderEnv,
) -> None:
    chain = [folder_dump(n, f"L{n}", n - 1 if n > 1 else None) for n in range(1, 10)]
    bundle = bundle_of([graph_dump(ID_A, "deep", 9), graph_dump(ID_B, "ok", 8)], chain)
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert (report.folders, report.errors) == (8, [f"collection 9: {MSG_DEPTH}"])
    assert home_of(folder_env.graphs, folder_env.folders) == {"deep": "L8", "ok": "L8"}


def test_a_backend_failure_while_creating_a_folder_aborts_the_import(
    folder_env: FolderEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(_data: Any) -> Any:
        raise StorageError("backend down")

    monkeypatch.setattr(folder_env.folders, "create_folder", down)
    bundle = bundle_of([graph_dump(ID_A, "g", 1)], [folder_dump(1, "A")])
    with pytest.raises(StorageError, match="backend down"):
        import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert folder_env.graphs.count() == 0


class Refusal(NamedTuple):
    label: str
    error: Exception


REFUSALS = [
    Refusal("name taken", FolderNameTakenError("A collection with this name exists")),
    Refusal("rule", FolderRuleError("At most 3 collections are allowed")),
    Refusal("parent gone", NotFoundError("Folder not found")),
]


@pytest.mark.parametrize("case", REFUSALS, ids=lambda c: c.label)
def test_a_refusal_of_the_store_is_one_line_and_the_children_use_the_parent(
    folder_env: FolderEnv, monkeypatch: pytest.MonkeyPatch, case: Refusal
) -> None:
    real = folder_env.folders.create_folder

    def refuse_b(data: Any) -> Any:
        if data.name == "B":
            raise case.error
        return real(data)

    monkeypatch.setattr(folder_env.folders, "create_folder", refuse_b)
    bundle = bundle_of(
        [graph_dump(ID_A, "in B", 2), graph_dump(ID_B, "in C", 3)],
        [folder_dump(1, "A"), folder_dump(2, "B", 1), folder_dump(3, "C", 2)],
    )
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert report.errors == [f"collection 2: {case.error}"]
    assert (report.imported, report.failed, report.folders) == (2, 0, 2)
    assert tree_of(folder_env.folders) == {"A": None, "C": "A"}
    assert home_of(folder_env.graphs, folder_env.folders) == {"in B": "A", "in C": "C"}


@pytest.mark.parametrize(("bad", "listed"), [(1, 2), (48, 49), (49, 50), (50, 50), (60, 50)])
def test_the_error_list_is_capped_at_fifty_across_folders_and_graphs(
    folder_env: FolderEnv, bad: int, listed: int
) -> None:
    bundle = bundle_of([{**graph_dump(ID_D, "g"), "name": ""}], ["not a folder"] * bad)
    report = import_bundle(folder_env.graphs, bundle, "new_ids", folder_env.folders)
    assert len(report.errors) == listed
    assert report.errors[0] == "collection 1: not an object"
    assert report.failed == 1  # the graph; folder problems are not failed graphs
    assert (report.errors[-1].startswith("graph 1: ")) is (bad < 50)


def test_a_failed_folder_is_not_counted_as_a_failed_graph(folder_env: FolderEnv) -> None:
    report = import_bundle(folder_env.graphs, bundle_of([], ["bad"]), "new_ids", folder_env.folders)
    assert (report.imported, report.failed, report.folders) == (0, 0, 0)
    assert report.errors == ["collection 1: not an object"]
