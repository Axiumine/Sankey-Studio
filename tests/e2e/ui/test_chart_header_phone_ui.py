# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""On a phone the chart header (tabs plus tools) wraps instead of squeezing the tabs or the gear."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import graph_draft, unique_name
from tests.e2e.support.clients import seed_graph
from tests.e2e.support.ui_a_editor import EditGraphPage
from tests.e2e.support.ui_b_common import PHONE, overflow_pixels

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

ORDER = ["Salary", "Freelance", "Budget"]


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.mark.parametrize("viewport", [PHONE], ids=["phone"])
def test_with_a_node_order_the_tabs_fit_and_the_gear_stays_in_the_window(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    draft = graph_draft(style={"node_order": ORDER})
    graph_id = str(seed_graph(api, unique_name("Phone header"), draft)["id"])
    editor = EditGraphPage(page, live_server)
    editor.open(graph_id)
    expect(editor.tid("chart-reset-order")).to_be_visible()

    tabs = page.locator(".out-chart-head .out-tabs")
    fits = tabs.evaluate("(el) => el.scrollWidth <= el.clientWidth + 1")
    assert fits
    for testid in ("chart-settings-button", "chart-reset-order", "chart-order-open"):
        box = editor.tid(testid).bounding_box()
        assert box is not None
        assert box["x"] >= 0
        assert box["x"] + box["width"] <= PHONE["width"]
    assert overflow_pixels(page) <= 0
