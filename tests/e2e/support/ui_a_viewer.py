"""Page object of the viewer ``/graphs/<id>`` for the UI-A suites (UI.md section 4.4).

``ViewerPage.open(graph_id)`` goes to the viewer and waits for the Sankey to be drawn;
``open_donut()`` switches to the donut tab and waits for it. Export controls
(``export-*`` test ids) are plain locators: ``viewer.tid("export-sankey-svg")``.
"""

from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.uiwait import DONUT_CHART, wait_chart


class ViewerPage(AppPage):
    """The viewer of a saved graph."""

    path = "/graphs/"
    name = "viewer"

    def open(self, graph_id: str) -> None:
        self.goto(graph_id)
        wait_chart(self.page)

    def open_donut(self) -> None:
        self.tid("chart-tab-donut").click()
        wait_chart(self.page, DONUT_CHART)
        expect(self.tid("donut-chart")).to_be_visible()

    def set_export_size(self, *, width: str | None = None, scale: str | None = None) -> None:
        """Fill the size inputs of the export card (``None`` leaves a field alone)."""
        if width is not None:
            self.tid("export-width").fill(width)
        if scale is not None:
            self.tid("export-scale").fill(scale)
