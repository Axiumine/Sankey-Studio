"""F8, the chart settings popover: a gear in the chart header opens Style and Export.

The popover is NOT modal: the page stays live behind it (a style edit redraws the chart while it
is open), Escape or a press outside closes it, focus that moves elsewhere closes it, and a style
value the server rejects marks the gear. One server for the module (nothing here saves).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET
from tests.e2e.support.ui_a_chrome import ChartSettings
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_keyboard import focused
from tests.e2e.support.ui_b_common import PHONE, download_text, overflow_pixels

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

SECTIONS_KEY = "sankey-studio.editor.sections"
TITLE = "Quarterly flows"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def open_editor(page: WatchedPage, server: LiveServer) -> tuple[EditorPage, ChartSettings]:
    editor = EditorPage(page, server)
    editor.goto()
    editor.paste(BUDGET.csv)
    return editor, ChartSettings(page)


def tab_selected(editor: EditorPage, tab: str, *, on: bool = True) -> None:
    expected = "true" if on else "false"
    expect(editor.tid(f"chart-settings-tab-{tab}")).to_have_attribute("aria-selected", expected)


# ------------------------------------------------------------------------------ opening and closing


def test_the_gear_toggles_a_non_modal_dialog_that_opens_on_the_style_tab(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    gear = settings.button

    expect(gear).to_have_attribute("aria-expanded", "false")
    expect(gear).to_have_attribute("aria-haspopup", "dialog")
    expect(settings.panel).to_be_hidden()
    expect(gear).to_have_accessible_name("Chart settings")
    gear.click()

    expect(gear).to_have_attribute("aria-expanded", "true")
    expect(settings.panel).to_be_visible()
    expect(settings.panel).to_have_attribute("role", "dialog")
    expect(settings.panel).not_to_have_attribute("aria-modal", "true")
    expect(gear).to_have_attribute("aria-controls", settings.panel.get_attribute("id") or "")
    tab_selected(editor, "style")
    expect(editor.tid("chart-settings-tab-style")).to_be_focused()
    expect(editor.tid("style-title")).to_be_visible()
    gear.click()
    expect(settings.panel).to_be_hidden()
    expect(gear).to_have_attribute("aria-expanded", "false")


def test_escape_closes_the_popover_and_puts_the_focus_back_on_the_gear(
    page: WatchedPage, live_server: LiveServer
) -> None:
    _, settings = open_editor(page, live_server)
    settings.open("export")

    settings.close()

    expect(settings.button).to_have_attribute("aria-expanded", "false")


def test_the_close_button_closes_it_and_the_focus_returns_to_the_gear(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    settings.open()

    editor.tid("chart-settings-close").click()

    expect(settings.panel).to_be_hidden()
    expect(settings.button).to_be_focused()


def test_a_press_outside_closes_it_and_leaves_the_focus_where_the_person_clicked(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    settings.open()

    editor.content.click()

    expect(settings.panel).to_be_hidden()
    expect(editor.content).to_be_focused()
    expect(settings.button).to_have_attribute("aria-expanded", "false")


def test_focus_moving_to_another_control_closes_it_without_taking_the_focus_back(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    settings.open()

    editor.content.focus()

    expect(settings.panel).to_be_hidden()
    expect(editor.content).to_be_focused()


def test_a_press_inside_the_panel_keeps_it_open(page: WatchedPage, live_server: LiveServer) -> None:
    editor, settings = open_editor(page, live_server)
    settings.open()

    editor.tid("chart-settings-panel").locator(".ed-settings-title").click()
    editor.tid("style-title").click()

    expect(settings.panel).to_be_visible()


def test_tab_from_the_gear_enters_the_open_panel_and_the_gear_is_in_the_tab_order(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    settings.button.focus()
    page.keyboard.press("Enter")
    expect(settings.panel).to_be_visible()
    settings.button.focus()

    page.keyboard.press("Tab")

    assert focused(page) == "chart-settings-close"
    expect(settings.panel).to_be_visible()
    expect(editor.tid("chart-settings-close")).to_be_focused()


# ------------------------------------------------------------------------------ tabs and content


def test_the_tabs_switch_between_style_and_export_with_the_arrow_keys(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    settings.open()

    editor.tid("chart-settings-tab-export").click()
    expect(editor.tid("export-csv")).to_be_visible()
    expect(editor.tid("style-title")).to_be_hidden()
    tab_selected(editor, "style", on=False)
    page.keyboard.press("ArrowLeft")

    tab_selected(editor, "style")
    expect(editor.tid("style-title")).to_be_visible()
    expect(editor.tid("export-csv")).to_be_hidden()


def test_a_style_edit_redraws_the_chart_while_the_popover_is_open(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    settings.open()

    editor.tid("style-title").fill(TITLE)

    expect(page.locator("[data-testid=sankey-chart] .gtitle")).to_have_text(TITLE)
    expect(settings.panel).to_be_visible()
    expect(editor.tid("style-title")).to_have_value(TITLE)


def test_an_export_works_from_the_export_tab_and_the_popover_stays_open(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    settings.open("export")

    name, text = download_text(page, editor.tid("export-csv").click)

    assert name.endswith(".csv")
    assert "Salary" in text
    expect(settings.panel).to_be_visible()


def test_the_style_section_always_starts_open_in_the_popover_and_never_stores_its_state(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    page.evaluate(f"localStorage.setItem('{SECTIONS_KEY}', JSON.stringify({{style: false}}))")
    editor.goto()
    page.evaluate(f"localStorage.removeItem('{SECTIONS_KEY}')")
    settings.open()

    expect(editor.tid("style-title")).to_be_visible()
    editor.tid("section-style").click()

    expect(editor.tid("style-title")).to_be_hidden()
    assert page.evaluate(f"localStorage.getItem('{SECTIONS_KEY}')") is None


def test_the_popover_is_flat_inside_and_hidden_when_printing(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    settings.open("export")
    section = "getComputedStyle(document.querySelector('[data-panel=export] .out-card'))"

    assert page.evaluate(f"{section}.boxShadow") == "none"
    page.emulate_media(media="print")

    expect(settings.panel).to_be_hidden()
    expect(editor.tid("chart-settings-button")).to_be_hidden()


# ------------------------------------------------------------------------------ errors and sizes


def test_a_style_value_the_server_rejects_marks_the_gear_and_opens_on_the_style_tab(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, settings = open_editor(page, live_server)
    page.allow_http(422, "/api/v1/preview")
    settings.open()
    page.get_by_label("Number format").fill("a/b")
    editor.tid("chart-settings-tab-export").click()
    settings.close()

    expect(settings.button).to_have_attribute("data-badge", "error")
    expect(settings.button).to_have_accessible_name("Chart settings, 1 problem")
    settings.button.click()
    tab_selected(editor, "style")
    page.get_by_label("Number format").fill("")

    expect(settings.button).not_to_have_attribute("data-badge", "error")
    expect(settings.button).to_have_accessible_name("Chart settings")


@pytest.mark.parametrize("viewport", [PHONE], ids=["phone"])
def test_on_a_phone_the_panel_stays_inside_the_window(
    page: WatchedPage, live_server: LiveServer
) -> None:
    _, settings = open_editor(page, live_server)

    settings.open()

    box = settings.panel.bounding_box()
    assert box is not None
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= PHONE["width"]
    assert overflow_pixels(page) <= 0
    expect(settings.button).to_be_visible()


@pytest.mark.parametrize("color_scheme", ["dark"])
def test_in_the_dark_theme_the_panel_has_a_solid_surface_and_a_border(
    page: WatchedPage, live_server: LiveServer
) -> None:
    _, settings = open_editor(page, live_server)

    settings.open()

    style = settings.panel.evaluate(
        "(el) => { const s = getComputedStyle(el); return [s.backgroundColor, s.borderTopWidth]; }"
    )
    assert style[0] != "rgba(0, 0, 0, 0)"
    assert style[1] == "1px"
