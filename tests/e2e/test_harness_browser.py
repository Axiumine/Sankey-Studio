"""Self-tests of the browser side of the harness: fixtures, UI waits, the watcher in a real page.

Everything here proves one promise of ``conftest.py``: a suite built on ``page`` sees the same
page a user sees, and cannot overlook a console error, a failed request or a CSP violation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import fetch_json, seed_graph
from tests.e2e.support.uiwait import (
    DONUT_CHART,
    chart_state,
    wait_charts,
    wait_editor,
    wait_page,
    wait_preview,
    wait_shell,
)

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

TALL = {"width": 1280, "height": 2600}
PHONE = {"width": 390, "height": 844}


# ------------------------------------------------------------------------------ fixtures


def test_the_defaults_are_a_desktop_light_en_us_utc_reduced_motion_page(
    page: WatchedPage, live_server: LiveServer
) -> None:
    page.goto(live_server.url_for("/"))
    assert page.viewport_size == {"width": 1280, "height": 900}
    assert page.evaluate("matchMedia('(prefers-color-scheme: light)').matches") is True
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches") is True
    assert page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone") == "UTC"
    assert page.evaluate("navigator.language") == "en-US"
    assert page.evaluate("(8240).toLocaleString()") == "8,240"


@pytest.mark.parametrize("viewport", [PHONE], ids=["phone"])
def test_the_viewport_is_a_parametrizable_fixture(
    page: WatchedPage, live_server: LiveServer
) -> None:
    page.goto(live_server.url_for("/"))
    assert page.evaluate("[innerWidth, innerHeight]") == [390, 844]


def test_a_relative_goto_uses_the_server_as_base_url(
    page: WatchedPage, live_server: LiveServer
) -> None:
    page.goto("/settings")
    assert page.url == live_server.url_for("/settings")
    wait_shell(page)
    wait_page(page, "settings")


def test_downloads_are_accepted(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    seed_graph(api, unique_name("download"))
    page.goto(live_server.url_for("/"))
    with page.expect_download() as download:
        page.get_by_test_id("library-export").click()
    assert download.value.suggested_filename == "sankey-studio-graphs.json"


# ------------------------------------------------------------------------------ UI waits


def test_the_editor_waits_follow_the_dom_signals(
    page: WatchedPage, live_server: LiveServer
) -> None:
    page.goto(live_server.url_for("/graphs/new"))
    wait_shell(page)
    wait_page(page, "new")
    wait_editor(page)
    page.get_by_test_id("source-content").fill(BUDGET.csv)
    wait_preview(page)
    chart = page.get_by_test_id("sankey-chart")
    expect(chart).to_have_attribute("aria-label", "Sankey diagram with 10 nodes and 9 links")
    assert chart_state(page) == "true"
    assert chart_state(page, DONUT_CHART) is None  # no categories: no donut yet


def test_a_changed_input_is_waited_for_until_the_new_chart_is_drawn(
    page: WatchedPage, live_server: LiveServer
) -> None:
    page.goto(live_server.url_for("/graphs/new"))
    wait_editor(page)
    source = page.get_by_test_id("source-content")
    source.fill(BUDGET.csv)
    wait_preview(page)
    source.fill("source,target,value\nA,B,1\nB,C,1\n")
    wait_preview(page)
    chart = page.get_by_test_id("sankey-chart")
    expect(chart).to_have_attribute("aria-label", "Sankey diagram with 3 nodes and 2 links")


def test_the_viewer_donut_tab_waits_on_its_own_chart(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    saved = seed_graph(api, unique_name("donut"), graph_draft(BUDGET_CATEGORISED.csv))
    page.goto(live_server.url_for(f"/graphs/{saved['id']}"))
    wait_shell(page)
    wait_page(page, "viewer")
    wait_preview(page)
    page.get_by_test_id("chart-tab-donut").click()
    wait_preview(page, DONUT_CHART)
    assert chart_state(page, DONUT_CHART) == "true"


@pytest.mark.parametrize("viewport", [TALL], ids=["tall"])
def test_wait_charts_counts_the_drawn_charts_of_the_compare_page(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    ids = [seed_graph(api, unique_name(f"cmp{n}"))["id"] for n in range(3)]
    page.goto(live_server.url_for(f"/compare?ids={','.join(ids)}"))
    wait_shell(page)
    expect(page.get_by_test_id("compare-card")).to_have_count(3)
    wait_charts(page, 3)


# ------------------------------------------------------------------------------ the watcher


def test_the_watcher_sees_every_kind_of_noise(page: WatchedPage, live_server: LiveServer) -> None:
    page.goto(live_server.url_for("/"))
    wait_shell(page)
    page.evaluate("console.error('seen: error')")
    page.evaluate("console.warn('seen: warning')")
    page.evaluate("console.log('not noise: log')")
    page.evaluate("setTimeout(() => { throw new Error('seen: thrown'); }, 0)")
    page.route("**/api/v1/health", lambda route: route.abort("connectionfailed"))
    page.evaluate("fetch('/api/v1/health').catch(() => 0)")
    fetch_json(page, "GET", f"/api/v1/graphs/{'0' * 32}")
    page.evaluate("0")
    watch = page.watch
    assert watch.matching(r"^console\.error: seen: error @")
    assert watch.matching(r"^console\.warning: seen: warning @")
    assert not watch.matching("not noise")
    assert watch.matching(r"^pageerror: Error: seen: thrown")
    assert watch.matching(r"^requestfailed: GET .*/api/v1/health net::ERR_CONNECTION_FAILED")
    assert len(watch.matching(r"^http 404: GET .*/api/v1/graphs/0{32}$")) == 1
    assert watch.matching(r"^console\.error: Failed to load resource: .* 404")
    assert len(watch.problems()) >= 6
    page.allow_errors(r"seen: ", r"/api/v1/health", r"^http 404", r"status of 404")
    assert page.watch.problems() == []


def test_allow_http_matches_what_chrome_and_playwright_really_report(
    page: WatchedPage, live_server: LiveServer
) -> None:
    page.goto(live_server.url_for("/"))
    wait_shell(page)
    page.allow_http(404, "/api/v1/graphs/")
    assert fetch_json(page, "GET", f"/api/v1/graphs/{'0' * 32}").status == 404
    assert fetch_json(page, "GET", "/api/v1/health").status == 200
    page.evaluate("0")
    assert len(page.watch.events) == 2  # Chrome's console line and Playwright's response
    assert page.watch.problems() == []


def test_a_csp_violation_is_reported_through_the_binding_and_cannot_be_allowed(
    page: WatchedPage, live_server: LiveServer
) -> None:
    page.goto(live_server.url_for("/"))
    wait_shell(page)
    page.evaluate(
        "document.body.append(Object.assign(document.createElement('img'),"
        " {src: 'http://evil.example/x.png'}))"
    )
    page.allow_errors(r".*")
    problems = page.watch.problems()
    assert any(line.startswith("csp: img-src http://evil.example/x.png") for line in problems)
    page.watch.csp.clear()  # seen and understood: the test may now pass its teardown check
    page.watch.events.clear()


def test_a_new_tab_is_watched_by_the_same_watcher(
    page: WatchedPage, live_server: LiveServer
) -> None:
    other = page.new_tab()
    assert other.watch is page.watch
    other.goto(live_server.url_for("/"))
    other.evaluate("console.error('from the second tab')")
    other.evaluate("0")
    assert page.watch.matching("from the second tab")
    page.allow_errors("from the second tab")
    assert len(page.context.pages) == 2


# ------------------------------------------------------------------------------ real Mongo


@pytest.mark.mongo
def test_the_real_mongo_uri_fixture_hands_out_the_variable(real_mongo_uri: str) -> None:
    assert real_mongo_uri.startswith(("mongodb://", "mongodb+srv://"))
