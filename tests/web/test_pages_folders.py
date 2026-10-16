# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The library and new-graph pages with ``?folder=``: boot data, fallback links, lenient value."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.models import FolderCreate, FolderDefinition, FolderUpdate
from tests.web.test_pages_support import Page, parse
from tests.web.test_routes_graphs_support import UNKNOWN_ID, put_graph

if TYPE_CHECKING:
    from tests.web.conftest import WebApp

NAV: Final = [("/", "Library"), ("/graphs/new", "New graph"), ("/settings", "Settings")]
FOLDER_KEYS: Final = {
    "id",
    "name",
    "parent_id",
    "revision",
    "updated_at",
    "graph_count",
    "child_count",
}
HOSTILE: Final = "</script><img src=x onerror=alert(1)>"


def folder(web: WebApp, name: str, parent: str | None = None) -> str:
    return web.services.folders().create_folder(FolderCreate(name=name, parent_id=parent)).id


def data_of(web: WebApp, path: str, **params: str) -> dict[str, Any]:
    response = web.client.get(path, params=params)
    assert response.status_code == 200
    return parse(response).data()


def links(web: WebApp, path: str, **params: str) -> list[tuple[str, str]]:
    return parse(web.client.get(path, params=params)).nav_links()


# --------------------------------------------------------------------------- the library


def test_the_boot_data_names_the_folders_and_no_scope_at_the_top_level(web: WebApp) -> None:
    top = folder(web, "Finance")
    folder(web, "Q3", top)
    data = data_of(web, "/")
    assert data["folder"] is None
    assert [f["name"] for f in data["folders"]] == ["Finance", "Q3"]
    assert set(data["folders"][0]) == FOLDER_KEYS
    assert (data["folders"][0]["child_count"], data["folders"][0]["graph_count"]) == (1, 0)


def test_the_top_level_lists_only_the_graphs_outside_every_folder(web: WebApp) -> None:
    inside = folder(web, "F")
    web.services.folders().move_graphs([put_graph(web, 1, "Filed")], inside)
    put_graph(web, 2, "Loose")
    data = data_of(web, "/")
    assert ([g["name"] for g in data["graphs"]], data["total"]) == (["Loose"], 1)


def test_a_folder_scope_lists_the_graphs_directly_in_it(web: WebApp) -> None:
    outer = folder(web, "Outer")
    inner = folder(web, "Inner", outer)
    filed, deeper = put_graph(web, 1, "Filed"), put_graph(web, 2, "Deeper")
    web.services.folders().move_graphs([filed], outer)
    web.services.folders().move_graphs([deeper], inner)
    put_graph(web, 3, "Loose")
    data = data_of(web, "/", folder=outer)
    assert data["folder"] == outer
    assert ([g["name"] for g in data["graphs"]], data["total"]) == (["Filed"], 1)
    assert [f["id"] for f in data["folders"]] == [inner, outer]  # all of them, by name


@pytest.mark.parametrize("value", [UNKNOWN_ID, "../etc", "root", "A" * 32, "", " ", "x" * 5000])
def test_an_unknown_or_invalid_folder_shows_the_top_level_and_never_an_error(
    web: WebApp, value: str
) -> None:
    folder(web, "F")
    put_graph(web, 1, "Loose")
    response = web.client.get("/", params={"folder": value})
    data = parse(response).data()
    assert response.status_code == 200
    assert (data["folder"], [g["name"] for g in data["graphs"]]) == (None, ["Loose"])


def test_other_query_parameters_are_ignored(web: WebApp) -> None:
    inside = folder(web, "F")
    response = web.client.get("/", params={"folder": inside, "utm_source": "x", "folder2": "y"})
    assert response.status_code == 200
    assert parse(response).data()["folder"] == inside


def test_the_noscript_list_has_the_folders_of_the_scope_then_its_graphs(web: WebApp) -> None:
    top = folder(web, "Finance")
    inner = folder(web, "Q3", top)
    archive = folder(web, "Archive")
    graph = put_graph(web, 1, "Budget")
    web.services.folders().move_graphs([graph], top)
    assert links(web, "/") == [
        *NAV,
        (f"/?folder={archive}", "Collection: Archive"),
        (f"/?folder={top}", "Collection: Finance"),
    ]
    assert links(web, "/", folder=top) == [
        *NAV,
        (f"/?folder={inner}", "Collection: Q3"),
        (f"/graphs/{graph}", "Budget"),
    ]
    assert links(web, "/", folder=inner) == NAV


def test_a_folder_whose_parent_is_gone_is_listed_at_the_top_level(web: WebApp) -> None:
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    orphan = FolderDefinition(
        id=f"{7:032x}", name="Orphan", parent_id=f"{8:032x}", created_at=stamp, updated_at=stamp
    )
    web.services.folders().put_folder(orphan)
    assert links(web, "/") == [*NAV, (f"/?folder={orphan.id}", "Collection: Orphan")]
    assert data_of(web, "/", folder=orphan.id)["folder"] == orphan.id


def test_a_folder_with_no_visible_name_still_gets_a_label(web: WebApp) -> None:
    hidden = folder(web, chr(0x202E))
    assert links(web, "/") == [*NAV, (f"/?folder={hidden}", "Collection: Untitled collection")]


# --------------------------------------------------------------------------- hostile names


def shape(page: Page) -> tuple[list[str], list[str]]:
    return page.tags, [name for name, _ in page.attrs]


def test_a_hostile_folder_name_is_inert_in_the_boot_data_and_the_fallback_list(
    web: WebApp,
) -> None:
    hostile = folder(web, "Plain")
    benign = parse(web.client.get("/"))
    update = FolderUpdate(name=HOSTILE, parent_id=None, revision=1)
    web.services.folders().update_folder(hostile, update)
    page = parse(web.client.get("/"))
    raw = web.client.get("/").text
    assert HOSTILE not in raw
    assert "<img" not in raw
    assert page.data()["folders"][0]["name"] == HOSTILE  # the JSON block keeps it exactly
    assert (f"/?folder={hostile}", f"Collection: {HOSTILE}") in page.nav_links()
    assert shape(page) == shape(benign)  # no tag and no attribute came from the name
    assert all(not name.startswith("on") for name in shape(page)[1])


def test_a_hostile_folder_name_adds_no_script(web: WebApp) -> None:
    folder(web, HOSTILE)
    scripts = parse(web.client.get("/")).scripts
    assert [s.attrs.get("id") for s in scripts if "src" not in s.attrs] == ["page-data"]


# --------------------------------------------------------------------------- the new-graph page


def test_the_new_graph_page_has_no_folder_by_default(web: WebApp) -> None:
    folder(web, "F")
    assert data_of(web, "/graphs/new")["folder_id"] is None


def test_the_new_graph_page_carries_an_existing_folder(web: WebApp) -> None:
    inside = folder(web, "F")
    data = data_of(web, "/graphs/new", folder=inside)
    assert (data["folder_id"], data["graph"]) == (inside, None)


@pytest.mark.parametrize("value", [UNKNOWN_ID, "../etc", "root", "A" * 32, "", " "])
def test_the_new_graph_page_ignores_an_unknown_or_invalid_folder(web: WebApp, value: str) -> None:
    folder(web, "F")
    assert data_of(web, "/graphs/new", folder=value)["folder_id"] is None


def test_the_new_graph_page_keeps_its_navigation_and_other_boot_keys(web: WebApp) -> None:
    inside = folder(web, "F")
    assert links(web, "/graphs/new", folder=inside) == NAV
    assert set(data_of(web, "/graphs/new", folder=inside)) == {
        "page",
        "remote_mode",
        "writes_allowed",
        "theme",
        "graph",
        "folder_id",
    }
