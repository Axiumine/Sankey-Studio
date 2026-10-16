# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""F1: the Clear icon inside the Paste box, with an Undo toast.

The icon sits top right inside the box (clear of the vertical scrollbar and the text), exists only
while the box holds text, empties it, brings the empty chart state back and keeps the focus in
the box. Clear wipes the only copy of the data, so a "Cleared" toast offers Undo; the toast goes
away as soon as other text arrives or the tab changes, so Undo can never overwrite newer data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, LAYERED, many_links
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_sources import SourcePanel

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

#: Where the icon is, in page pixels, next to the textarea box and its scrollbar and padding.
GEOMETRY: Final = """textarea => {
  const style = getComputedStyle(textarea);
  const box = textarea.getBoundingClientRect();
  const clear = textarea.parentElement.querySelector('[data-testid=source-clear]');
  const icon = clear.getBoundingClientRect();
  const border = parseFloat(style.borderRightWidth);
  const frame = parseFloat(style.borderLeftWidth) + border;
  const bar = textarea.offsetWidth - textarea.clientWidth - frame;
  return {
    box: {left: box.left, top: box.top, right: box.right, bottom: box.bottom},
    icon: {left: icon.left, top: icon.top, right: icon.right, bottom: icon.bottom},
    textEdge: box.right - border - bar - parseFloat(style.paddingRight),
    scrollbarEdge: box.right - border - bar,
  };
}"""


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


def inside(inner: dict[str, float], outer: dict[str, float]) -> bool:
    """``inner`` lies within ``outer`` (both ``left/top/right/bottom`` rectangles)."""
    fits_across = outer["left"] <= inner["left"] and inner["right"] <= outer["right"]
    return fits_across and outer["top"] <= inner["top"] and inner["bottom"] <= outer["bottom"]


def expect_empty_box(editor: EditorPage, source: SourcePanel) -> None:
    """The box is empty and focused, the icon is gone and the chart shows its empty state."""
    expect(editor.content).to_have_value("")
    expect(editor.content).to_be_focused()
    expect(source.clear_button).to_be_hidden()
    expect(editor.page.get_by_role("button", name="Insert an example")).to_be_visible()
    expect(editor.tid("state-empty").first).to_contain_text("Nothing to draw yet")
    expect(editor.tid("sankey-chart").locator("svg")).to_have_count(0)  # the plot is gone
    expect(editor.tid("stats")).to_be_hidden()


def expect_budget_drawn(editor: EditorPage) -> None:
    editor.expect_stats(
        nodes=BUDGET.nodes,
        links=BUDGET.links,
        total_in=BUDGET.total,
        total_out=BUDGET.total,
        columns=BUDGET.layers,
    )


def test_the_icon_sits_top_right_inside_the_box_and_only_while_it_holds_text(
    editor: EditorPage, source: SourcePanel
) -> None:
    expect(source.clear_button).to_be_hidden()
    editor.paste(many_links(40).csv)  # 40 rows: the box scrolls, so a scrollbar may be there

    expect(source.clear_button).to_be_visible()
    expect(source.clear_button).to_have_accessible_name("Clear the pasted data")
    labelled = editor.page.get_by_label("Your data", exact=True)  # the label still names the box
    expect(labelled).to_have_attribute("data-testid", "source-content")
    where = editor.content.evaluate(GEOMETRY)
    box, icon = where["box"], where["icon"]
    assert inside(icon, box)
    assert icon["top"] - box["top"] < 12  # top, not the resize grip at the bottom right
    assert icon["right"] <= where["scrollbarEdge"]  # clear of a classic vertical scrollbar
    assert where["textEdge"] <= icon["left"]  # the text never runs under the icon


def test_clear_empties_the_box_and_undo_brings_the_text_back(
    editor: EditorPage, source: SourcePanel
) -> None:
    editor.paste(BUDGET.csv)
    before = editor.content.input_value()

    source.clear()

    expect_empty_box(editor, source)
    expect(source.cleared_toast).to_be_visible()
    editor.wait_settled()
    with editor.page.expect_response(lambda r: "/api/v1/preview" in r.url):
        source.undo_clear()
    expect(editor.content).to_have_value(before)
    expect(editor.content).to_be_focused()
    expect(source.cleared_toast).to_have_count(0)
    editor.wait_preview()
    expect_budget_drawn(editor)


def test_the_icon_is_one_tab_stop_after_the_box_and_works_from_the_keyboard(
    editor: EditorPage, source: SourcePanel
) -> None:
    editor.paste(BUDGET.csv)
    editor.content.focus()

    editor.page.keyboard.press("Tab")
    expect(source.clear_button).to_be_focused()
    editor.page.keyboard.press("Enter")

    expect_empty_box(editor, source)
    expect(source.cleared_toast).to_be_visible()


def test_new_text_retires_the_undo_and_a_second_clear_offers_its_own(
    editor: EditorPage, source: SourcePanel
) -> None:
    editor.paste(BUDGET.csv)
    source.clear()
    expect(source.cleared_toast).to_be_visible()

    editor.fill_source(LAYERED.csv)

    expect(source.cleared_toast).to_have_count(0)
    editor.wait_preview()
    source.clear()
    expect(source.cleared_toast).to_have_count(1)
    source.undo_clear()
    expect(editor.content).to_have_value(LAYERED.csv)


def test_leaving_the_paste_tab_retires_the_undo(editor: EditorPage, source: SourcePanel) -> None:
    editor.paste(BUDGET.csv)
    source.clear()
    expect(source.cleared_toast).to_be_visible()

    source.open_tab("manual")

    expect(source.cleared_toast).to_have_count(0)
    source.open_tab("paste")
    expect(editor.content).to_have_value("")
