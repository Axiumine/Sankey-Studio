"""Page object of the viewer ``/graphs/<id>`` for the UI-A suites (UI.md section 4.4).

``ViewerPage.open(graph_id)`` goes to the viewer and waits for the Sankey to be drawn;
``open_donut()`` switches to the donut tab and waits for it. Export controls
(``export-*`` test ids) are plain locators: ``viewer.tid("export-sankey-svg")``, but they sit in a
popover that the download icon (``export-menu-button``) opens, so a test calls
``open_export_menu()`` first (``set_export_size`` does it itself). A press on a tab, like any press
outside the popover, closes it again: call ``open_export_menu()`` after ``open_donut()``.
``open_export_menu(page_object)`` is the same step for the page object of another suite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.uiwait import DONUT_CHART, wait_chart

if TYPE_CHECKING:
    from playwright.sync_api import Locator

EXPORT_BUTTON: Final = "export-menu-button"
EXPORT_PANEL: Final = "export-menu-panel"


def open_export_menu(viewer: AppPage) -> None:
    """Open the export popover of ``viewer`` (a viewer page object); a no-op when it is open."""
    panel = viewer.tid(EXPORT_PANEL)
    if not panel.is_visible():
        viewer.tid(EXPORT_BUTTON).click()
    expect(panel).to_be_visible()


class ViewerPage(AppPage):
    """The viewer of a saved graph."""

    path = "/graphs/"
    name = "viewer"

    @property
    def export_button(self) -> Locator:
        """The download icon at the right of the tab row."""
        return self.tid(EXPORT_BUTTON)

    @property
    def export_panel(self) -> Locator:
        """The popover that holds every ``export-*`` control (hidden until the icon is clicked)."""
        return self.tid(EXPORT_PANEL)

    def open(self, graph_id: str) -> None:
        self.goto(graph_id)
        wait_chart(self.page)

    def open_donut(self) -> None:
        self.tid("chart-tab-donut").click()
        wait_chart(self.page, DONUT_CHART)
        expect(self.tid("donut-chart")).to_be_visible()

    def open_export_menu(self) -> None:
        """Click the icon when the export popover is closed and wait until it shows (idempotent)."""
        open_export_menu(self)

    def set_export_size(self, *, width: str | None = None, scale: str | None = None) -> None:
        """Fill the size inputs of the export popover (``None`` leaves a field alone)."""
        self.open_export_menu()
        if width is not None:
            self.tid("export-width").fill(width)
        if scale is not None:
            self.tid("export-scale").fill(scale)
