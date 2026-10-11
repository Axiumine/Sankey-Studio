"""``ComparePage``: the page object of ``/compare?ids=...`` (UI.md section 4.5).

Cards are found by the graph name in their heading. ``donut_colours(name)`` reads the colour of
every category from the Plotly figure of a card's donut (the page keeps it on the chart div), so
tests can compare what two cards draw without parsing pixels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.ui_b_common import query_of
from tests.e2e.support.ui_b_library import exact
from tests.e2e.support.uiwait import wait_idle

if TYPE_CHECKING:
    from collections.abc import Sequence

    from playwright.sync_api import Locator, Response

_COLOURS_JS = """chart => Object.fromEntries(
    chart.data[0].labels.map((label, i) => [label, chart.data[0].marker.colors[i]]))"""


class ComparePage(AppPage):
    path = "/compare"
    name = "compare"

    def open_ids(self, ids: Sequence[str]) -> Response | None:
        return self.goto("?ids=" + ",".join(ids))

    # ------------------------------------------------------------------ locators

    @property
    def cards(self) -> Locator:
        return self.tid("compare-card")

    @property
    def missing(self) -> Locator:
        return self.tid("compare-missing")

    @property
    def count_line(self) -> Locator:
        return self.page.get_by_role("region", name="Comparison").get_by_role("status").first

    def card(self, name: str) -> Locator:
        title = self.page.get_by_role("heading", level=2).filter(has_text=exact(name))
        return self.cards.filter(has=title)

    def toggle(self, name: str) -> Locator:
        return self.card(name).get_by_test_id("compare-card-toggle")

    def summary(self, name: str) -> Locator:
        return self.card(name).get_by_role("table", name=f"Summary of {name}")

    def url_ids(self) -> list[str]:
        ids = query_of(self.page.url).get("ids", "")
        return [part for part in ids.split(",") if part]

    # ------------------------------------------------------------------ actions

    def remove(self, name: str) -> None:
        self.card(name).get_by_test_id("compare-remove").click()

    def add(self, name: str) -> None:
        self.tid("compare-add-select").select_option(label=name)
        self.tid("compare-add").click()
        wait_idle(self.page)

    def expect_drawn(self, name: str) -> None:
        """The Sankey of the card ``name`` is drawn (``data-ready=true`` and real nodes)."""
        chart = self.card(name).get_by_test_id("sankey-chart")
        expect(chart).to_have_attribute("data-ready", "true")
        expect(chart.locator(".sankey-node").first).to_be_attached()

    def donut_colours(self, name: str) -> dict[str, str]:
        chart = self.card(name).get_by_test_id("donut-chart")
        expect(chart).to_have_attribute("data-ready", "true")
        return dict(chart.evaluate(_COLOURS_JS))
