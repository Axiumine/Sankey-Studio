"""What the pages ask the repository for, and the navigation of the pages that have no graph.

A library page lists the folders once, asks the FOLDER repository for the newest 200 graphs of
its scope (``root`` or one folder id, ``offset=0``) and counts that scope; it never asks the graph
repository for a listing. A viewer, editor and compare page read each graph once by its exact id,
in the order asked. The static pages (new graph, settings) show exactly the common navigation and
nothing else, and ask no store at all unless the new-graph page names a folder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.models import FolderCreate
from tests.web.test_pages_support import parse
from tests.web.test_routes_graphs_support import PLAIN, UNKNOWN_ID, save

if TYPE_CHECKING:
    from sankey_studio.models import (
        FolderDefinition,
        FolderSummary,
        GraphCreate,
        GraphDefinition,
        GraphSummary,
    )
    from sankey_studio.storage.base import GraphRepository
    from sankey_studio.storage.folders_base import FolderRepository
    from tests.web.conftest import WebApp

NAV: Final = [("/", "Library"), ("/graphs/new", "New graph"), ("/settings", "Settings")]


class SpyRepo:
    """A repository that records every call (name and keyword arguments) and delegates."""

    def __init__(self, repo: GraphRepository) -> None:
        self.repo = repo
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_graphs(self, **kwargs: Any) -> list[GraphSummary]:
        self.calls.append(("list_graphs", kwargs))
        return self.repo.list_graphs(**kwargs)

    def count(self, **kwargs: Any) -> int:
        self.calls.append(("count", kwargs))
        return self.repo.count(**kwargs)

    def get(self, graph_id: str) -> GraphDefinition:
        self.calls.append(("get", {"graph_id": graph_id}))
        return self.repo.get(graph_id)

    def create(self, data: GraphCreate, *, folder_id: str | None = None) -> GraphDefinition:
        """Not recorded: tests store their graphs through the spy, then clear the calls."""
        return self.repo.create(data, folder_id=folder_id)


class FolderSpy:
    """A folder repository that records every call (name and keyword arguments) and delegates."""

    def __init__(self, repo: FolderRepository) -> None:
        self.repo = repo
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_folders(self) -> list[FolderSummary]:
        self.calls.append(("list_folders", {}))
        return self.repo.list_folders()

    def list_in(self, scope: str, *, limit: int = 200, offset: int = 0) -> list[GraphSummary]:
        self.calls.append(("list_in", {"scope": scope, "limit": limit, "offset": offset}))
        return self.repo.list_in(scope, limit=limit, offset=offset)

    def count_in(self, scope: str) -> int:
        self.calls.append(("count_in", {"scope": scope}))
        return self.repo.count_in(scope)

    def get_folder(self, folder_id: str) -> FolderDefinition:
        self.calls.append(("get_folder", {"folder_id": folder_id}))
        return self.repo.get_folder(folder_id)

    def create_folder(self, data: FolderCreate) -> FolderDefinition:
        """Not recorded: tests store their folders through the spy, then clear the calls."""
        return self.repo.create_folder(data)


@pytest.fixture
def spy(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> SpyRepo:
    repo = SpyRepo(web.services.graphs())
    monkeypatch.setattr(web.services, "graphs", lambda: repo)
    return repo


@pytest.fixture
def folder_spy(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> FolderSpy:
    repo = FolderSpy(web.services.folders())
    monkeypatch.setattr(web.services, "folders", lambda: repo)
    return repo


def test_the_library_lists_the_folders_then_asks_for_the_first_200_graphs_of_the_top_level(
    web: WebApp, spy: SpyRepo, folder_spy: FolderSpy
) -> None:
    assert web.client.get("/").status_code == 200
    assert folder_spy.calls == [
        ("list_folders", {}),
        ("list_in", {"scope": "root", "limit": 200, "offset": 0}),
        ("count_in", {"scope": "root"}),
    ]
    assert spy.calls == []  # the graph repository is not asked for a listing at all


def test_the_library_of_a_folder_asks_for_that_folder_only(
    web: WebApp, folder_spy: FolderSpy
) -> None:
    folder = folder_spy.create_folder(FolderCreate(name="Finance")).id
    assert web.client.get("/", params={"folder": folder}).status_code == 200
    assert folder_spy.calls == [
        ("list_folders", {}),
        ("list_in", {"scope": folder, "limit": 200, "offset": 0}),
        ("count_in", {"scope": folder}),
    ]


@pytest.mark.parametrize("value", [UNKNOWN_ID, "../x", "root", ""])
def test_an_invalid_or_unknown_folder_asks_for_the_top_level(
    web: WebApp, folder_spy: FolderSpy, value: str
) -> None:
    assert web.client.get("/", params={"folder": value}).status_code == 200
    assert folder_spy.calls[1:] == [
        ("list_in", {"scope": "root", "limit": 200, "offset": 0}),
        ("count_in", {"scope": "root"}),
    ]


def test_the_library_never_reads_a_graph_one_by_one(
    web: WebApp, spy: SpyRepo, folder_spy: FolderSpy
) -> None:
    save(web, "One", *PLAIN)
    spy.calls.clear()
    folder_spy.calls.clear()
    web.client.get("/")
    assert spy.calls == []
    assert [name for name, _ in folder_spy.calls] == ["list_folders", "list_in", "count_in"]


@pytest.mark.parametrize("suffix", ["", "/edit"])
def test_a_graph_page_reads_its_graph_once_by_the_exact_id(
    web: WebApp, spy: SpyRepo, suffix: str
) -> None:
    stored = save(web, "One", *PLAIN)
    spy.calls.clear()
    assert web.client.get(f"/graphs/{stored.id}{suffix}").status_code == 200
    assert spy.calls == [("get", {"graph_id": stored.id})]


def test_compare_reads_each_graph_once_in_the_order_of_the_ids(web: WebApp, spy: SpyRepo) -> None:
    first = save(web, "First", *PLAIN)
    second = save(web, "Second", *PLAIN)
    spy.calls.clear()
    response = web.client.get("/compare", params={"ids": f"{second.id},{first.id}"})
    assert response.status_code == 200
    assert spy.calls == [("get", {"graph_id": second.id}), ("get", {"graph_id": first.id})]


@pytest.mark.parametrize("path", ["/graphs/new", "/settings"])
def test_the_pages_without_a_graph_show_exactly_the_common_navigation(
    web: WebApp, spy: SpyRepo, folder_spy: FolderSpy, path: str
) -> None:
    page = parse(web.client.get(path))
    assert page.nav_links() == NAV
    assert page.tags.count("li") == len(NAV)
    assert spy.calls == []
    assert folder_spy.calls == []


def test_the_new_graph_page_asks_the_store_only_when_it_names_a_folder(
    web: WebApp, folder_spy: FolderSpy
) -> None:
    folder = folder_spy.create_folder(FolderCreate(name="Finance")).id
    web.client.get("/graphs/new", params={"folder": ""})
    assert folder_spy.calls == []
    web.client.get("/graphs/new", params={"folder": folder})
    assert folder_spy.calls == [("get_folder", {"folder_id": folder})]
