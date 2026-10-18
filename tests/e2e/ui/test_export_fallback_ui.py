# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""B4, part 3: a server that cannot draw images (501 ``export_unavailable``).

``make_server(export_unavailable=True)`` answers the production 501 for svg and png only. The UI
must then draw the image in the browser (``Plotly.downloadImage``) and still download a file with
the size the inputs ask for, say so in ``export-fallback-note``, and never fall back for the
html, json and csv exports, which the server still draws. The 501 itself shows up once per try as
a response and a console line, which every test here allows on purpose.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET_CATEGORISED, unique_name
from tests.e2e.support.ui_a_downloads import SVG_PREFIX, download, png_info
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_seed import SavedGraph, save_graph
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.watch import WatchedPage

NOTE = "This server cannot draw images"
EXPORT_PATH = "/export"
TRANSPARENT = 0


@pytest.fixture
def live_server(make_server: ServerFactory) -> LiveServer:
    return make_server(export_unavailable=True)


@pytest.fixture
def saved(live_server: LiveServer) -> SavedGraph:
    return save_graph(live_server, "Fallback")


@pytest.fixture
def viewer(live_server: LiveServer, page: WatchedPage, saved: SavedGraph) -> ViewerPage:
    # The 501 of every image try: the response and Chrome's console line (docs/ui/testing.md).
    # ``live_server`` comes first so that the server outlives the browser context at teardown.
    page.allow_http(501, EXPORT_PATH)
    viewer = ViewerPage(page, live_server)
    viewer.open(saved.id)
    return viewer


def test_the_viewer_draws_every_image_in_the_browser_and_still_exports_data_from_the_server(
    viewer: ViewerPage, saved: SavedGraph
) -> None:
    viewer.open_export_menu()
    note = viewer.tid("export-fallback-note")
    expect(note).to_be_hidden()

    svg = download(viewer.page, viewer.tid("export-sankey-svg"))

    assert svg.name == f"{saved.name}.svg"
    assert svg.data.startswith(SVG_PREFIX)
    assert "Salary" in svg.text
    expect(note).to_be_visible()
    expect(note).to_contain_text(NOTE)
    expect(note).to_contain_text("Your browser drew the image instead")

    viewer.set_export_size(width="800", scale="1")
    png = download(viewer.page, viewer.tid("export-sankey-png"))

    assert png.name == f"{saved.name}.png"
    info = png_info(png.data)
    assert (info.width, info.height) == (800, 560)

    viewer.open_donut()  # closes the popover; set_export_size opens it again
    viewer.set_export_size(width="700", scale="1")
    viewer.tid("export-transparent").check()
    donut_svg = download(viewer.page, viewer.tid("export-donut-svg"))
    donut_png = download(viewer.page, viewer.tid("export-donut-png"))

    assert donut_svg.name == f"{saved.name}-donut.svg"
    assert donut_svg.data.startswith(SVG_PREFIX)
    assert donut_png.name == f"{saved.name}-donut.png"
    assert png_info(donut_png.data).width == 700
    expect(note).to_contain_text("transparent background is only possible")
    assert len(viewer.page.watch.matching(r"^http 501: ")) == 4

    # html, json and csv never fall back: the server still draws them.
    csv_file = download(viewer.page, viewer.tid("export-csv"))
    json_file = download(viewer.page, viewer.tid("export-json"))
    html_file = download(viewer.page, viewer.tid("export-html"))
    assert csv_file.name == f"{saved.name}-donut.csv"
    assert csv_file.text.startswith("category,value,share")
    assert json.loads(json_file.text)["data"][0]["type"] == "pie"
    assert html_file.name == f"{saved.name}-donut.html"
    assert len(viewer.page.watch.matching(r"^http 501: ")) == 4


def test_the_editor_falls_back_too_and_a_transparent_png_keeps_its_clear_background(
    live_server: LiveServer, page: WatchedPage
) -> None:
    page.allow_http(501, EXPORT_PATH)
    editor = EditorPage(page, live_server)
    editor.goto()
    editor.paste(BUDGET_CATEGORISED.csv)
    name = unique_name("Editor fallback")
    editor.set_name(name)
    editor.open_export()

    svg = download(page, editor.tid("export-sankey-svg"))

    assert svg.name == f"{name}.svg"
    assert svg.data.startswith(SVG_PREFIX)
    expect(editor.tid("export-fallback-note")).to_contain_text(NOTE)

    editor.tid("export-width").fill("640")
    editor.tid("export-scale").fill("1")
    editor.tid("export-transparent").check()
    png = png_info(download(page, editor.tid("export-sankey-png")).data)

    assert png.width == 640
    assert png.corner_alpha == TRANSPARENT
    donut = download(page, editor.tid("export-donut-svg"))
    assert donut.name == f"{name}-donut.svg"
