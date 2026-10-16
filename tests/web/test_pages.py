# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The six HTML pages: status, template, boot data, links, 404/422 answers, remote mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.models import GraphCreate
from sankey_studio.web.routers import pages
from sankey_studio.web.schemas.queries import LIST_LIMIT_MAX
from tests.web.test_pages_support import DATA_ID, JSON_TYPE, parse
from tests.web.test_routes_graphs_support import (
    MALFORMED_IDS,
    PLAIN,
    UNKNOWN_ID,
    code,
    graph_json,
    ids_of,
    put_graph,
    save,
)

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, Mode, WebApp

HTML = "text/html; charset=utf-8"
NAV = [("/", "Library"), ("/graphs/new", "New graph"), ("/settings", "Settings")]
SUMMARY_KEYS = {
    "id",
    "name",
    "description",
    "tags",
    "source_type",
    "revision",
    "updated_at",
    "folder_id",
}


class Case(NamedTuple):
    path: str
    page: str
    heading: str


CASES = [
    Case("/", "library", "Graphs"),
    Case("/graphs/new", "new", "New graph"),
    Case("/settings", "settings", "Settings"),
]


def links_of(web: WebApp, path: str) -> list[tuple[str, str]]:
    """The ``(href, text)`` of the navigation and the fallback list, read from the HTML itself."""
    return parse(web.client.get(path)).nav_links()


@pytest.mark.parametrize("case", CASES, ids=[c.path for c in CASES])
def test_a_static_page_renders_its_template(web: WebApp, case: Case) -> None:
    response = web.client.get(case.path)
    page = parse(response)
    assert response.status_code == 200
    assert response.headers["content-type"] == HTML
    assert f'data-page="{case.page}"' in response.text
    assert f"<h1>{case.heading}</h1>" in response.text
    assert f"<title>{case.heading} - Sankey Studio</title>" in response.text
    assert response.text.startswith("<!doctype html>")
    data = [s for s in page.scripts if s.attrs.get("type") == JSON_TYPE]
    assert [s.attrs["id"] for s in data] == [DATA_ID]
    assert all("src" in s.attrs for s in page.scripts if s not in data)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", [case.path for case in CASES])
def test_a_page_carries_exactly_one_cache_control_header_and_it_is_no_store(
    web: WebApp, path: str
) -> None:
    raw = web.client.get(path).headers.raw
    assert [(name, value) for name, value in raw if name.lower() == b"cache-control"] == [
        (b"cache-control", b"no-store")
    ]


def test_the_new_and_settings_pages_carry_only_the_common_boot_data(web: WebApp) -> None:
    common = {"remote_mode": False, "writes_allowed": True, "theme": "system"}
    new = parse(web.client.get("/graphs/new")).data()
    settings = parse(web.client.get("/settings")).data()
    assert new == {"page": "new", "graph": None, "folder_id": None, **common}
    assert settings == {"page": "settings", **common}


def test_an_empty_library_has_no_graphs_and_the_navigation(web: WebApp) -> None:
    data = parse(web.client.get("/")).data()
    assert data == {
        "page": "library",
        "remote_mode": False,
        "writes_allowed": True,
        "theme": "system",
        "graphs": [],
        "total": 0,
        "folders": [],
        "folder": None,
    }
    assert links_of(web, "/") == NAV


def test_the_library_lists_the_newest_graphs_first_with_links(web: WebApp) -> None:
    older = put_graph(web, 1, "Older", ["b", "a"])
    newer = put_graph(web, 2, "Newer")
    response = web.client.get("/")
    data = parse(response).data()
    assert [g["id"] for g in data["graphs"]] == [newer, older]
    assert data["total"] == 2
    assert set(data["graphs"][0]) == SUMMARY_KEYS
    assert data["graphs"][1]["tags"] == ["b", "a"]
    assert links_of(web, "/") == [
        *NAV,
        (f"/graphs/{newer}", "Newer"),
        (f"/graphs/{older}", "Older"),
    ]


def test_the_library_page_asks_for_the_first_200_graphs() -> None:
    assert LIST_LIMIT_MAX == 200


@pytest.mark.parametrize(("count", "listed"), [(3, 3), (4, 3)])
def test_the_library_page_lists_at_most_the_page_limit_and_counts_all(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, count: int, listed: int
) -> None:
    monkeypatch.setattr(pages, "LIST_LIMIT_MAX", 3)
    repo = web.services.graphs()
    for number in range(count):
        repo.create(GraphCreate.model_validate(graph_json(f"G{number}", *PLAIN)))
    data = parse(web.client.get("/")).data()
    assert len(data["graphs"]) == listed
    assert data["total"] == count


class View(NamedTuple):
    path: str
    page: str
    heading: str
    other: tuple[str, str]


def views(graph_id: str) -> list[View]:
    return [
        View(f"/graphs/{graph_id}", "viewer", "Budget 2026", (f"/graphs/{graph_id}/edit", "Edit")),
        View(
            f"/graphs/{graph_id}/edit",
            "edit",
            "Edit Budget 2026",
            (f"/graphs/{graph_id}", "View"),
        ),
    ]


@pytest.mark.parametrize("index", [0, 1], ids=["viewer", "edit"])
def test_a_graph_page_shows_the_summary_of_the_stored_graph(web: WebApp, index: int) -> None:
    stored = save(web, "Budget 2026", *PLAIN, description="Plan", tags=["home"])
    view = views(stored.id)[index]
    response = web.client.get(view.path)
    data = parse(response).data()
    assert response.status_code == 200
    assert f'data-page="{view.page}"' in response.text
    assert f"<h1>{view.heading}</h1>" in response.text
    assert links_of(web, view.path) == [*NAV, view.other]
    assert data["page"] == view.page
    assert data["graph"] == {
        "id": stored.id,
        "name": "Budget 2026",
        "description": "Plan",
        "tags": ["home"],
        "source_type": "manual",
        "revision": 1,
        "updated_at": stored.updated_at.isoformat().replace("+00:00", "Z"),
        "folder_id": None,
    }


def test_a_graph_page_never_embeds_the_source_data(web: WebApp) -> None:
    stored = save(web, "Secrets", ("TopSecretNode", "b", 1.0, None))
    for suffix in ("", "/edit"):
        assert "TopSecretNode" not in web.client.get(f"/graphs/{stored.id}{suffix}").text


@pytest.mark.parametrize("suffix", ["", "/edit"])
@pytest.mark.parametrize("graph_id", [UNKNOWN_ID, *MALFORMED_IDS])
def test_an_unknown_or_malformed_id_is_a_404_envelope(
    web: WebApp, graph_id: str, suffix: str
) -> None:
    response = web.client.get(f"/graphs/{graph_id}{suffix}")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "error": {"code": "not_found", "message": "Graph not found", "details": []}
    }


def compare(web: WebApp, ids: str) -> Any:
    return web.client.get("/compare", params={"ids": ids})


def test_compare_lists_the_graphs_in_the_order_of_the_ids(web: WebApp) -> None:
    # fixed ids (0...01 < 0...02): the order asked for is NOT the sorted one, on every run
    first = put_graph(web, 1, "First")
    second = put_graph(web, 2, "Second")
    assert sorted([second, first]) == [first, second]
    response = compare(web, f"{second},{first},{second}")
    data = parse(response).data()
    assert response.status_code == 200
    assert 'data-page="compare"' in response.text
    assert "<h1>Compare graphs</h1>" in response.text
    assert data["ids"] == [second, first]
    assert [g["id"] for g in data["graphs"]] == [second, first]
    assert [g["name"] for g in data["graphs"]] == ["Second", "First"]
    assert set(data["graphs"][0]) == SUMMARY_KEYS
    expected = [*NAV, (f"/graphs/{second}", "Second"), (f"/graphs/{first}", "First")]
    assert links_of(web, f"/compare?ids={second},{first}") == expected


def test_compare_with_an_unknown_id_is_a_page_that_lists_it_as_missing(web: WebApp) -> None:
    known = save(web, "Known", *PLAIN)
    response = compare(web, f"{UNKNOWN_ID},{known.id}")
    data = parse(response).data()
    assert response.status_code == 200
    assert data["ids"] == [UNKNOWN_ID, known.id]
    assert [g["id"] for g in data["graphs"]] == [known.id]
    assert data["missing"] == [UNKNOWN_ID]
    assert links_of(web, f"/compare?ids={UNKNOWN_ID},{known.id}")[-1] == (
        f"/graphs/{known.id}",
        "Known",
    )


def test_compare_of_only_unknown_ids_is_still_a_page(web: WebApp) -> None:
    data = parse(compare(web, UNKNOWN_ID)).data()
    assert (data["ids"], data["graphs"], data["missing"]) == ([UNKNOWN_ID], [], [UNKNOWN_ID])


def test_compare_with_only_known_ids_misses_nothing(web: WebApp) -> None:
    known = save(web, "Known", *PLAIN)
    assert parse(compare(web, known.id)).data()["missing"] == []


@pytest.mark.parametrize("ids", ["short", "x" * 32, "A" * 32, f"{'a' * 32},short"])
def test_compare_with_a_malformed_id_is_a_422(web: WebApp, ids: str) -> None:
    response = compare(web, ids)
    assert response.status_code == 422
    assert code(response) == "validation_error"


@pytest.mark.parametrize(
    "path", ["/compare", "/compare?ids=", "/compare?ids=,", "/compare?ids=%20"]
)
def test_compare_without_ids_is_the_empty_compare_page(web: WebApp, path: str) -> None:
    response = web.client.get(path)
    data = parse(response).data()
    assert response.status_code == 200
    assert (data["page"], data["ids"], data["graphs"], data["missing"]) == ("compare", [], [], [])
    assert response.headers["cache-control"] == "no-store"
    assert links_of(web, path) == NAV


def test_compare_ignores_blank_pieces_and_repeats(web: WebApp) -> None:
    first = put_graph(web, 1, "First")
    data = parse(compare(web, f"{first},,{first},")).data()
    assert data["ids"] == [first]


def test_compare_still_refuses_an_unknown_query_parameter(web: WebApp) -> None:
    response = web.client.get("/compare", params={"theme": "dark"})
    assert response.status_code == 422
    assert code(response) == "validation_error"


@pytest.mark.parametrize(("count", "status"), [(12, 200), (13, 422)])
def test_compare_takes_at_most_twelve_ids(web: WebApp, count: int, status: int) -> None:
    # twelve well-formed ids pass the query model (and are then missing), thirteen do not
    response = compare(web, ids_of(count))
    assert response.status_code == status
    if status == 200:
        assert len(parse(response).data()["missing"]) == count


def test_the_pages_are_get_only(web: WebApp) -> None:
    stored = save(web, "Any", *PLAIN)
    for path in ("/", "/graphs/new", f"/graphs/{stored.id}", f"/graphs/{stored.id}/edit"):
        response = web.client.post(path, json={})
        assert response.status_code == 405
        assert code(response) == "method_not_allowed"


@pytest.mark.parametrize(
    ("mode", "remote_mode", "writes_allowed"),
    [("local", False, True), ("remote_read_only", True, False), ("remote_writes", True, True)],
)
def test_the_boot_data_tells_the_page_about_remote_mode(
    make_app: AppFactory, mode: Mode, remote_mode: bool, writes_allowed: bool
) -> None:
    web = make_app(mode=mode)
    for path in ("/", "/graphs/new", "/settings"):
        data = parse(web.client.get(path)).data()
        assert (data["remote_mode"], data["writes_allowed"]) == (remote_mode, writes_allowed)
