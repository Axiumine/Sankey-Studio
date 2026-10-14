"""Bundles over HTTP carry the folders of the exported graphs and rebuild them on import."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.models import FolderCreate, GraphCreate
from sankey_studio.storage.bundle import export_bundle
from sankey_studio.web.routers import folders, graphs
from sankey_studio.web.routers.graphs import encode_bundle
from tests.web.test_routes_graphs_support import API, PLAIN, code, graph_json

if TYPE_CHECKING:
    from httpx2 import Response

    from tests.web.conftest import AppFactory, WebApp

EXPORT: Final = f"{API}/graphs/export"
IMPORT: Final = f"{API}/graphs/import"
JSON_HEADERS: Final = {"Content-Type": "application/json"}
TOO_LARGE: Final = "The export is larger than a bundle import accepts; export fewer graphs"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router, folders.router])


def folder(web: WebApp, name: str, parent: str | None = None) -> str:
    return web.services.folders().create_folder(FolderCreate(name=name, parent_id=parent)).id


def graph_in(web: WebApp, name: str, folder_id: str | None) -> str:
    body = GraphCreate.model_validate(graph_json(name, *PLAIN))
    return web.services.graphs().create(body, folder_id=folder_id).id


def export(web: WebApp, *ids: str) -> Response:
    return web.client.get(EXPORT, params={"ids": ",".join(ids)})


def import_text(web: WebApp, text: str) -> Response:
    return web.client.post(IMPORT, content=text, headers=JSON_HEADERS)


def library(web: WebApp) -> dict[str, Any]:
    """``{folder name: [parent name, [graph names]]}`` of the stored library."""
    stored = web.services.folders().list_definitions()
    names = {f.id: f.name for f in stored}
    inside: dict[str, list[str]] = {f.name: [] for f in stored}
    for graph in web.services.graphs().iter_definitions():
        if graph.folder_id in names:
            inside[names[graph.folder_id]].append(graph.name)
    return {f.name: [names.get(f.parent_id or ""), sorted(inside[f.name])] for f in stored}


# --------------------------------------------------------------------------- export


def test_the_export_carries_the_folders_of_its_graphs_and_their_ancestors_only(
    web: WebApp,
) -> None:
    top = folder(web, "Finance")
    mid = folder(web, "Q3", top)
    folder(web, "Empty")
    other = folder(web, "Travel")
    wanted = graph_in(web, "In Q3", mid)
    graph_in(web, "Elsewhere", other)
    bundle = export(web, wanted).json()
    assert list(bundle) == ["format", "version", "graphs", "folders"]
    assert [f["id"] for f in bundle["folders"]] == [top, mid]
    assert bundle["folders"][1]["parent_id"] == top
    assert [g["folder_id"] for g in bundle["graphs"]] == [mid]


def test_a_graph_at_the_top_level_exports_an_empty_folder_list(web: WebApp) -> None:
    folder(web, "Unused")
    loose = graph_in(web, "Loose", None)
    response = export(web, loose)
    assert response.json()["folders"] == []
    assert response.text.endswith('\n  ],\n  "folders": []\n}')


def test_the_bytes_are_those_of_a_whole_json_dumps_with_folders(web: WebApp) -> None:
    top = folder(web, "Finance")
    mid = folder(web, "Q3", top)
    ids = [graph_in(web, "One", mid), graph_in(web, "Two", None), graph_in(web, "Three", top)]
    whole = export_bundle(web.services.graphs(), ids, web.services.folders())
    assert export(web, *ids).content == json.dumps(whole, indent=2).encode()


def test_a_folder_that_no_longer_exists_is_not_exported(web: WebApp) -> None:
    gone = folder(web, "Gone")
    graph = graph_in(web, "g", gone)
    web.services.folders().delete_folder(gone)  # the graph moved up: nothing dangles
    assert export(web, graph).json()["folders"] == []


class ListSpy:
    """Counts the listings asked of a folder repository."""

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self.listed = 0

    def list_definitions(self) -> Any:
        self.listed += 1
        return self.repo.list_definitions()


def test_the_folders_are_only_listed_when_a_graph_sits_in_one(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside = folder(web, "F")
    loose, filed = graph_in(web, "Loose", None), graph_in(web, "Filed", inside)
    spy = ListSpy(web.services.folders())
    monkeypatch.setattr(web.services, "folders", lambda: spy)
    assert export(web, loose).status_code == 200
    assert spy.listed == 0
    assert export(web, loose, filed).status_code == 200
    assert spy.listed == 1


def test_encode_bundle_without_a_folder_source_carries_no_folder(web: WebApp) -> None:
    inside = folder(web, "F")
    graph = graph_in(web, "Filed", inside)
    body = encode_bundle(web.services.graphs().get, [graph], 1 << 40)
    bundle = json.loads(body)
    assert bundle["folders"] == []  # no source of folders was given
    assert bundle["graphs"][0]["folder_id"] == inside


def test_the_folders_count_against_the_import_cap(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    top = folder(web, "Finance")
    mid = folder(web, "Q3", top)
    graph = graph_in(web, "g", mid)
    size = len(export(web, graph).content)
    monkeypatch.setattr(graphs, "IMPORT_BODY_BYTES", size)
    assert export(web, graph).status_code == 200
    monkeypatch.setattr(graphs, "IMPORT_BODY_BYTES", size - 1)
    refused = export(web, graph)
    assert (refused.status_code, code(refused)) == (422, "bundle_error")
    assert refused.json()["error"]["message"] == TOO_LARGE
    assert refused.json()["error"]["details"] == [f"limit_bytes={size - 1}"]


# --------------------------------------------------------------------------- import


def wipe(web: WebApp) -> None:
    """Delete every graph and folder (children first), so an import meets an empty library."""
    for graph in list(web.services.graphs().iter_definitions()):
        web.services.graphs().delete(graph.id)
    for item in reversed(web.services.folders().list_definitions()):
        web.services.folders().delete_folder(item.id)


def stamp_folder(number: int, name: str, parent: int | None = None) -> dict[str, Any]:
    """A folder as a bundle holds it (the persisted shape)."""
    return {
        "id": f"{number:032x}",
        "name": name,
        "parent_id": None if parent is None else f"{parent:032x}",
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2020-01-01T00:00:00Z",
    }


def bundle_with(folders_: list[Any], graphs_: list[Any] | None = None) -> dict[str, Any]:
    return {
        "format": "sankey-studio/graphs",
        "version": 2,
        "graphs": graphs_ or [],
        "folders": folders_,
    }


def test_an_exported_bundle_rebuilds_the_tree_in_an_empty_library(web: WebApp) -> None:
    top = folder(web, "Finance")
    mid = folder(web, "Q3", top)
    text = export(web, graph_in(web, "In Q3", mid), graph_in(web, "In Finance", top)).text
    before = library(web)
    old_ids = {f.id for f in web.services.folders().list_definitions()}
    wipe(web)
    report = import_text(web, text).json()
    assert (report["imported"], report["failed"], report["folders"], report["errors"]) == (
        2,
        0,
        2,
        [],
    )
    assert library(web) == before
    assert not old_ids & {f.id for f in web.services.folders().list_definitions()}


def test_importing_the_same_bundle_again_reuses_the_folders(web: WebApp) -> None:
    top = folder(web, "Finance")
    mid = folder(web, "Q3", top)
    text = export(web, graph_in(web, "In Q3", mid), graph_in(web, "In Finance", top)).text
    report = import_text(web, text).json()
    assert (report["imported"], report["folders"]) == (2, 0)
    assert library(web) == {
        "Finance": [None, ["In Finance", "In Finance"]],
        "Q3": ["Finance", ["In Q3", "In Q3"]],
    }
    assert web.services.graphs().count() == 4


def test_a_bundle_of_folders_only_creates_them_with_new_ids(web: WebApp) -> None:
    body = bundle_with([stamp_folder(10, "A"), stamp_folder(11, "B", 10)])
    report = web.client.post(IMPORT, json=body).json()
    assert report == {"imported": 0, "failed": 0, "ids": [], "errors": [], "folders": 2}
    stored = web.services.folders().list_definitions()
    assert sorted(f.name for f in stored) == ["A", "B"]
    assert not {f"{10:032x}", f"{11:032x}"} & {f.id for f in stored}


def test_a_bad_folder_is_a_line_of_the_report_and_the_rest_is_stored(web: WebApp) -> None:
    body = bundle_with([5, stamp_folder(1, "Good"), {**stamp_folder(2, "x"), "name": ""}])
    report = web.client.post(IMPORT, json=body).json()
    assert (report["failed"], report["folders"]) == (0, 1)  # a folder is not a failed graph
    assert report["errors"] == [
        "collection 1: not an object",
        "collection 3: name: String should have at least 1 character",
    ]


def test_a_saved_write_back_consent_does_not_survive_an_import(web: WebApp) -> None:
    source = {"type": "text", "origin": "file", "path": "budget.csv"}
    pref = {"mode": "source", "target": "file:budget.csv"}
    stored = {**graph_json("with consent", *PLAIN), "id": "a" * 32}
    stored.update(source={**source, "write_back": pref}, created_at="2020-01-01T00:00:00Z")
    stored["updated_at"] = "2020-01-01T00:00:00Z"
    report = web.client.post(IMPORT, json=bundle_with([], [stored])).json()
    assert (report["imported"], report["failed"]) == (1, 0)
    (graph,) = web.services.graphs().iter_definitions()
    assert getattr(graph.source, "write_back", "missing") is None


@pytest.mark.parametrize("value", [{}, "x", 5, None])
def test_a_folder_list_that_is_not_a_list_is_a_422_and_stores_nothing(
    web: WebApp, value: Any
) -> None:
    response = web.client.post(IMPORT, json={**bundle_with([]), "folders": value})
    assert (response.status_code, code(response)) == (422, "bundle_error")
    assert response.json()["error"]["message"] == "The bundle has no list of collections"


@pytest.mark.parametrize(("count", "status"), [(1000, 200), (1001, 422)])
def test_a_bundle_holds_at_most_1000_folders(web: WebApp, count: int, status: int) -> None:
    response = web.client.post(IMPORT, json=bundle_with(["bad"] * count))
    assert response.status_code == status
    if status == 422:
        assert code(response) == "bundle_error"
        assert "at most 1000 collections" in response.json()["error"]["message"]
        assert web.services.folders().list_folders() == []


def test_a_hostile_folder_name_survives_an_export_and_import_unchanged(web: WebApp) -> None:
    name = f"<img src=x onerror=alert(1)>{chr(0x202E)}"
    inside = folder(web, name)
    text = export(web, graph_in(web, "g", inside)).text
    wipe(web)
    assert import_text(web, text).json()["folders"] == 1
    assert [f.name for f in web.services.folders().list_definitions()] == [name]
