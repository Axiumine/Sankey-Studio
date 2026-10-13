"""The display menu of the viewer (``/graphs/<id>``) and the requests it sends (UI-A suites).

``DisplayMenu(viewer)``    - the icon at the right of the tab row and its panel of view-only
                             switches: ``open()``, ``switch(testid)``, ``set(testid, on)`` (clicks
                             the switch and waits for the redraw request to be answered).
``RequestLog(page)``       - the ``/render`` and ``/export`` requests the page sends, as parsed
                             query strings: ``queries("render")``, ``last("export")``.
``tab_strip_overflow(page)`` - ``(scrollHeight, clientHeight)`` of the chart card's tab strip.

The switch ids are ``display-node-values``, ``display-donut-percent`` and ``display-donut-value``.
Redraws are waited for on the server's answer (``expect_response``), then on what the chart shows
(``ChartDom.node_label`` / ``donut_slice``), never on a sleep.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import parse_qsl, urlsplit

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page, Request

    from tests.e2e.support.ui_a_viewer import ViewerPage

NODE_VALUES: Final = "display-node-values"
DONUT_PERCENT: Final = "display-donut-percent"
DONUT_VALUE: Final = "display-donut-value"
_OVERFLOW_JS = "el => [el.scrollHeight, el.clientHeight]"


class RequestLog:
    """Every ``/api/v1/graphs/<id>/render`` and ``/export`` request of ``page`` from now on."""

    def __init__(self, page: Page) -> None:
        self.requests: list[Request] = []
        page.on("request", self._seen)

    def _seen(self, request: Request) -> None:
        path = urlsplit(request.url).path
        if path.endswith(("/render", "/export")):
            self.requests.append(request)

    def queries(self, kind: str) -> list[dict[str, str]]:
        """The query strings (name -> value) of the ``kind`` requests, oldest first."""
        found = [r for r in self.requests if urlsplit(r.url).path.endswith(f"/{kind}")]
        return [dict(parse_qsl(urlsplit(r.url).query)) for r in found]

    def last(self, kind: str) -> dict[str, str]:
        return self.queries(kind)[-1]


class DisplayMenu:
    """The display menu of one viewer page."""

    def __init__(self, viewer: ViewerPage) -> None:
        self.viewer = viewer
        self.page = viewer.page

    @property
    def button(self) -> Locator:
        return self.viewer.tid("display-menu-button")

    @property
    def panel(self) -> Locator:
        return self.viewer.tid("display-menu-panel")

    def open(self) -> None:
        self.button.click()
        expect(self.panel).to_be_visible()
        expect(self.button).to_have_attribute("aria-expanded", "true")

    def close(self) -> None:
        self.page.keyboard.press("Escape")
        expect(self.panel).to_be_hidden()

    def switch(self, testid: str) -> Locator:
        return self.viewer.tid(testid)

    def set(self, testid: str, on: bool) -> None:
        """Turn a switch on or off and wait until the server has answered the redraw."""
        with self.page.expect_response(lambda r: "/render" in r.url):
            self.switch(testid).set_checked(on)


def tab_strip_overflow(page: Page) -> tuple[int, int]:
    """``(scrollHeight, clientHeight)`` of the "Chart type" tab strip; equal: it cannot scroll."""
    strip = page.get_by_role("tablist", name="Chart type")
    height, client = strip.evaluate(_OVERFLOW_JS)
    return int(height), int(client)
