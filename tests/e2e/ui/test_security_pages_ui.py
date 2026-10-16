# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.12, hostile text on every page that shows it, at desktop and phone width.

One graph carries markup (``<img onerror>``, ``</script>``, ``<b>``), a direction override, a
control character, a 2000-emoji description and a hostile tag, chart title, node names and
categories. Nothing of it may become an element, run, open a dialog, break the page data or break
the layout; the chart shows the text as plain characters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import expect

from tests.e2e.support import ui_b_hostile as hostile
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.ui_b_common import PHONE, overflow_pixels
from tests.e2e.support.ui_b_compare import ComparePage
from tests.e2e.support.ui_b_editor import EditorPage
from tests.e2e.support.ui_b_library import LibraryPage
from tests.e2e.support.ui_b_viewer import ViewerPage
from tests.e2e.support.uiwait import wait_idle, wait_shell

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

SECOND_NAME = f"{hostile.IMG} second"
UNTITLED_NAME = f"{hostile.RLO}{hostile.BELL}"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


class Graphs:
    """The ids of the seeded graphs."""

    def __init__(self, first: str, second: str, untitled: str) -> None:
        self.first = first
        self.second = second
        self.untitled = untitled


@pytest.fixture(scope="module")
def graphs(module_server: LiveServer) -> Graphs:
    with make_client(module_server) as api:
        ids = [
            str(json_of(api.post("/api/v1/graphs", json=hostile.hostile_body(name)), 201)["id"])
            for name in (hostile.NAME, SECOND_NAME, UNTITLED_NAME)
        ]
    return Graphs(*ids)


@pytest.fixture
def inert(page: WatchedPage) -> hostile.Inert:
    return hostile.Inert.watch(page)


def no_stray_characters(page: WatchedPage, extra: str = "") -> None:
    """Direction overrides and the bell are gone from everything the person can read."""
    text = page.inner_text("body") + extra
    for character in (hostile.RLO, hostile.BELL):
        assert character not in text, f"U+{ord(character):04X} is visible"


def chart_text(chart: Any) -> str:
    return hostile.literal_text(chart)


# ------------------------------------------------------------------------------ library


@pytest.mark.usefixtures("graphs")
def test_the_library_shows_hostile_names_tags_descriptions_and_searches_as_text(
    page: WatchedPage, live_server: LiveServer, inert: hostile.Inert
) -> None:
    library = LibraryPage(page, live_server)
    library.goto("?sort=name-asc")
    expect(library.card(hostile.NAME)).to_have_count(1)
    expect(library.card(hostile.NAME).get_by_role("button", name=hostile.TAG)).to_be_visible()
    expect(library.card(hostile.NAME)).to_contain_text(hostile.EMOJI * 20)  # the long description
    expect(library.card("Untitled graph")).to_have_count(1)
    expect(library.tick("Untitled graph")).to_have_accessible_name(
        "Select “Untitled graph” to compare"
    )
    no_stray_characters(page)
    library.toggle_tag(hostile.TAG)  # the hostile tag filters through its chip and the address
    expect(library.tag_chip(hostile.TAG)).to_have_attribute("aria-pressed", "true")
    expect(library.count).to_contain_text(f"tagged “{hostile.TAG}”")
    page.reload()
    library.expect_ready()
    expect(library.tag_chip(hostile.TAG)).to_have_attribute("aria-pressed", "true")
    query = hostile.IMG.replace(
        "src=x", "src=nothing"
    )  # matches no graph: the empty result echoes it
    library.goto(f"?q={query}")
    expect(library.tid("library-no-results")).to_contain_text(f"“{query}”")
    expect(library.tid("library-search")).to_have_value(query)
    inert.check()


# ------------------------------------------------------------------------------ viewer


def test_the_viewer_draws_hostile_labels_literally_in_the_chart_donut_legend_and_table(
    page: WatchedPage, live_server: LiveServer, graphs: Graphs, inert: hostile.Inert
) -> None:
    viewer = ViewerPage(page, live_server, graphs.first)
    viewer.goto()
    expect(viewer.heading).to_have_text(hostile.NAME)
    expect(page).to_have_title(f"{hostile.NAME} - Sankey Studio")
    shown = chart_text(viewer.sankey)
    for label in hostile.LITERAL_NODES:
        assert label in shown, f"{label!r} is not drawn literally"
    assert viewer.sankey.locator(".sankey-node").count() == 5  # four hostile nodes and Hub
    viewer.sankey.locator(".sankey-node").first.hover(force=True)
    expect(page.locator(".hoverlayer .hovertext").first).to_be_visible()
    page.locator("[data-testid=links-table] summary").click()
    expect(viewer.tid("links-table")).to_contain_text(hostile.IMG)
    viewer.show_donut()
    donut = chart_text(viewer.donut)
    assert hostile.BOLD in donut
    assert hostile.CATEGORY_SCRIPT in donut
    expect(viewer.tid("category-row").filter(has_text=hostile.BOLD)).to_have_count(1)
    no_stray_characters(page, shown + donut)
    inert.check()


def test_the_boot_data_survives_a_closing_script_tag_and_invisible_names_read_untitled(
    page: WatchedPage, live_server: LiveServer, graphs: Graphs, inert: hostile.Inert
) -> None:
    viewer = ViewerPage(page, live_server, graphs.first)
    viewer.goto()
    boot = page.evaluate("JSON.parse(document.getElementById('page-data').textContent)")
    assert boot["graph"]["name"] == hostile.NAME
    assert boot["graph"]["tags"] == [hostile.TAG]
    inert.check()  # exactly one inline script: the (inert) JSON block
    untitled = ViewerPage(page, live_server, graphs.untitled)
    untitled.goto()
    expect(untitled.heading).to_have_text("Untitled graph")
    expect(page).to_have_title("Untitled graph - Sankey Studio")
    inert.check()


# ------------------------------------------------------------------------------ editor and compare


def test_the_editor_keeps_hostile_text_in_its_fields_and_tables(
    page: WatchedPage, live_server: LiveServer, graphs: Graphs, inert: hostile.Inert
) -> None:
    editor = EditorPage(page, live_server, graphs.first)
    editor.goto()
    expect(editor.heading).to_have_text(f"Edit {hostile.NAME}")
    editor.expect_details(  # the name and description fields and the tag chip
        name=hostile.NAME, description=hostile.DESCRIPTION, tags=(hostile.TAG,)
    )
    expect(editor.source).to_have_value(hostile.hostile_csv())
    expect(editor.tid("entries-row").filter(has_text=hostile.IMG)).to_have_count(1)
    expect(editor.tid("category-table")).to_contain_text(hostile.BOLD)
    editor.open_section("style")
    expect(editor.tid("style-title")).to_have_value(hostile.TITLE)  # the chart title field
    inert.check()
    editor.expect_settled()


def test_compare_shows_two_hostile_graphs_and_their_shared_colours_as_text(
    page: WatchedPage, live_server: LiveServer, graphs: Graphs, inert: hostile.Inert
) -> None:
    compare = ComparePage(page, live_server)
    compare.open_ids([graphs.first, graphs.second])
    expect(compare.cards).to_have_count(2)
    expect(compare.card(hostile.NAME)).to_be_visible()
    expect(compare.card(SECOND_NAME)).to_be_visible()
    last = compare.cards.get_by_test_id("sankey-chart").last
    expect(last).to_have_attribute("data-ready", "true")
    legend = compare.tid("compare-shared-colours")
    expect(legend).to_contain_text(hostile.BOLD)
    expect(legend).to_contain_text(hostile.CATEGORY_SCRIPT)
    assert hostile.IMG in chart_text(compare.card(hostile.NAME).get_by_test_id("sankey-chart"))
    inert.check()


@pytest.mark.parametrize("viewport", [PHONE], ids=["phone"])
def test_hostile_pages_fit_a_phone_and_stay_inert(
    page: WatchedPage, live_server: LiveServer, graphs: Graphs, inert: hostile.Inert
) -> None:
    for path in (
        "/",
        f"/graphs/{graphs.first}",
        f"/graphs/{graphs.first}/edit",
        f"/compare?ids={graphs.first},{graphs.second}",
    ):
        page.goto(live_server.url_for(path))
        wait_shell(page)
        wait_idle(page)
        expect(page.locator("[data-ready=false], [data-ready=error]")).to_have_count(0)
        assert overflow_pixels(page) <= 0, f"{path} scrolls sideways at 390px"
        inert.check()
