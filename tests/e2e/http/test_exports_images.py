"""E2E A.4 (exports, real Chrome): SVG and PNG of the Sankey and the donut, drawn by the server.

Slow tests: each image costs one Chrome start (about a second). They skip when the server has no
Chrome (501). One server for the module; every graph has its own name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import BUDGET, MANY_LINKS, csv_text, graph_draft, unique_name
from tests.e2e.support.clients import make_client, seed_graph
from tests.e2e.support.http_a_exports import (
    assert_download,
    export,
    export_draft,
    need_chrome,
    parse_disposition,
)
from tests.e2e.support.http_a_images import alpha_range, png_info, svg_tags, svg_texts

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

pytestmark = pytest.mark.slow

HOSTILE = [
    "R&D <b>x</b>",
    "<img src=x onerror=alert(1)>",
    "</text><script>alert(1)</script>",
    "AT&amp;T",  # a typed entity is drawn as typed (Plotly would decode it without the escaping)
]
DONUT_HOSTILE = "Fixed <i>costs</i> & more"
FIGURE_HEIGHT = 560  # the default height of a figure (style.height)


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: each test saves graphs under names of its own."""
    return module_server


@pytest.fixture
def hostile_graph(api: httpx.Client) -> dict[str, str]:
    rows = [("Salary", HOSTILE[0], 10, DONUT_HOSTILE), (HOSTILE[1], HOSTILE[2], 10, "Other things")]
    return seed_graph(api, unique_name("Hostile"), graph_draft(csv_text(rows)))


def test_the_svg_is_well_formed_and_draws_hostile_labels_as_plain_text(
    api: httpx.Client,
) -> None:
    rows = [("Salary", HOSTILE[0], 10), (HOSTILE[1], HOSTILE[2], 10), (HOSTILE[2], "Out", 10)]
    rows.append((HOSTILE[2], HOSTILE[3], 10))
    draft = graph_draft(csv_text(rows), style={"title": "Escaping check"})
    answer = need_chrome(export_draft(api, draft, format="svg", width=900))
    assert_download(answer, "svg")
    svg = answer.text
    assert svg.startswith("<svg")
    assert parse_disposition(answer).utf8 == "Escaping check.svg"
    assert f'width="1800" height="{FIGURE_HEIGHT * 2}"' in svg  # 900 x 2 (scale), 560 x 2
    assert f'viewBox="0 0 900 {FIGURE_HEIGHT}"' in svg
    texts = svg_texts(svg)  # parsing it also proves the SVG is well-formed XML
    for label in HOSTILE:
        assert label in texts  # drawn exactly as typed ...
    assert not {"b", "img", "script", "a"} & svg_tags(svg)  # ... and never as live markup
    assert "<b>x</b>" not in svg
    assert "<img" not in svg


@dataclass(frozen=True, slots=True)
class PngCase:
    """The query of a PNG export and the pixel size of the file it must give."""

    width: int
    height: int | None
    scale: float
    size: tuple[int, int]


PNG_CASES = [
    pytest.param(PngCase(400, None, 2, (800, FIGURE_HEIGHT * 2)), id="width-and-scale"),
    pytest.param(PngCase(400, 300, 1, (400, 300)), id="width-and-height"),
    pytest.param(PngCase(100, 100, 1, (200, 200)), id="clamped-up-to-200"),
    pytest.param(PngCase(9000, 300, 1, (4000, 300)), id="clamped-down-to-4000"),
]


@pytest.mark.parametrize("case", PNG_CASES)
def test_the_png_has_the_requested_dimensions(api: httpx.Client, case: PngCase) -> None:
    graph = seed_graph(api, unique_name("Png sizes"), graph_draft(BUDGET.csv))
    params: dict[str, float] = {"width": case.width, "scale": case.scale}
    if case.height is not None:
        params["height"] = case.height
    answer = need_chrome(export(api, graph["id"], format="png", **params))
    assert_download(answer, "png")
    info = png_info(answer.content)  # asserts the PNG magic and the IHDR chunk
    assert (info.width, info.height) == case.size
    assert parse_disposition(answer).utf8 == f"{graph['name']}.png"


def test_a_transparent_png_has_transparent_pixels_and_the_default_has_none(
    api: httpx.Client,
) -> None:
    graph = seed_graph(api, unique_name("Alpha"), graph_draft(BUDGET.csv))
    small = {"format": "png", "width": 200, "height": 200, "scale": 1}
    opaque = need_chrome(export(api, graph["id"], **small))
    transparent = export(api, graph["id"], transparent="true", **small)
    assert alpha_range(opaque.content) == (255, 255)  # a solid background everywhere
    lowest, highest = alpha_range(transparent.content)
    assert lowest == 0  # the background is see-through ...
    assert highest > 0  # ... and the chart is still drawn on it


def test_the_donut_svg_and_png_are_named_with_a_suffix(
    api: httpx.Client, hostile_graph: dict[str, str]
) -> None:
    donut = {"chart": "donut", "width": 400, "height": 300, "scale": 1}
    svg = need_chrome(export(api, hostile_graph["id"], format="svg", **donut))
    assert_download(svg, "svg")
    assert svg.text.startswith("<svg")
    assert parse_disposition(svg).utf8 == f"{hostile_graph['name']}-donut.svg"
    assert DONUT_HOSTILE in svg_texts(svg.text)
    assert "<i>" not in svg.text
    assert not {"i", "b"} & svg_tags(svg.text)
    png = export(api, hostile_graph["id"], format="png", **donut)
    assert_download(png, "png")
    assert (png_info(png.content).width, png_info(png.content).height) == (400, 300)
    assert parse_disposition(png).utf8 == f"{hostile_graph['name']}-donut.png"


def test_images_are_drawn_like_the_screen_with_at_most_max_drawn_links(
    make_server: ServerFactory,
) -> None:
    server = make_server(settings={"max_drawn_links": 50})
    with make_client(server) as api:
        graph = seed_graph(api, unique_name("Many"), graph_draft(MANY_LINKS.csv))
        svg = need_chrome(export(api, graph["id"], format="svg", width=600, scale=1))
        assert svg.text.count('class="sankey-link"') == 50
        assert "Showing 50 of 300 links" in svg_texts(svg.text)
        csv_rows = export(api, graph["id"], format="csv").text.splitlines()
        assert len(csv_rows) - 1 == MANY_LINKS.links  # the CSV is never cut
