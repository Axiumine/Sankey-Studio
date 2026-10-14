"""B1: smoke test of the app shell and navigation, then the keyboard-only paths.

Library empty state, the header links to New / Settings / Library and the compare page, the
keyboard path from the library through the editor to a saved graph, the focus ring, the dialog
that Escape closes, and the arrow keys on the chart tabs. "No console error, page error, CSP
violation or failed request" is asserted for every page these tests visit by the ``page`` fixture
(it fails the test at teardown otherwise). Each test has its own server: the empty-library checks
need an empty library.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.pages import AppPage
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_keyboard import focus_ring, focused, tab_until
from tests.e2e.support.ui_a_viewer import ViewerPage
from tests.e2e.support.ui_a_wizard import NewGraphWizard
from tests.e2e.support.uiwait import wait_charts, wait_editor, wait_page, wait_shell

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

HEADER_ORDER = ["skip-link", "brand", "nav-library", "nav-new"]
MIN_RING_PX = 2.0


class LibraryPage(AppPage):
    path = "/"
    name = "library"


# ------------------------------------------------------------------------------ navigation
# Tests with a server of their own list ``live_server`` before ``page``: fixtures are torn down in
# reverse order, so the browser context closes while the server is still up (Chrome asks for the
# favicon late, and a stopped server would answer that with ERR_CONNECTION_REFUSED).


def test_an_empty_library_invites_a_first_graph_and_the_header_links_reach_every_page(
    live_server: LiveServer, page: WatchedPage
) -> None:
    library = LibraryPage(page, live_server)

    response = library.goto()

    assert response is not None
    assert response.status == 200
    expect(library.heading).to_have_text("Graphs")
    empty = library.tid("library-empty")
    expect(empty).to_contain_text("No graphs yet")
    expect(empty.get_by_role("link", name="Create your first graph")).to_have_attribute(
        "href", "/graphs/new"
    )
    expect(library.tid("graph-card")).to_have_count(0)
    expect(library.nav("library")).to_have_attribute("aria-current", "page")

    library.nav("new").click()
    wait_page(page, "new")
    expect(library.heading).to_have_text("New graph")
    expect(library.tid("new-wizard")).to_be_visible()
    assert page.url == live_server.url_for("/graphs/new")

    library.nav("settings").click()
    wait_page(page, "settings")
    expect(library.heading).to_have_text("Settings")
    expect(library.tid("settings-save")).to_be_visible()

    page.get_by_label("Sankey Studio, home").click()
    wait_page(page, "library")
    expect(library.heading).to_have_text("Graphs")

    library.nav("settings").click()
    library.nav("library").click()
    wait_page(page, "library")
    expect(library.nav("library")).to_have_attribute("aria-current", "page")


def test_the_compare_page_is_empty_without_graphs_and_opens_from_the_library(
    live_server: LiveServer, page: WatchedPage, api: httpx.Client
) -> None:
    library = LibraryPage(page, live_server)
    page.goto("/compare")
    wait_shell(page)
    wait_page(page, "compare")
    expect(library.heading).to_have_text("Compare graphs")
    expect(library.tid("state-empty")).to_contain_text("Nothing to compare yet")

    first = seed_graph(api, unique_name("Compare A"), graph_draft(BUDGET.csv))
    second = seed_graph(api, unique_name("Compare B"), graph_draft(BUDGET_CATEGORISED.csv))
    library.goto()
    library.tid("compare-select").nth(0).check()
    library.tid("compare-select").nth(1).check()
    expect(library.tid("selection-bar")).to_contain_text("2 graphs selected")
    library.tid("compare-open").click()

    wait_page(page, "compare")
    cards = library.tid("compare-card")
    expect(cards).to_have_count(2)
    wait_charts(page, 2)
    assert {first["id"], second["id"]} == {
        card.get_attribute("data-graph-id") for card in cards.all()
    }


# ------------------------------------------------------------------------------ keyboard only


def test_a_graph_can_be_created_and_saved_with_the_keyboard_alone(
    live_server: LiveServer, page: WatchedPage, api: httpx.Client
) -> None:
    library = LibraryPage(page, live_server)
    library.goto()

    assert tab_until(page, "nav-new") == HEADER_ORDER
    assert focus_ring(page)[0] == "solid"
    assert focus_ring(page)[1] >= MIN_RING_PX
    page.keyboard.press("Enter")
    wizard = NewGraphWizard(page)
    wizard.expect_showing()
    expect(wizard.tid("editor-name")).to_be_focused()  # the wizard starts on the name
    name = unique_name("Keyboard graph")
    page.keyboard.type(name)
    tab_until(page, "wizard-next")
    page.keyboard.press("Enter")
    wizard.expect_step("source")
    tab_until(page, "source-content")
    page.keyboard.type(BUDGET.csv)
    tab_until(page, "wizard-create")
    page.keyboard.press("Enter")
    wizard.expect_gone()
    editor = EditorPage(page, live_server)
    wait_editor(page)

    assert tab_until(page, "graph-settings-button") == ["graph-settings-button"]
    assert tab_until(page, "chart-tab-sankey") == ["chart-tab-sankey"]
    assert tab_until(page, "chart-settings-button")[-1] == "chart-settings-button"
    editor.wait_preview()
    editor.expect_stats(nodes=10, links=9, total_in=3800, total_out=3800, columns=4)
    tab_until(page, "save-button")
    assert focus_ring(page)[1] >= MIN_RING_PX
    page.keyboard.press("Enter")

    page.wait_for_url(re.compile(r"/graphs/[0-9a-f]{32}/edit$"))
    expect(editor.save_status).to_contain_text("All changes saved")
    assert focused(page) == "save-button"
    found = json_of(api.get("/api/v1/graphs", params={"q": name}))
    assert [item["name"] for item in found["items"]] == [name]


def test_escape_closes_the_delete_dialog_and_the_chart_tabs_follow_the_arrow_keys(
    live_server: LiveServer, page: WatchedPage, api: httpx.Client
) -> None:
    name = unique_name("Keep me")
    saved = seed_graph(api, name, graph_draft(BUDGET_CATEGORISED.csv))
    library = LibraryPage(page, live_server)
    library.goto()
    delete = library.tid("graph-delete")

    delete.focus()
    page.keyboard.press("Enter")

    dialog = library.tid("delete-dialog")
    expect(dialog).to_be_visible()
    expect(library.tid("confirm-dialog-cancel")).to_be_focused()
    page.keyboard.press("Tab")
    assert focused(page) == "delete-confirm"
    page.keyboard.press("Tab")
    assert focused(page) == "confirm-dialog-cancel"
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(delete).to_be_focused()
    assert json_of(api.get(f"/api/v1/graphs/{saved['id']}"))["name"] == name

    viewer = ViewerPage(page, live_server)
    viewer.open(saved["id"])
    sankey_tab = viewer.tid("chart-tab-sankey")
    donut_tab = viewer.tid("chart-tab-donut")
    expect(sankey_tab).to_have_attribute("aria-selected", "true")
    sankey_tab.focus()
    page.keyboard.press("ArrowRight")
    expect(donut_tab).to_be_focused()
    expect(donut_tab).to_have_attribute("aria-selected", "true")
    expect(viewer.tid("donut-chart")).to_be_visible()
    page.keyboard.press("ArrowLeft")
    expect(sankey_tab).to_be_focused()
    expect(viewer.tid("sankey-chart")).to_be_visible()
