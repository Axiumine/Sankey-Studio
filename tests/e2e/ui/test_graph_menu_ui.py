"""F10 part 1: the gear next to the title and the "Graph details" dialog.

The gear is a menu button (``Edit details`` and ``Change data source``); the details dialog holds
the name, description and tags the old inline panel held. Edits are live in the draft (the heading
follows, the graph is dirty), ``Done`` validates the name, Esc / the X / the backdrop close without
validating. The menu and the dialog are keyboard-complete and fit a phone. One server for the
module (nothing here saves).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET
from tests.e2e.support.ui_a_chrome import DetailsDialog, GraphMenu
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_keyboard import focused
from tests.e2e.support.ui_b_common import PHONE, overflow_pixels
from tests.e2e.support.ui_b_hostile import DESCRIPTION, NAME, TAG, Inert

if TYPE_CHECKING:
    from playwright.sync_api import Route

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

REQUIRED = "Give the graph a name so you can find it later."


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def refuse_the_name(route: Route) -> None:
    """Answer the save with the 422 the server gives for a bad ``name``."""
    error = {
        "code": "validation_error",
        "message": "The request is not valid",
        "details": ["body.name: That name is not allowed"],
    }
    route.fulfill(status=422, json={"error": error})


def open_editor(page: WatchedPage, server: LiveServer) -> tuple[EditorPage, GraphMenu]:
    editor = EditorPage(page, server)
    editor.goto()
    editor.paste(BUDGET.csv)
    return editor, GraphMenu(page)


def open_unnamed_editor(page: WatchedPage, server: LiveServer) -> tuple[EditorPage, GraphMenu]:
    """The wizard always names the graph; empty the name to reach the unnamed state."""
    editor, menu = open_editor(page, server)
    editor.open_details().fill(name="")
    DetailsDialog(page).dismiss()
    return editor, menu


# ------------------------------------------------------------------------------ the menu


def test_the_gear_sits_beside_the_title_and_is_a_menu_button(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, menu = open_editor(page, live_server)

    expect(menu.button).to_have_accessible_name("Graph settings")
    expect(menu.button).to_have_attribute("aria-haspopup", "menu")
    expect(menu.button).to_have_attribute("aria-expanded", "false")
    expect(menu.panel).to_be_hidden()
    head, gear = editor.heading.bounding_box(), menu.button.bounding_box()
    assert head is not None
    assert gear is not None
    assert gear["x"] >= head["x"] + head["width"] - 1  # after the heading, on the same line
    assert abs((gear["y"] + gear["height"] / 2) - (head["y"] + head["height"] / 2)) < head["height"]
    menu.open()
    expect(menu.panel).to_have_attribute("role", "menu")
    expect(menu.panel.get_by_role("menuitem")).to_have_text(["Edit details", "Change data source"])


def test_the_arrow_keys_drive_the_menu_and_escape_returns_to_the_gear(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, menu = open_editor(page, live_server)
    menu.button.focus()

    page.keyboard.press("ArrowDown")
    expect(menu.panel).to_be_visible()
    assert focused(page) == "graph-settings-details"
    page.keyboard.press("ArrowDown")
    assert focused(page) == "graph-settings-source"
    page.keyboard.press("ArrowDown")  # wraps
    assert focused(page) == "graph-settings-details"
    page.keyboard.press("End")
    assert focused(page) == "graph-settings-source"
    page.keyboard.press("Home")
    assert focused(page) == "graph-settings-details"
    page.keyboard.press("Escape")

    expect(menu.panel).to_be_hidden()
    expect(menu.button).to_be_focused()
    menu.button.press("ArrowUp")
    assert focused(page) == "graph-settings-source"
    editor.content.click()  # a press outside closes it
    expect(menu.panel).to_be_hidden()


def test_tab_leaves_the_menu_and_closes_it(page: WatchedPage, live_server: LiveServer) -> None:
    _, menu = open_editor(page, live_server)
    menu.button.focus()
    page.keyboard.press("ArrowDown")

    page.keyboard.press("Tab")

    expect(menu.panel).to_be_hidden()
    expect(menu.button).not_to_be_focused()


# ------------------------------------------------------------------------------ the dialog


def test_the_details_dialog_edits_the_draft_live_and_hands_the_focus_back(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, menu = open_editor(page, live_server)
    dialog = DetailsDialog(page)

    menu.choose("details")
    expect(dialog.dialog).to_be_visible()
    expect(dialog.dialog).to_have_attribute("aria-modal", "true")
    expect(editor.name_field).to_be_focused()
    expect(dialog.dialog.get_by_role("heading", name="Graph details")).to_be_visible()
    dialog.fill(name="Household 2026", description="Monthly", tags=("home", "2026"))
    expect(editor.heading).to_have_text("New graph: Household 2026")
    expect(editor.save_status).to_have_text("Not saved yet")
    dialog.done()

    expect(menu.button).to_be_focused()
    editor.expect_details(name="Household 2026", description="Monthly", tags=("home", "2026"))
    expect(editor.heading).to_have_text("New graph: Household 2026")


def test_done_refuses_an_empty_name_but_escape_and_the_x_close_without_validating(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, menu = open_unnamed_editor(page, live_server)
    dialog = DetailsDialog(page)
    menu.choose("details")

    editor.tid("details-done").click()
    expect(dialog.dialog.get_by_text(REQUIRED)).to_be_visible()
    expect(dialog.dialog).to_be_visible()
    expect(editor.name_field).to_be_focused()
    editor.name_field.fill("x")
    expect(dialog.dialog.get_by_text(REQUIRED)).to_be_hidden()
    editor.name_field.fill("")
    dialog.dismiss()
    expect(editor.heading).to_have_text("New graph")

    menu.choose("details")
    editor.tid("dialog-close").click()
    expect(dialog.dialog).to_be_hidden()
    menu.choose("details")
    page.mouse.click(5, 5)  # the backdrop
    expect(dialog.dialog).to_be_hidden()


def test_a_second_request_for_the_dialog_reuses_the_open_one(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor, menu = open_unnamed_editor(page, live_server)
    menu.choose("details")

    page.keyboard.press("Control+s")  # Save with no name asks for the dialog again

    expect(editor.tid("details-dialog")).to_have_count(1)
    expect(editor.tid("details-dialog").get_by_text(REQUIRED)).to_be_visible()
    expect(editor.name_field).to_be_focused()


def test_hostile_details_stay_text_in_the_dialog_and_the_heading(
    page: WatchedPage, live_server: LiveServer
) -> None:
    inert = Inert.watch(page)
    editor, _ = open_editor(page, live_server)

    editor.set_details(name=NAME, description=DESCRIPTION, tags=(TAG,))

    expect(editor.heading).to_have_text(f"New graph: {NAME}")
    editor.expect_name(NAME)
    assert len(editor.description_value()) == len(DESCRIPTION)
    inert.check()


@pytest.mark.parametrize("viewport", [PHONE], ids=["phone"])
def test_the_gear_and_the_dialog_fit_a_phone(page: WatchedPage, live_server: LiveServer) -> None:
    editor, menu = open_editor(page, live_server)
    menu.open()
    expect(menu.panel).to_be_in_viewport(ratio=1)  # slid back inside: the gear is far from the edge
    menu.choose("details")

    dialog = editor.tid("details-dialog").bounding_box()
    assert dialog is not None
    assert dialog["x"] >= 0
    assert dialog["x"] + dialog["width"] <= PHONE["width"]
    assert overflow_pixels(page) <= 0


def test_a_name_the_server_refuses_marks_the_gear_and_the_field(
    page: WatchedPage, live_server: LiveServer
) -> None:
    page.allow_http(422, "/api/v1/graphs")
    editor, menu = open_editor(page, live_server)
    editor.set_name("Taken")
    page.route("**/api/v1/graphs", refuse_the_name, times=1)

    editor.save_button.click()

    expect(menu.button).to_have_attribute("data-badge", "error")
    expect(menu.button).to_have_accessible_name("Graph settings, 1 problem")
    menu.choose("details")
    expect(editor.tid("details-dialog").get_by_text("That name is not allowed")).to_be_visible()
    editor.name_field.fill("Fine")
    editor.tid("details-done").click()
    editor.save_button.click()
    expect(editor.save_status).to_contain_text("All changes saved")
    expect(menu.button).to_have_accessible_name("Graph settings")
