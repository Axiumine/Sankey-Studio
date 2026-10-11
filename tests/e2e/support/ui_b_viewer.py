"""``ViewerPage`` (``/graphs/<id>``) and readers of the Plotly figure behind a chart div.

The chart div keeps its figure (``div.data`` and ``div.layout``), so a test can ask "what colour is
the paper" instead of looking at pixels. ``figure_colours`` returns every colour of the figure
normalised to ``#rrggbb`` (the transparent ones are left out), which is what the palette check
compares with ``sankey_studio.render.palette``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.uiwait import wait_chart, wait_idle

if TYPE_CHECKING:
    from playwright.sync_api import Locator

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

_COLOUR: Final = re.compile(r"#[0-9a-fA-F]{6}|rgba?\([^)]*\)")
_FIGURE_JS = "chart => JSON.stringify({data: chart.data, layout: chart.layout})"
_LAYOUT_JS = "chart => ({paper: chart.layout.paper_bgcolor, ink: chart.layout.font.color})"


def normalise(colour: str) -> str | None:
    """``rgba(42, 120, 214, 0.4)`` -> ``#2a78d6``; ``None`` for a fully transparent colour."""
    if colour.startswith("#"):
        return colour.lower()
    channels = [part.strip() for part in colour[colour.index("(") + 1 : -1].split(",")]
    if len(channels) == 4 and float(channels[3]) == 0:
        return None
    red, green, blue = (int(float(part)) for part in channels[:3])
    return f"#{red:02x}{green:02x}{blue:02x}"


def figure_colours(chart: Locator) -> set[str]:
    """Every non-transparent colour in the figure of ``chart``, as ``#rrggbb``."""
    text = str(chart.evaluate(_FIGURE_JS))
    found = {normalise(match) for match in _COLOUR.findall(text)}
    return {colour for colour in found if colour is not None}


def figure_surface(chart: Locator) -> tuple[str, str]:
    """``(paper background, text colour)`` of the figure of ``chart``."""
    layout = chart.evaluate(_LAYOUT_JS)
    return str(layout["paper"]), str(layout["ink"])


def expect_chart_theme(chart: Locator, theme: str) -> None:
    """The chart was (re)drawn for ``theme`` and is ready."""
    expect(chart).to_have_attribute("data-chart-theme", theme)
    expect(chart).to_have_attribute("data-ready", "true")


class ViewerPage(AppPage):
    name = "viewer"

    def __init__(self, page: WatchedPage, server: LiveServer, graph_id: str) -> None:
        super().__init__(page, server)
        self.graph_id = graph_id

    def url_for(self, suffix: str = "") -> str:
        return self.server.url_for(f"/graphs/{self.graph_id}") + suffix

    def expect_ready(self) -> None:
        super().expect_ready()
        wait_chart(self.page)
        wait_idle(self.page)

    @property
    def sankey(self) -> Locator:
        return self.tid("sankey-chart")

    @property
    def donut(self) -> Locator:
        return self.tid("donut-chart")

    def show_donut(self) -> None:
        self.tid("chart-tab-donut").click()
        wait_chart(self.page, "donut-chart")
