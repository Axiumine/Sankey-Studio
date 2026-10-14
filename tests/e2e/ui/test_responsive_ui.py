"""E2E.md B.10, responsive layout: a phone never scrolls sideways and charts follow the window.

One server for the module (nothing here writes); the graphs are seeded once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET_CATEGORISED, LAYERED, graph_draft
from tests.e2e.support.clients import make_client, seed_graph
from tests.e2e.support.ui_a_wizard import NewGraphWizard
from tests.e2e.support.ui_b_common import PHONE, overflow_pixels, poll_js
from tests.e2e.support.ui_b_compare import ComparePage
from tests.e2e.support.ui_b_library import LibraryPage
from tests.e2e.support.ui_b_settings import SettingsPage
from tests.e2e.support.ui_b_viewer import ViewerPage
from tests.e2e.support.uiwait import wait_idle, wait_shell

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

LIBRARY_GRAPHS = 6
#: The drawn width of every Sankey chart on the page (the first ``svg.main-svg`` of each).
CHART_WIDTHS = (
    "[...document.querySelectorAll('[data-testid=sankey-chart]')]"
    ".map((chart) => Number(chart.querySelector('svg.main-svg').getAttribute('width')))"
)


class Seeded(NamedTuple):
    cats: str
    layers: str


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def seeded(module_server: LiveServer) -> Seeded:
    long_name = "A graph with a rather long name that has to wrap on a narrow phone screen"
    with make_client(module_server) as api:
        cats = seed_graph(api, long_name, graph_draft(BUDGET_CATEGORISED.csv), tags=["a", "b"])
        layers = seed_graph(api, "Layered", graph_draft(LAYERED.csv))
        for number in range(LIBRARY_GRAPHS):
            seed_graph(api, f"Filler {number}")
    return Seeded(cats["id"], layers["id"])


def wait_charts_drawn(page: WatchedPage) -> None:
    """Nothing on the page is still drawing (a chart that has not started yet does not count)."""
    wait_idle(page)
    expect(page.locator("[data-ready=false], [data-ready=error]")).to_have_count(0)


# ------------------------------------------------------------------------------ no sideways scroll

PAGES: Final = {
    "library": "/",
    "library-filtered": "/?q=graph&sort=name-asc",
    "new": "/graphs/new",
    "editor": "/graphs/{cats}/edit",
    "viewer": "/graphs/{cats}",
    "compare": "/compare?ids={cats},{layers}",
    "compare-empty": "/compare",
    "settings": "/settings",
}
#: Visible controls whose box leaves the window (the visually hidden file inputs are 1 x 1 px).
CLIPPED_JS = """() => [...document.querySelectorAll('main button, main a, main input, main select')]
    .filter((e) => { const r = e.getBoundingClientRect();
        return r.width > 2 && r.height > 2 && getComputedStyle(e).visibility !== 'hidden'
            && (r.right > innerWidth + 1 || r.left < -1); })
    .map((e) => e.getAttribute('data-testid') || e.textContent.trim().slice(0, 30))"""


@pytest.mark.parametrize("viewport", [PHONE], ids=["phone"])
def test_a_phone_has_no_horizontal_scroll_or_clipped_control_on_any_page_not_found_included(
    page: WatchedPage, live_server: LiveServer, seeded: Seeded
) -> None:
    assert page.viewport_size == PHONE
    for which, path in PAGES.items():
        page.goto(live_server.url_for(path.format(cats=seeded.cats, layers=seeded.layers)))
        wait_shell(page)
        wait_charts_drawn(page)
        assert overflow_pixels(page) <= 0, f"{which} is wider than the window"
        assert page.evaluate(CLIPPED_JS) == [], f"clipped controls on {which}"
    page.allow_http(404, "")  # the not-found pages: the document itself is a 404
    for path in ("/nope", "/graphs/" + "0" * 32, "/compare?ids=bad"):
        response = page.goto(live_server.url_for(path))
        assert response is not None
        assert response.status == 404
        wait_shell(page)
        expect(page.get_by_test_id("state-empty")).to_be_visible()
        assert overflow_pixels(page) <= 0, path


@pytest.mark.parametrize("viewport", [PHONE], ids=["phone"])
@pytest.mark.parametrize("kind", ["paste", "text", "upload", "manual", "mongo"])
def test_the_wizard_fits_a_phone_on_both_steps_for_every_kind_of_source(
    page: WatchedPage, live_server: LiveServer, kind: str
) -> None:
    page.goto(live_server.url_for("/graphs/new"))
    wizard = NewGraphWizard(page)
    wizard.expect_showing()
    assert overflow_pixels(page) <= 0, "step 1 is wider than the window"
    assert page.evaluate(CLIPPED_JS) == []
    wizard.fill_details("A wizard name that is long enough to wrap on a narrow phone screen")
    wizard.next()

    wizard.tid(f"source-tab-{kind}").click()

    expect(wizard.tid("wizard-step-source")).to_be_visible()
    assert overflow_pixels(page) <= 0, f"step 2 ({kind}) is wider than the window"
    assert page.evaluate(CLIPPED_JS) == [], f"clipped controls on step 2 ({kind})"
    expect(wizard.tid("wizard-cancel")).to_be_in_viewport()


# ------------------------------------------------------------------------------ charts resize


def chart_widths(page: WatchedPage) -> list[float]:
    return [float(width) for width in page.evaluate(CHART_WIDTHS)]


def test_charts_resize_with_the_window_in_the_viewer_and_on_the_compare_page(
    page: WatchedPage, live_server: LiveServer, seeded: Seeded
) -> None:
    viewer = ViewerPage(page, live_server, seeded.cats)
    viewer.goto()
    (wide,) = chart_widths(page)
    page.set_viewport_size(PHONE)
    poll_js(page, f"{CHART_WIDTHS}[0] < {wide}", what="the chart to shrink")
    (narrow,) = chart_widths(page)
    assert narrow <= PHONE["width"], "the chart is wider than the phone window"
    assert overflow_pixels(page) <= 0
    page.set_viewport_size({"width": 1280, "height": 900})
    poll_js(page, f"{CHART_WIDTHS}[0] > {narrow}", what="the chart to grow back")
    expect(viewer.sankey).to_have_attribute("data-ready", "true")
    compare = ComparePage(page, live_server)
    compare.open_ids([seeded.cats, seeded.layers])
    compare.expect_drawn("Layered")
    before = chart_widths(page)
    assert len(before) == 2
    page.set_viewport_size(PHONE)
    poll_js(page, f"{CHART_WIDTHS}.every((width) => width <= 390)", what="both charts to fit")
    assert all(after < wide for after, wide in zip(chart_widths(page), before, strict=True))
    assert overflow_pixels(page) <= 0


@pytest.mark.usefixtures("seeded")
def test_the_library_columns_and_the_settings_section_list_follow_the_window_width(
    page: WatchedPage, live_server: LiveServer
) -> None:
    library, settings = LibraryPage(page, live_server), SettingsPage(page, live_server)
    columns = (
        "[...new Set([...document.querySelectorAll('[data-testid=graph-card]')]"
        ".map((c) => Math.round(c.getBoundingClientRect().left)))].length"
    )
    library.goto()
    for width, expected in ((1440, 3), (768, 2), (390, 1)):
        page.set_viewport_size({"width": width, "height": 900})
        poll_js(page, f"innerWidth === {width}", what=f"width {width}")
        assert poll_js(page, f"{columns} === {expected}", what=f"{expected} columns at {width}px")
        assert overflow_pixels(page) <= 0
    toc = page.locator("nav.settings-toc")
    for width, visible in ((1440, True), (1024, False), (768, False), (390, False)):
        page.set_viewport_size({"width": width, "height": 900})
        settings.goto()
        expect(toc).to_be_visible() if visible else expect(toc).to_be_hidden()
        assert overflow_pixels(page) <= 0, f"sideways scroll at {width}px"
