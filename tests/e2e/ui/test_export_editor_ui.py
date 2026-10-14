"""B4, part 2: downloads from the editor (the draft, not a saved graph).

The editor exports the draft: ``graph`` until the Name field has text, then the name (``-donut``
for the donut chart that ``export-data-chart`` picks for HTML, JSON and CSV), the images drawn by
the server (Chrome) included. A page with a new-graph wizard asks for a name first, so the first
download carries ``EditorPage.wizard_name`` there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET_CATEGORISED, unique_name
from tests.e2e.support.ui_a_downloads import (
    SVG_PREFIX,
    download,
    expect_image_size,
    image_size_hint,
    png_info,
)
from tests.e2e.support.ui_a_editor import EditorPage

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

SANKEY_CSV_HEADER = "source,target,value,category"
DONUT_CSV_HEADER = "category,value,share"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def test_the_editor_exports_the_draft_named_graph_until_it_has_a_name_images_included(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = EditorPage(page, live_server)
    editor.goto()
    editor.paste(BUDGET_CATEGORISED.csv)
    name = unique_name("Draft export")

    editor.open_export()
    unnamed = download(page, editor.tid("export-csv"))
    editor.set_name(name)
    editor.open_export()
    named = download(page, editor.tid("export-csv"))
    editor.tid("export-data-chart").select_option("donut")
    donut = download(page, editor.tid("export-csv"))
    donut_json = download(page, editor.tid("export-json"))
    svg = download(page, editor.tid("export-sankey-svg"))
    donut_svg = download(page, editor.tid("export-donut-svg"))

    assert unnamed.name == f"{editor.wizard_name or 'graph'}.csv"  # a wizard asks for a name first
    assert unnamed.text.splitlines()[0] == SANKEY_CSV_HEADER
    assert named.name == f"{name}.csv"
    assert donut.name == f"{name}-donut.csv"
    assert donut.text.splitlines()[0] == DONUT_CSV_HEADER
    assert donut_json.name == f"{name}-donut.json"
    assert svg.name == f"{name}.svg"
    assert svg.data.startswith(SVG_PREFIX)
    assert donut_svg.name == f"{name}-donut.svg"
    assert donut_svg.data.startswith(SVG_PREFIX)
    expect(editor.tid("export-fallback-note")).to_be_hidden()


def test_the_editor_images_follow_the_size_inputs_of_the_export_card(
    page: WatchedPage, live_server: LiveServer
) -> None:
    """Width, height and scale typed in the editor reach the server (as in the viewer)."""
    editor = EditorPage(page, live_server)
    editor.goto()
    editor.paste(BUDGET_CATEGORISED.csv)

    editor.open_export()
    editor.tid("export-width").fill("600")
    editor.tid("export-height").fill("700")
    editor.tid("export-scale").fill("1")
    expect_image_size(page, 600, 700)
    exact = png_info(download(page, editor.tid("export-sankey-png")).data)
    svg = download(page, editor.tid("export-sankey-svg"))

    editor.tid("export-width").fill("400")
    editor.tid("export-height").fill("")
    editor.tid("export-scale").fill("2")
    expect_image_size(page, 800)
    announced = image_size_hint(page)
    doubled = png_info(download(page, editor.tid("export-sankey-png")).data)

    assert (exact.width, exact.height) == (600, 700)
    assert 'viewBox="0 0 600 700"' in svg.text
    assert (doubled.width, doubled.height) == announced
    assert doubled.width == 800  # 400 wide at scale 2, not the 1200 x 2 of an untouched card
    expect(editor.tid("export-fallback-note")).to_be_hidden()
