"""What the pages ask the repository for, and the navigation of the pages that have no graph.

A library page asks for the newest 200 graphs with NO filter (``query=None, tag=None``,
``offset=0``) and counts with NO filter; a viewer, editor and compare page read each graph once
by its exact id, in the order asked. The static pages (new graph, settings) show exactly the
common navigation and nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from tests.web.test_pages_support import parse
from tests.web.test_routes_graphs_support import PLAIN, save

if TYPE_CHECKING:
    from sankey_studio.models import GraphCreate, GraphDefinition, GraphSummary
    from sankey_studio.storage.base import GraphRepository
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

    def create(self, data: GraphCreate) -> GraphDefinition:
        """Not recorded: tests store their graphs through the spy, then clear the calls."""
        return self.repo.create(data)


@pytest.fixture
def spy(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> SpyRepo:
    repo = SpyRepo(web.services.graphs())
    monkeypatch.setattr(web.services, "graphs", lambda: repo)
    return repo


def test_the_library_asks_for_the_first_200_graphs_and_counts_without_a_filter(
    web: WebApp, spy: SpyRepo
) -> None:
    assert web.client.get("/").status_code == 200
    assert spy.calls == [
        ("list_graphs", {"query": None, "tag": None, "limit": 200, "offset": 0}),
        ("count", {"query": None, "tag": None}),
    ]


def test_the_library_never_reads_a_graph_one_by_one(web: WebApp, spy: SpyRepo) -> None:
    save(web, "One", *PLAIN)
    spy.calls.clear()
    web.client.get("/")
    assert [name for name, _ in spy.calls] == ["list_graphs", "count"]


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
    web: WebApp, spy: SpyRepo, path: str
) -> None:
    page = parse(web.client.get(path))
    assert page.nav_links() == NAV
    assert page.tags.count("li") == len(NAV)
    assert spy.calls == []
