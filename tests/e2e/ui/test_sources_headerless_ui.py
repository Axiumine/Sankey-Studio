"""F3: a headerless text has its category in the fourth column (server rule, mirrored in JS)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_sources import SourcePanel

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

FOUR_COLUMNS = "Salary,Budget,3000,Income\nSalary,Savings,800,Income\n"
THREE_COLUMNS = "Salary,Budget,3000\nSalary,Savings,800\n"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    editor = EditorPage(page, live_server)
    editor.goto()
    return editor


@pytest.fixture
def source(page: WatchedPage) -> SourcePanel:
    return SourcePanel(page)


def test_a_headerless_fourth_column_is_the_category_and_three_columns_are_not(
    editor: EditorPage, source: SourcePanel
) -> None:
    # Read with a header row, the first record names no usable columns: a 422 until it is unticked.
    editor.page.allow_http(422, "/api/v1/preview")
    editor.page.allow_http(422, "/api/v1/entries")
    editor.fill_source(FOUR_COLUMNS)
    editor.wait_settled()
    source.tid("source-has-header").uncheck()
    editor.wait_preview()

    options = ["Auto (col 4)", "Column 1", "Column 2", "Column 3", "Column 4"]
    source.expect_options("category", options)
    expect(editor.tid("chart-tab-donut")).to_be_visible()
    editor.expect_stats(nodes=3, links=2, total_in=3800, total_out=3800, columns=2, categories=1)

    source.tid("source-no-category-switch").check()
    editor.wait_preview()
    expect(editor.tid("chart-tab-donut")).to_have_count(0)

    source.tid("source-no-category-switch").uncheck()
    editor.fill_source(THREE_COLUMNS)
    editor.wait_preview()
    source.expect_options("category", ["Auto (none found)", "Column 1", "Column 2", "Column 3"])
    expect(editor.tid("chart-tab-donut")).to_have_count(0)


def test_the_category_hint_names_the_fourth_column_only_without_a_header(
    editor: EditorPage, source: SourcePanel
) -> None:
    editor.page.allow_http(422, "/api/v1/preview")
    editor.page.allow_http(422, "/api/v1/entries")
    hint = source.column("category").locator("xpath=following-sibling::p[contains(@class, 'hint')]")
    editor.fill_source(FOUR_COLUMNS)
    editor.wait_settled()
    expect(hint).to_have_text(
        "Optional. Automatic uses a column called category when there is one."
    )

    source.tid("source-has-header").uncheck()
    expect(hint).to_have_text("Optional. Automatic uses the fourth column when there is one.")

    source.tid("source-has-header").check()
    expect(hint).to_have_text(
        "Optional. Automatic uses a column called category when there is one."
    )
