# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Waits on the DOM signals of the app (docs/ui/testing.md). Never ``networkidle``, never a sleep.

All of them are Playwright ``expect`` assertions, so they retry until the (suite-wide) expect
timeout and fail with Playwright's own message. They need no CSP-blocked ``wait_for_function``.

* ``wait_shell(page)``       - ``body[data-shell=ready]``: ``core/shell.js`` has wired the page.
* ``wait_page(page, name)``  - ``main[data-page=<name>]`` (``library``, ``new``, ``edit``,
  ``viewer``, ``compare``, ``settings``, ``notfound``).
* ``wait_idle(page)``        - ``#main[data-loading=false]``: no API request and no pending or
  running editor preview. Turns ``true`` at once on a change, so it is safe right after an input.
* ``wait_chart(page, testid)`` - the chart div with that test id has ``data-ready=true``
  (``sankey-chart`` by default, or ``donut-chart``). It is true for the OLD chart while a new
  request runs, so use ``wait_preview`` after changing an input.
* ``wait_editor(page)``      - ``#page-root[data-ready=true]``: the editor mounted every panel.
* ``wait_preview(page)``     - ``wait_idle`` then ``wait_chart``: the safe wait after an edit.
* ``wait_charts(page, count)`` - ``count`` chart divs are ready, none is still drawing or failed
  (the compare page: one chart per card, drawn lazily; use a tall viewport).
* ``chart_state(page, testid)`` - the current ``data-ready`` value without waiting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Page

SANKEY_CHART = "sankey-chart"
DONUT_CHART = "donut-chart"
CHARTS = ":is([data-testid=sankey-chart], [data-testid=donut-chart])"


def wait_shell(page: Page) -> None:
    expect(page.locator("body")).to_have_attribute("data-shell", "ready")


def wait_page(page: Page, name: str) -> None:
    expect(page.get_by_test_id("app-root")).to_have_attribute("data-page", name)


def wait_idle(page: Page) -> None:
    expect(page.get_by_test_id("app-root")).to_have_attribute("data-loading", "false")


def wait_chart(page: Page, testid: str = SANKEY_CHART) -> None:
    expect(page.get_by_test_id(testid)).to_have_attribute("data-ready", "true")


def wait_editor(page: Page) -> None:
    expect(page.locator("#page-root")).to_have_attribute("data-ready", "true")


def wait_preview(page: Page, testid: str = SANKEY_CHART) -> None:
    wait_idle(page)
    wait_chart(page, testid)


def wait_charts(page: Page, count: int) -> None:
    drawn = f"{CHARTS}[data-ready=true]"
    expect(page.locator(drawn)).to_have_count(count)
    expect(page.locator(f"{CHARTS}[data-ready=false], {CHARTS}[data-ready=error]")).to_have_count(0)


def chart_state(page: Page, testid: str = SANKEY_CHART) -> str | None:
    """``data-ready`` of the chart (``"true"``, ``"false"``, ``"error"``) or ``None`` if absent."""
    chart = page.get_by_test_id(testid)
    return chart.get_attribute("data-ready") if chart.count() else None
