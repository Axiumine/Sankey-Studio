"""E2E.md B.11, a slow server: the loading state is shown and a superseded answer never wins.

Requests are held inside the page (``support.ui_b_hold``), so every test controls exactly when the
server's answer "arrives".
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from playwright.sync_api import expect

from tests.e2e.support.builders import MANY_LINKS, unique_name
from tests.e2e.support.clients import seed_graph
from tests.e2e.support.ui_b_editor import EditorPage
from tests.e2e.support.ui_b_hold import Hold
from tests.e2e.support.ui_b_viewer import ViewerPage
from tests.e2e.support.uiwait import wait_preview

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

PREVIEW: Final = "/api/v1/preview"
HEAD: Final = "source,target,value\n"
TWO: Final = HEAD + "A,B,1\n"
THREE: Final = TWO + "B,C,2\n"
FOUR: Final = THREE + "C,D,3\n"
BUDGET_SECONDS: Final = 3.0


def label(editor: EditorPage) -> str:
    return editor.tid("sankey-chart").get_attribute("aria-label") or ""


def new_editor(page: WatchedPage, live_server: LiveServer) -> tuple[EditorPage, Hold]:
    hold = Hold(page)  # before the first goto
    editor = EditorPage(page, live_server, None)
    editor.goto()
    editor.source.fill(TWO)
    wait_preview(page)
    expect(editor.tid("sankey-chart")).to_have_attribute(
        "aria-label", "Sankey diagram with 2 nodes and 1 links"
    )
    return editor, hold


# ------------------------------------------------------------------------------ the editor preview


def test_a_slow_preview_shows_loading_and_a_replaced_inputs_answer_is_cancelled_and_never_drawn(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, hold = new_editor(page, live_server)
    root, chart = editor.tid("app-root"), editor.tid("sankey-chart")
    hold.start(PREVIEW)
    editor.source.fill(THREE)
    expect(root).to_have_attribute("data-loading", "true")  # the loading state
    hold.wait_for(1)
    assert "2 nodes" in label(editor)  # the previous chart stays while the new one is on its way
    editor.source.fill(FOUR)  # the person keeps typing while the first answer is still on its way
    hold.wait_for(2)
    assert hold.aborted(0), "the request for the replaced input was not cancelled"
    assert not hold.aborted(1)
    hold.release(0)  # the stale answer arrives first: nothing is drawn, the page keeps loading
    expect(root).to_have_attribute("data-loading", "true")
    assert "2 nodes" in label(editor)
    hold.release(1)
    wait_preview(page)
    expect(chart).to_have_attribute("aria-label", "Sankey diagram with 4 nodes and 3 links")
    expect(root).to_have_attribute("data-loading", "false")
    expect(editor.tid("stats")).to_contain_text("4")
    expect(editor.tid("entries-total")).to_have_text("3 entries")


# ------------------------------------------------------------------------------ the viewer


def test_a_slow_viewer_shows_a_skeleton_until_the_chart_is_ready(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    graph = seed_graph(api, unique_name("Slow"))
    hold = Hold(page, "/render")  # held from the first load of the page
    viewer = ViewerPage(page, live_server, graph["id"])
    page.goto(viewer.url_for())
    hold.wait_for(1)
    loading = viewer.tid("state-loading")
    expect(loading).to_be_visible()
    expect(loading).to_have_attribute("aria-busy", "true")
    expect(viewer.sankey).to_have_count(0)  # no chart before the answer arrives
    hold.release(0)
    viewer.expect_ready()
    expect(loading).to_have_count(0)


# ------------------------------------------------------------------------------ big graphs


def test_a_three_hundred_link_graph_stays_interactive_in_the_editor(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = EditorPage(page, live_server, None)
    editor.goto()
    editor.source.fill(TWO)  # the first draw loads plotly: not what is measured here
    wait_preview(page)
    started = time.monotonic()
    editor.source.fill(MANY_LINKS.csv)
    wait_preview(page)
    seconds = time.monotonic() - started
    expect(editor.tid("stats")).to_contain_text(f"{MANY_LINKS.links}")
    expect(editor.tid("sankey-chart")).to_have_attribute(
        "aria-label", f"Sankey diagram with {MANY_LINKS.nodes} nodes and {MANY_LINKS.links} links"
    )
    assert seconds < BUDGET_SECONDS, f"300 links took {seconds:.1f}s to draw"
    expect(editor.tid("warnings").locator("[data-testid=warning-item]")).to_have_count(0)
    link = editor.page.locator("[data-testid=sankey-chart] .sankey-link").nth(40)
    link.hover(force=True)
    expect(editor.page.locator(".hoverlayer .hovertext")).to_be_visible()  # hovering still works
    started = time.monotonic()
    editor.source.fill(MANY_LINKS.csv + "S999,T999,5\n")  # one more link: a second full preview
    wait_preview(page)
    assert time.monotonic() - started < BUDGET_SECONDS
    expect(editor.tid("sankey-chart")).to_have_attribute(
        "aria-label",
        f"Sankey diagram with {MANY_LINKS.nodes + 2} nodes and {MANY_LINKS.links + 1} links",
    )
