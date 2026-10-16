# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""F9, the editor layout: a full-width chart row, then Source and Transform, then the entries.

The chart is no longer in a sticky side pane: it is a row of its own on top of the page, Source
and Transform share the next row from 900 px and stack below it, and there is no "Go to the chart"
link any more (the chart is the first thing on the page). Style and Export live in the chart
settings popover (``test_chart_settings_popover_ui.py``), so neither is a page section.
One server for the module (nothing here saves).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_b_common import DESKTOP, PHONE, overflow_pixels, poll_js

if TYPE_CHECKING:
    from playwright.sync_api import FloatRect, Page

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

#: Slack for borders and sub-pixel rounding (px).
SLACK = 4


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def box(page: Page, selector: str) -> FloatRect:
    """The bounding box of the first match, which must be on the page."""
    found = page.locator(selector).first.bounding_box()
    assert found is not None, f"{selector} is not visible"
    return found


def same_row(page: Page) -> bool:
    """Source and Transform start at the same height (side by side)."""
    return (
        abs(box(page, "[data-panel=source]")["y"] - box(page, "[data-panel=transform]")["y"])
        <= SLACK
    )


def open_editor(page: WatchedPage, server: LiveServer) -> EditorPage:
    editor = EditorPage(page, server)
    editor.goto()
    editor.paste(BUDGET.csv)
    return editor


@pytest.mark.parametrize("viewport", [DESKTOP], ids=["desktop"])
def test_the_chart_is_a_full_width_row_above_source_and_transform(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = open_editor(page, live_server)

    root = box(page, "#page-root")
    chart = box(page, "[data-panel=chart]")
    source = box(page, "[data-panel=source]")
    transform = box(page, "[data-panel=transform]")
    entries = box(page, "[data-panel=entries]")

    assert chart["width"] >= root["width"] - SLACK, "the chart row spans the page"
    assert chart["y"] + chart["height"] <= source["y"] + SLACK, "the chart is above Source"
    assert abs(source["y"] - transform["y"]) <= SLACK, "Source and Transform share a row"
    assert transform["x"] > source["x"] + source["width"] - SLACK
    assert (
        entries["y"]
        >= max(source["y"] + source["height"], transform["y"] + transform["height"]) - SLACK
    )
    expect(page.get_by_role("link", name="Go to the chart")).to_have_count(0)
    expect(editor.tid("chart-settings-button")).to_be_visible()


@pytest.mark.parametrize("viewport", [DESKTOP], ids=["desktop"])
def test_the_chart_row_is_not_sticky_and_the_page_has_no_side_panes(
    page: WatchedPage, live_server: LiveServer
) -> None:
    open_editor(page, live_server)

    position = page.evaluate("getComputedStyle(document.querySelector('#editor-output')).position")
    side_panes = page.locator(".editor-layout, .editor-pane, .editor-pane-preview")

    assert position == "relative", "the row only anchors the settings popover"
    expect(side_panes).to_have_count(0)
    expect(page.locator("#editor-output [data-panel=chart]")).to_be_visible()
    expect(page.locator("#editor-output [data-panel=style]")).to_be_hidden()


@pytest.mark.parametrize("viewport", [PHONE], ids=["phone"])
def test_the_rows_stack_on_a_phone_and_nothing_scrolls_sideways(
    page: WatchedPage, live_server: LiveServer
) -> None:
    open_editor(page, live_server)

    chart = box(page, "[data-panel=chart]")
    source = box(page, "[data-panel=source]")
    transform = box(page, "[data-panel=transform]")

    assert source["y"] >= chart["y"] + chart["height"] - SLACK, "phone: the chart comes first"
    assert transform["y"] >= source["y"] + source["height"] - SLACK, "phone: Transform under Source"
    assert abs(source["x"] - chart["x"]) < SLACK * 2, "phone: one column"
    assert chart["width"] <= PHONE["width"]
    assert overflow_pixels(page) <= 0


def test_the_layout_follows_the_window_width(page: WatchedPage, live_server: LiveServer) -> None:
    open_editor(page, live_server)
    side_by_side = same_row(page)

    page.set_viewport_size(PHONE)
    poll_js(page, "innerWidth === 390", what="the phone width")
    stacked = same_row(page)
    page.set_viewport_size(DESKTOP)
    poll_js(page, "innerWidth === 1280", what="the desktop width")

    assert (side_by_side, stacked, same_row(page)) == (True, False, True)
