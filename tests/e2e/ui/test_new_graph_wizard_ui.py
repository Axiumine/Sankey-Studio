"""F10: the new-graph wizard (``/graphs/new``): two steps before the editor starts.

Step 1 names the graph (a name is required), step 2 picks the data. Back keeps what was typed,
hostile text stays inert, "Do it later" exists for an empty Paste and Manual only, the finished
editor is "not saved yet" (leaving asks first), and saving goes to ``/graphs/<id>/edit``. The wizard
creates nothing by itself. One server for the module: every test uses its own names.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support import ui_b_hostile as hostile
from tests.e2e.support.builders import BUDGET, unique_name
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_sources import SourcePanel
from tests.e2e.support.uiwait import wait_editor

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.ui_a_wizard import NewGraphWizard
    from tests.e2e.support.watch import WatchedPage

NAME_REQUIRED = "Give the graph a name so you can find it later."
HEADERLESS = "Salary,Budget,3000,Income\nSalary,Savings,800,Income\n"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    return EditorPage(page, live_server)


@pytest.fixture
def wizard(editor: EditorPage) -> NewGraphWizard:
    return editor.goto_wizard()


def start_editing(editor: EditorPage, wizard: NewGraphWizard) -> None:
    """Finish the wizard with the Start editing button, then wait for the mounted editor."""
    wizard.create()
    wizard.expect_gone()
    wait_editor(editor.page)


# ------------------------------------------------------------------------------ steps


def test_the_wizard_has_two_steps_and_an_empty_name_blocks_the_first(
    editor: EditorPage, wizard: NewGraphWizard
) -> None:
    expect(editor.heading).to_have_text("New graph")
    expect(wizard.tid("wizard-step-details")).to_be_visible()
    expect(wizard.tid("wizard-step-source")).to_be_hidden()
    expect(wizard.tid("editor-name")).to_be_focused()
    expect(editor.page.locator("#page-root")).to_have_attribute("data-wizard", "details")
    expect(wizard.tid("wizard-cancel")).to_have_attribute("href", "/")

    wizard.next()
    wizard.expect_step("details")
    expect(wizard.root.get_by_text(NAME_REQUIRED)).to_be_visible()
    expect(wizard.tid("editor-name")).to_be_focused()
    wizard.tid("editor-name").fill("   ")
    wizard.tid("editor-name").press("Enter")
    wizard.expect_step("details")

    wizard.tid("editor-name").fill(unique_name("Two steps"))
    wizard.tid("editor-name").press("Enter")
    wizard.expect_step("source")
    expect(wizard.tid("wizard-step-source")).to_be_visible()
    expect(editor.page.locator("#page-root")).to_have_attribute("data-wizard", "source")
    expect(wizard.tid("source-tab-paste")).to_have_attribute("aria-selected", "true")
    expect(wizard.tid("wizard-next")).to_be_hidden()
    expect(wizard.tid("wizard-create")).to_be_disabled()
    expect(wizard.root).to_contain_text("Nothing is saved until you press Save.")


def test_back_keeps_everything_that_was_typed(wizard: NewGraphWizard) -> None:
    name = unique_name("Back and forth")
    wizard.fill_details(name, "kept on step one", ("qa-wizard",))
    wizard.next()
    wizard.tid("source-content").fill(BUDGET.csv)

    wizard.back()

    wizard.expect_step("details")
    expect(wizard.tid("editor-name")).to_have_value(name)
    expect(wizard.tid("editor-description")).to_have_value("kept on step one")
    expect(wizard.root.get_by_text("qa-wizard", exact=True)).to_be_visible()
    wizard.next()
    expect(wizard.tid("source-content")).to_have_value(BUDGET.csv)
    expect(wizard.tid("wizard-create")).to_be_enabled()


def test_hostile_text_in_every_field_stays_text(
    page: WatchedPage, editor: EditorPage, wizard: NewGraphWizard
) -> None:
    inert = hostile.Inert.watch(page)
    wizard.fill_details(hostile.NAME, hostile.DESCRIPTION, (hostile.TAG,))
    wizard.next()
    wizard.tid("source-content").fill(hostile.hostile_csv())
    inert.check()

    start_editing(editor, wizard)

    expect(editor.heading).to_have_text(f"New graph: {hostile.NAME}")
    editor.expect_name(hostile.NAME)
    inert.check()


# ------------------------------------------------------------------------------ do it later


def test_do_it_later_starts_an_empty_paste_or_manual_graph(
    editor: EditorPage, wizard: NewGraphWizard
) -> None:
    wizard.fill_details(unique_name("Later"))
    wizard.next()
    expect(wizard.tid("wizard-later")).to_be_visible()
    wizard.later()
    wizard.expect_gone()
    wait_editor(editor.page)
    expect(editor.tid("source-tab-paste")).to_have_attribute("aria-selected", "true")
    expect(editor.content).to_have_value("")

    second = editor.goto_wizard()
    second.fill_details(unique_name("Later manual"))
    second.next()
    second.choose_kind("manual")
    second.later()
    second.expect_gone()
    wait_editor(editor.page)
    expect(editor.tid("source-tab-manual")).to_have_attribute("aria-selected", "true")
    expect(editor.tid("manual-table")).to_be_visible()


def test_do_it_later_disappears_once_there_is_data(wizard: NewGraphWizard) -> None:
    wizard.fill_details(unique_name("No longer empty"))
    wizard.next()
    expect(wizard.tid("wizard-later")).to_be_visible()

    wizard.tid("source-content").fill("a,b,1")

    expect(wizard.tid("wizard-later")).to_be_hidden()
    expect(wizard.tid("wizard-create")).to_be_enabled()
    expect(wizard.tid("wizard-create")).not_to_have_attribute("aria-describedby", re.compile("."))


@pytest.mark.parametrize("kind", ["text", "upload", "mongo"])
def test_a_file_an_upload_and_mongodb_need_a_choice_first(
    wizard: NewGraphWizard, kind: str
) -> None:
    wizard.fill_details(unique_name("Needs a choice"))
    wizard.next()

    wizard.tid(f"source-tab-{kind}").click()

    expect(wizard.tid("wizard-later")).to_be_hidden()
    expect(wizard.tid("wizard-create")).to_be_disabled()
    expect(wizard.tid("wizard-create")).to_have_attribute("aria-describedby", "wizard-source-hint")
    expect(wizard.root.locator("#wizard-source-hint")).not_to_be_empty()


# ------------------------------------------------------------------------------ finishing


def test_the_finished_editor_is_not_saved_yet_asks_before_leaving_and_saves(
    editor: EditorPage, wizard: NewGraphWizard, api: httpx.Client
) -> None:
    name = unique_name("Wizard graph")
    before = json_of(api.get("/api/v1/graphs"))["total"]
    wizard.fill_details(name, "from the wizard", ("qa-wizard",))
    wizard.next()
    wizard.tid("source-content").fill(BUDGET.csv)
    assert json_of(api.get("/api/v1/graphs"))["total"] == before  # nothing is created by the wizard

    start_editing(editor, wizard)

    expect(editor.heading).to_have_text(f"New graph: {name}")
    expect(editor.save_status).to_have_text("Not saved yet")
    expect(editor.content).to_have_value(BUDGET.csv)
    editor.wait_preview()
    editor.expect_details(name=name, description="from the wizard", tags=("qa-wizard",))
    editor.nav("library").click()
    dialog = editor.tid("confirm-dialog")
    expect(dialog).to_contain_text("Leave without saving?")
    dialog.get_by_role("button", name="Stay and keep editing").click()
    graph_id = editor.save()
    assert re.fullmatch(r"[0-9a-f]{32}", graph_id)
    expect(editor.heading).to_have_text(f"Edit {name}")
    stored = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    assert (stored["name"], stored["tags"]) == (name, ["qa-wizard"])


def test_a_typed_name_makes_a_link_in_the_app_ask_before_leaving(
    editor: EditorPage, wizard: NewGraphWizard
) -> None:
    wizard.tid("editor-name").fill("Typed but not started")

    editor.nav("library").click()

    dialog = editor.tid("confirm-dialog")
    expect(dialog).to_contain_text("Leave without saving?")
    dialog.get_by_role("button", name="Stay and keep editing").click()
    wizard.expect_showing()
    expect(wizard.tid("editor-name")).to_have_value("Typed but not started")
    wizard.tid("editor-name").fill("")
    editor.nav("library").click()
    editor.page.wait_for_url(re.compile(r"/$"))


# ------------------------------------------------------------------------------ headerless


def test_a_headerless_paste_with_the_header_box_unticked_keeps_its_category_column(
    editor: EditorPage, wizard: NewGraphWizard
) -> None:
    wizard.fill_details(unique_name("Headerless"))
    wizard.next()
    header = wizard.tid("source-has-header")
    expect(header).to_be_checked()
    wizard.tid("source-content").fill(HEADERLESS)
    header.uncheck()

    start_editing(editor, wizard)

    editor.wait_preview()
    expect(editor.tid("source-has-header")).not_to_be_checked()
    SourcePanel(editor.page).expect_options(
        "category", ["Auto (col 4)", "Column 1", "Column 2", "Column 3", "Column 4"]
    )
    editor.expect_stats(nodes=3, links=2, total_in=3800, total_out=3800, columns=2, categories=1)


def test_the_header_box_is_only_offered_for_text_sources(wizard: NewGraphWizard) -> None:
    wizard.fill_details(unique_name("Header box"))
    wizard.next()
    expect(wizard.tid("source-has-header")).to_be_visible()

    wizard.choose_kind("manual")

    expect(wizard.tid("source-has-header")).to_be_hidden()
