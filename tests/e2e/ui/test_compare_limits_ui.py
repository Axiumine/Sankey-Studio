"""E2E.md B.7, the edges of the compare page: the 12-graph limit, gone graphs and no graphs at all.

One server for the module; unique names per test; a tall window so the lazy charts are in view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from sankey_studio.render import palette
from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import seed_graph
from tests.e2e.support.ui_b_common import TALL
from tests.e2e.support.ui_b_compare import ComparePage
from tests.e2e.support.ui_b_library import LibraryPage
from tests.e2e.support.ui_b_settings import wait_theme_saved
from tests.e2e.support.ui_b_viewer import expect_chart_theme, figure_surface

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import ViewportSize

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

LIMIT = 12
GONE = "This graph is gone"
PARTIAL = "One graph could not be drawn. The others are shown."


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def viewport() -> ViewportSize:
    return TALL


@pytest.fixture
def compare(page: WatchedPage, live_server: LiveServer) -> ComparePage:
    return ComparePage(page, live_server)


def seed_many(api: httpx.Client, prefix: str, count: int) -> list[dict[str, str]]:
    graphs = [seed_graph(api, f"{prefix} {n:02d}") for n in range(1, count + 1)]
    return [{"id": g["id"], "name": g["name"]} for g in graphs]


def api_requests(page: WatchedPage) -> list[str]:
    """Collect the URL of every request the page makes to ``/api/`` from now on."""
    urls: list[str] = []
    page.on("request", lambda request: urls.append(request.url) if "/api/" in request.url else None)
    return urls


# ------------------------------------------------------------------------------ the limit


def test_twelve_cards_show_the_limit_message_and_a_thirteenth_id_is_a_not_found_page(
    compare: ComparePage, api: httpx.Client
) -> None:
    graphs = seed_many(api, unique_name("Max"), LIMIT + 1)
    compare.open_ids([g["id"] for g in graphs[:LIMIT]])
    expect(compare.cards).to_have_count(LIMIT)
    expect(compare.tid("compare-grid")).to_have_attribute("data-count", str(LIMIT))
    limit = compare.tid("compare-limit-message")
    expect(limit).to_contain_text("You are comparing 12 graphs, the most this page can draw.")
    expect(compare.tid("compare-add")).to_be_hidden()
    expect(compare.tid("compare-add-select")).to_be_hidden()
    compare.remove(graphs[0]["name"])
    expect(compare.cards).to_have_count(LIMIT - 1)
    expect(limit).to_be_hidden()
    compare.add(graphs[LIMIT]["name"])  # a different graph takes its place
    expect(compare.cards).to_have_count(LIMIT)
    expect(limit).to_be_visible()
    ids = ",".join(g["id"] for g in graphs)  # thirteen ids in the address
    compare.page.allow_http(404, "/compare")  # the document itself is a 404 page
    response = compare.page.goto(compare.url_for(f"?ids={ids}"))
    assert response is not None
    assert response.status == 404
    expect(compare.heading).to_have_text("Page not found")
    expect(compare.cards).to_have_count(0)


def test_the_library_stops_at_twelve_ticked_graphs_and_says_so(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    prefix = unique_name("Tick")
    seed_many(api, prefix, LIMIT + 1)
    library = LibraryPage(page, live_server)
    library.goto(f"?q={prefix}&sort=name-asc")
    expect(library.tid("compare-select")).to_have_count(LIMIT)  # the 13th is on the next page
    for number in range(1, LIMIT + 1):
        library.tick(f"{prefix} {number:02d}").check()
    expect(library.tid("selection-bar")).to_contain_text("12 graphs selected")
    limit = library.tid("compare-limit-message")
    expect(limit).to_contain_text("You can compare up to 12 graphs at a time.")
    library.next_page()
    thirteenth = library.tick(f"{prefix} 13")
    expect(thirteenth).to_be_disabled()
    expect(thirteenth).to_have_attribute("title", "You can compare up to 12 graphs at a time")
    library.previous_page()
    library.tick(f"{prefix} 12").uncheck()
    expect(limit).to_be_hidden()
    library.next_page()
    expect(library.tick(f"{prefix} 13")).to_be_enabled()


# ------------------------------------------------------------------------------ gone graphs


def test_gone_graphs_are_placeholders_never_requested_and_no_graphs_is_a_calm_empty_page(
    compare: ComparePage, api: httpx.Client
) -> None:
    prefix = unique_name("Gone")
    keep_a, doomed, keep_b = (seed_graph(api, f"{prefix} {n}") for n in "ABC")
    assert api.delete(f"/api/v1/graphs/{doomed['id']}").status_code == 204
    requests = api_requests(compare.page)
    response = compare.open_ids([keep_a["id"], doomed["id"], keep_b["id"]])
    assert response is not None
    assert response.status == 200
    expect(compare.cards).to_have_count(2)
    expect(compare.missing).to_have_count(1)
    expect(compare.missing).to_contain_text(GONE)
    compare.expect_toast(PARTIAL, "warning")
    compare.expect_drawn(f"{prefix} A")
    compare.expect_drawn(f"{prefix} C")
    assert not [url for url in requests if doomed["id"] in url]  # the answer was in the page data
    compare.missing.get_by_role("button").click()
    expect(compare.missing).to_have_count(0)
    assert compare.url_ids() == [keep_a["id"], keep_b["id"]]
    earlier = len(requests)
    response = compare.goto("?ids=" + "0" * 32)  # nothing but unknown ids
    assert response is not None
    assert response.status == 200
    expect(compare.missing).to_have_count(1)
    expect(compare.cards).to_have_count(0)
    expect(compare.page.locator("[data-testid=sankey-chart]")).to_have_count(0)
    assert not [url for url in requests[earlier:] if "/api/" in url and "0" * 32 in url]
    assert not [url for url in requests[earlier:] if "/compare/render" in url]
    earlier = len(requests)
    for suffix in ("", "?ids="):  # and no graphs at all: a calm empty page
        response = compare.goto(suffix)
        assert response is not None
        assert response.status == 200
        empty = compare.tid("state-empty")
        expect(empty).to_contain_text("Nothing to compare yet")
        expect(empty.get_by_role("link", name="Back to the library")).to_have_attribute("href", "/")
        expect(compare.count_line).to_have_text("No graphs in the comparison")
        expect(compare.cards).to_have_count(0)
    assert not [url for url in requests[earlier:] if "/compare/render" in url]
    assert not [url for url in requests[earlier:] if "/api/v1/graphs/" in url]


def test_a_graph_deleted_after_the_page_opened_turns_into_a_placeholder_on_the_next_draw(
    compare: ComparePage, api: httpx.Client
) -> None:
    prefix = unique_name("Late")
    keep, doomed = (seed_graph(api, f"{prefix} {n}") for n in "AB")
    compare.open_ids([keep["id"], doomed["id"]])
    compare.expect_drawn(f"{prefix} A")
    compare.expect_drawn(f"{prefix} B")
    assert api.delete(f"/api/v1/graphs/{doomed['id']}").status_code == 204
    compare.page.allow_http(404, "/api/v1/")  # the cards ask the server again after the switch
    compare.theme_button("dark").click()
    expect(compare.missing).to_have_count(1)
    expect(compare.missing).to_contain_text(GONE)
    compare.expect_toast(PARTIAL, "warning")
    compare.expect_drawn(f"{prefix} A")
    chart = compare.card(f"{prefix} A").get_by_test_id("sankey-chart")
    expect_chart_theme(chart, "dark")  # the surviving card was redrawn in the new theme
    assert figure_surface(chart)[0] == palette.TOKENS["dark"].surface
    wait_theme_saved(compare.page, "dark")  # the click also saved the theme, in the background
    assert compare.page.watch.matching(r"^http 404: ")
