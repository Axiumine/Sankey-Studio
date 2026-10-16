# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""B4, part 1: every download of the viewer, drawn by the server (real Chrome, a second each).

Real downloads: the file names (``<name>.svg``, ``<name>-donut.svg``, ``.csv`` ...), the SVG and
PNG content, the PNG size that follows the width / height / scale inputs and the size line of the
card, the transparent background, the inputs that must stop a download, and the HTML, JSON and
CSV data of both charts. The server draws everything, so the browser fallback note stays hidden.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET_CATEGORISED
from tests.e2e.support.ui_a_downloads import (
    OPAQUE,
    SVG_PREFIX,
    download,
    expect_image_size,
    image_size_hint,
    png_info,
)
from tests.e2e.support.ui_a_seed import SavedGraph, save_graph
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

TRANSPARENT = 0
SANKEY_CSV_HEADER = "source,target,value,category"
DONUT_CSV_HEADER = "category,value,share"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def saved(module_server: LiveServer) -> SavedGraph:
    return save_graph(module_server, "Image export")


@pytest.fixture
def viewer(page: WatchedPage, live_server: LiveServer, saved: SavedGraph) -> ViewerPage:
    viewer = ViewerPage(page, live_server)
    viewer.open(saved.id)
    return viewer


def step_sizes_outside_the_limits_stop_a_download(viewer: ViewerPage) -> None:
    requests: list[str] = []
    viewer.page.on(
        "request",
        lambda request: requests.append(request.url) if "/export" in request.url else None,
    )
    viewer.open_export_menu()
    viewer.tid("export-width").fill("100")
    viewer.tid("export-sankey-svg").click()
    expect(viewer.page.get_by_text("Enter a width from 200 to 4000.")).to_be_visible()
    expect(viewer.tid("export-width")).to_be_focused()
    viewer.tid("export-width").fill("1200")
    viewer.tid("export-scale").fill("9")
    viewer.tid("export-sankey-png").click()
    expect(viewer.page.get_by_text("Enter a scale from 0.5 to 4.")).to_be_visible()
    viewer.tid("export-scale").fill("2")
    viewer.tid("export-height").fill("50")
    viewer.tid("export-sankey-png").click()
    message = "Leave empty, or enter a height from 200 to 4000."
    expect(viewer.page.get_by_text(message)).to_be_visible()
    assert requests == []
    viewer.tid("export-height").fill("")


def step_svg_png_and_data_of_the_sankey(viewer: ViewerPage, saved: SavedGraph) -> None:
    viewer.open_export_menu()
    expect_image_size(viewer.page, 2400, 1120)
    width, height = image_size_hint(viewer.page)

    svg = download(viewer.page, viewer.tid("export-sankey-svg"))
    png = download(viewer.page, viewer.tid("export-sankey-png"))

    assert svg.name == f"{saved.name}.svg"
    assert svg.data.startswith(SVG_PREFIX)
    for label in ("Salary", "Freelance", "Groceries"):
        assert label in svg.text
    assert png.name == f"{saved.name}.png"
    info = png_info(png.data)
    assert (info.width, info.height) == (width, height)
    assert info.corner_alpha == OPAQUE
    viewer.expect_toast(f"Saved {saved.name}.png", "success")

    csv_file = download(viewer.page, viewer.tid("export-csv"))
    json_file = download(viewer.page, viewer.tid("export-json"))
    html_file = download(viewer.page, viewer.tid("export-html"))
    assert csv_file.name == f"{saved.name}.csv"
    lines = csv_file.text.splitlines()
    assert lines[0] == SANKEY_CSV_HEADER
    assert len(lines) == 1 + BUDGET_CATEGORISED.links
    assert "Budget,Rent,1200" in csv_file.text
    assert json_file.name == f"{saved.name}.json"
    figure = json.loads(json_file.text)
    assert figure["data"][0]["type"] == "sankey"
    assert "Salary" in figure["data"][0]["node"]["label"]
    assert html_file.name == f"{saved.name}.html"
    assert html_file.text.lstrip().lower().startswith(("<html", "<!doctype html"))
    assert "Plotly" in html_file.text
    assert "Salary" in html_file.text
    expect(viewer.tid("export-fallback-note")).to_be_hidden()


def step_png_size_follows_the_inputs_and_transparent_has_no_paint(viewer: ViewerPage) -> None:
    viewer.set_export_size(width="600", scale="1")
    viewer.tid("export-height").fill("700")
    expect_image_size(viewer.page, 600, 700)

    opaque = png_info(download(viewer.page, viewer.tid("export-sankey-png")).data)
    viewer.tid("export-transparent").check()
    transparent = png_info(download(viewer.page, viewer.tid("export-sankey-png")).data)

    assert (opaque.width, opaque.height) == (600, 700)
    assert (transparent.width, transparent.height) == (600, 700)
    assert opaque.corner_alpha == OPAQUE
    assert transparent.corner_alpha == TRANSPARENT


def step_donut_images_and_data(viewer: ViewerPage, saved: SavedGraph) -> None:
    viewer.open_donut()  # a press on the tab closed the popover: the icon opens it again
    viewer.open_export_menu()
    expect(viewer.tid("export-sankey-svg")).to_be_hidden()
    expect(viewer.tid("export-donut-svg")).to_be_visible()
    viewer.tid("export-transparent").uncheck()
    viewer.tid("export-height").fill("")
    viewer.set_export_size(width="800", scale="1.5")
    expect_image_size(viewer.page, 1200)
    width, height = image_size_hint(viewer.page)

    svg = download(viewer.page, viewer.tid("export-donut-svg"))
    png = download(viewer.page, viewer.tid("export-donut-png"))
    csv_file = download(viewer.page, viewer.tid("export-csv"))
    json_file = download(viewer.page, viewer.tid("export-json"))

    assert svg.name == f"{saved.name}-donut.svg"
    assert svg.data.startswith(SVG_PREFIX)
    assert "Income" in svg.text
    assert png.name == f"{saved.name}-donut.png"
    info = png_info(png.data)
    assert (info.width, info.height) == (width, height)
    assert csv_file.name == f"{saved.name}-donut.csv"
    donut_lines = csv_file.text.splitlines()
    assert donut_lines[0] == DONUT_CSV_HEADER
    names = sorted(line.split(",")[0] for line in donut_lines[1:])
    assert names == sorted(BUDGET_CATEGORISED.categories)
    assert json_file.name == f"{saved.name}-donut.json"
    assert json.loads(json_file.text)["data"][0]["type"] == "pie"


def test_the_viewer_stops_bad_sizes_and_downloads_svg_png_csv_json_and_html_of_the_sankey(
    viewer: ViewerPage, saved: SavedGraph
) -> None:
    step_sizes_outside_the_limits_stop_a_download(viewer)
    step_svg_png_and_data_of_the_sankey(viewer, saved)


def test_the_viewer_png_follows_the_size_inputs_and_the_donut_tab_exports_the_donut(
    viewer: ViewerPage, saved: SavedGraph
) -> None:
    step_png_size_follows_the_inputs_and_transparent_has_no_paint(viewer)
    step_donut_images_and_data(viewer, saved)
