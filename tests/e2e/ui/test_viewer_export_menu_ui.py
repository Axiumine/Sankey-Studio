"""The export menu of the viewer: a download icon at the right of the tab row opens the panel.

The export panel is not a card beside the chart any more. A icon icon (``export-menu-button``,
"Export settings") sits after the display menu icon and opens ``export-menu-panel``, a non-modal
popover that holds every ``export-*`` control. This file covers the closed state (the controls
are in the DOM but hidden), opening and closing with the icon, Escape (focus back on the icon), a
press outside, focus leaving, the display menu (only one popover is open), the Sankey and Donut
image buttons, a download that leaves the panel open and the panel inside a 390 px window. The
downloads themselves are in ``test_export_viewer_ui.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from playwright.sync_api import expect

from tests.e2e.support.ui_a_display import DisplayMenu
from tests.e2e.support.ui_a_downloads import download
from tests.e2e.support.ui_a_seed import SavedGraph, save_graph
from tests.e2e.support.ui_a_viewer import ViewerPage
from tests.e2e.support.ui_b_common import poll_js
from tests.e2e.support.uiwait import DONUT_CHART, wait_chart

if TYPE_CHECKING:
    from playwright.sync_api import FloatRect, Locator, ViewportSize

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

NARROW: Final[ViewportSize] = {"width": 390, "height": 800}
SANKEY_IMAGES: Final = ("export-sankey-svg", "export-sankey-png")
DONUT_IMAGES: Final = ("export-donut-svg", "export-donut-png")
DATA_BUTTONS: Final = ("export-html", "export-json", "export-csv")
OPTIONS: Final = (
    "export-width",
    "export-height",
    "export-scale",
    "export-transparent",
    "export-theme",
)


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def saved(module_server: LiveServer) -> SavedGraph:
    return save_graph(module_server, "Export menu")


@pytest.fixture
def viewer(page: WatchedPage, live_server: LiveServer, saved: SavedGraph) -> ViewerPage:
    viewer = ViewerPage(page, live_server)
    viewer.open(saved.id)
    return viewer


def box(locator: Locator) -> FloatRect:
    """The bounding box of a visible ``locator`` (the test fails when it has none)."""
    found = locator.bounding_box()
    assert found is not None
    return found


def expect_shown(viewer: ViewerPage, shown: tuple[str, ...], hidden: tuple[str, ...]) -> None:
    """The ``shown`` controls are visible and the ``hidden`` ones are not."""
    for testid in shown:
        expect(viewer.tid(testid)).to_be_visible()
    for testid in hidden:
        expect(viewer.tid(testid)).to_be_hidden()


def expect_closed(viewer: ViewerPage) -> None:
    expect(viewer.export_panel).to_be_hidden()
    expect(viewer.export_button).to_have_attribute("aria-expanded", "false")


def expect_open(viewer: ViewerPage) -> None:
    expect(viewer.export_panel).to_be_visible()
    expect(viewer.export_button).to_have_attribute("aria-expanded", "true")


def show_donut_tab_without_a_press(viewer: ViewerPage) -> None:
    """Select the Donut tab with a bare click event: no pointer press, no focus change."""
    viewer.tid("chart-tab-donut").dispatch_event("click")
    wait_chart(viewer.page, DONUT_CHART)


# ------------------------------------------------------------------------------ the icon


def test_the_icon_sits_after_the_display_icon_and_every_export_control_waits_in_a_closed_panel(
    viewer: ViewerPage,
) -> None:
    icon = viewer.export_button
    expect(icon).to_be_visible()
    expect(icon).to_have_attribute("aria-label", "Export settings")
    expect(icon).to_have_attribute("aria-haspopup", "dialog")
    expect(icon).to_have_attribute("aria-expanded", "false")
    expect(icon).to_have_attribute("aria-controls", viewer.export_panel.get_attribute("id") or "")
    expect(viewer.export_panel).to_be_hidden()
    expect_shown(viewer, (), (*OPTIONS, *SANKEY_IMAGES, *DATA_BUTTONS))
    display, donut_tab = box(viewer.tid("display-menu-button")), box(viewer.tid("chart-tab-donut"))
    assert box(icon)["x"] >= display["x"] + display["width"]  # after the sliders icon ...
    assert abs(box(icon)["y"] - donut_tab["y"]) < donut_tab["height"]  # ... on the row of the tabs


def test_the_icon_opens_and_closes_the_panel_and_the_page_has_no_export_column(
    viewer: ViewerPage,
) -> None:
    viewer.export_button.click()

    expect_open(viewer)
    expect(viewer.export_panel).to_have_attribute("role", "dialog")
    expect(viewer.export_panel.get_by_role("heading", name="Export")).to_be_visible()
    expect_shown(viewer, (*OPTIONS, *SANKEY_IMAGES, *DATA_BUTTONS), DONUT_IMAGES)
    expect(viewer.page.locator(".viewer-aside, .viewer-layout")).to_have_count(0)
    icon = box(viewer.export_button)
    assert box(viewer.export_panel)["y"] >= icon["y"] + icon["height"]  # under the icon
    main, card = box(viewer.page.locator("#main")), box(viewer.page.locator(".chart-card"))
    assert card["width"] >= main["width"] * 0.9  # the chart card uses the whole page width
    viewer.export_button.click()
    expect_closed(viewer)
    expect_shown(viewer, (), (*OPTIONS, *SANKEY_IMAGES, *DATA_BUTTONS))


def test_open_export_menu_is_idempotent_and_the_panel_keeps_its_state_between_openings(
    viewer: ViewerPage,
) -> None:
    viewer.open_export_menu()
    viewer.open_export_menu()  # a second call must not toggle it shut
    expect_open(viewer)
    viewer.tid("export-width").fill("900")

    viewer.export_button.click()
    expect_closed(viewer)
    viewer.open_export_menu()

    expect(viewer.tid("export-width")).to_have_value("900")


# ------------------------------------------------------------------------------ closing


def test_escape_closes_the_panel_and_puts_the_focus_back_on_the_icon(viewer: ViewerPage) -> None:
    viewer.export_button.click()
    expect_open(viewer)
    viewer.tid("export-scale").focus()

    viewer.page.keyboard.press("Escape")

    expect_closed(viewer)
    expect(viewer.export_button).to_be_focused()


def test_a_press_outside_closes_the_panel_and_a_press_inside_it_does_not(
    viewer: ViewerPage,
) -> None:
    viewer.open_export_menu()
    viewer.export_panel.get_by_role("heading", name="Export").click()  # blank space inside
    expect_open(viewer)

    viewer.heading.click()  # a pointer press outside the icon and the panel

    expect_closed(viewer)
    viewer.open_export_menu()
    viewer.tid("sankey-chart").click(position={"x": 5, "y": 5})  # on the chart
    expect_closed(viewer)


def test_the_panel_closes_when_the_focus_moves_to_something_outside_it(viewer: ViewerPage) -> None:
    viewer.open_export_menu()
    viewer.tid("export-height").focus()
    expect_open(viewer)  # the focus walks inside the panel

    viewer.tid("chart-tab-sankey").focus()

    expect_closed(viewer)


def test_opening_the_display_menu_closes_the_export_panel_and_the_icon_closes_the_display_menu(
    viewer: ViewerPage,
) -> None:
    menu = DisplayMenu(viewer)
    viewer.open_export_menu()

    menu.open()

    expect_closed(viewer)
    viewer.export_button.click()
    expect_open(viewer)
    expect(menu.panel).to_be_hidden()
    expect(menu.button).to_have_attribute("aria-expanded", "false")
    viewer.page.keyboard.press("Escape")  # the keyboard path: the focus is back on the icon
    expect_closed(viewer)
    viewer.page.keyboard.press("Enter")
    expect_open(viewer)
    menu.button.focus()
    viewer.page.keyboard.press("Enter")
    expect(menu.panel).to_be_visible()
    expect_closed(viewer)


# ------------------------------------------------------------------------------ the tabs


def test_the_donut_tab_swaps_the_image_buttons_and_a_press_on_a_tab_closes_the_panel(
    viewer: ViewerPage,
) -> None:
    viewer.open_export_menu()
    expect_shown(viewer, SANKEY_IMAGES, DONUT_IMAGES)

    viewer.open_donut()  # a press on the tab is outside the popover

    expect_closed(viewer)
    viewer.open_export_menu()
    expect_shown(viewer, (*DONUT_IMAGES, *DATA_BUTTONS), SANKEY_IMAGES)
    expect(viewer.export_panel).to_contain_text("Donut image")
    viewer.tid("chart-tab-sankey").click()
    wait_chart(viewer.page)
    expect_closed(viewer)
    viewer.open_export_menu()
    expect_shown(viewer, (*SANKEY_IMAGES, *DATA_BUTTONS), DONUT_IMAGES)
    expect(viewer.export_panel).to_contain_text("Sankey image")


def test_a_tab_switch_without_a_press_leaves_the_open_panel_open_with_the_other_image_buttons(
    viewer: ViewerPage,
) -> None:
    viewer.open_export_menu()

    show_donut_tab_without_a_press(viewer)

    expect(viewer.tid("chart-tab-donut")).to_have_attribute("aria-selected", "true")
    expect_open(viewer)
    expect_shown(viewer, (*DONUT_IMAGES, *DATA_BUTTONS), SANKEY_IMAGES)
    viewer.tid("chart-tab-sankey").dispatch_event("click")
    wait_chart(viewer.page)
    expect_open(viewer)
    expect_shown(viewer, (*SANKEY_IMAGES, *DATA_BUTTONS), DONUT_IMAGES)


# ------------------------------------------------------------------------------ downloads


def test_a_download_leaves_the_panel_open_so_the_note_and_the_size_line_stay_in_view(
    viewer: ViewerPage, saved: SavedGraph
) -> None:
    viewer.open_export_menu()

    csv_file = download(viewer.page, viewer.tid("export-csv"))

    assert csv_file.name == f"{saved.name}.csv"
    viewer.expect_toast(f"Saved {saved.name}.csv", "success")
    expect_open(viewer)
    json_file = download(viewer.page, viewer.tid("export-json"))
    assert json_file.name == f"{saved.name}.json"
    expect_open(viewer)
    expect(viewer.export_panel).to_contain_text("Image size:")


# ------------------------------------------------------------------------------ a narrow window


def test_the_panel_fits_inside_a_390_px_window_with_every_button_in_it(
    page: WatchedPage, viewer: ViewerPage
) -> None:
    page.set_viewport_size(NARROW)

    viewer.open_export_menu()

    panel = box(viewer.export_panel)
    assert panel["x"] >= 0
    assert panel["x"] + panel["width"] <= NARROW["width"]
    assert panel["height"] <= NARROW["height"]
    for testid in (*OPTIONS, *SANKEY_IMAGES, *DATA_BUTTONS):
        control = box(viewer.tid(testid))
        assert control["x"] >= panel["x"], testid
        assert control["x"] + control["width"] <= panel["x"] + panel["width"], testid
    fits = "document.documentElement.scrollWidth <= window.innerWidth"
    poll_js(page, fits, what="the chart shrank to the 390 px window")
