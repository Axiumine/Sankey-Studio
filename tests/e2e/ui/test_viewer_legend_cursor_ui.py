"""The viewer's legends and the mouse cursor.

The Sankey legend is a label: its entries do nothing when clicked, so the cursor over a coloured
square stays the standard arrow. Plotly gives every legend entry an inline pointer cursor, which
the viewer resets for the Sankey only; the donut legend does hide and show slices, so it keeps the
pointer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import make_client, seed_graph
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

#: The cursor of the element under the middle of the first legend square of a chart.
_CURSOR_UNDER_SQUARE_JS = """chart => {
    const square = chart.querySelector('.legend .legendpoints path');
    const box = square.getBoundingClientRect();
    const under = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return getComputedStyle(under).cursor;
}"""


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def graph_id(module_server: LiveServer) -> str:
    draft = graph_draft(BUDGET_CATEGORISED.csv, style={"color_mode": "category"})
    with make_client(module_server) as client:
        return str(seed_graph(client, unique_name("Legend cursor"), draft)["id"])


@pytest.fixture
def viewer(page: WatchedPage, live_server: LiveServer, graph_id: str) -> ViewerPage:
    viewer = ViewerPage(page, live_server)
    viewer.open(graph_id)
    return viewer


def test_the_cursor_over_a_sankey_legend_square_is_the_standard_arrow(viewer: ViewerPage) -> None:
    chart = viewer.tid("sankey-chart")

    assert chart.evaluate(_CURSOR_UNDER_SQUARE_JS) == "default"


def test_the_cursor_over_a_donut_legend_square_stays_the_pointer_that_toggles_a_slice(
    viewer: ViewerPage,
) -> None:
    viewer.open_donut()

    assert viewer.tid("donut-chart").evaluate(_CURSOR_UNDER_SQUARE_JS) == "pointer"
