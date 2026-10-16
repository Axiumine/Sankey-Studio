# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Image exports: size options, the pixel cap, the Chrome seam and its failures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from kaleido.errors import BrowserFailedError, ChromeNotFoundError

from sankey_studio.models import AppSettings
from sankey_studio.render.options import ResolvedImage
from sankey_studio.render.palette import TOKENS
from sankey_studio.web.routers import exports
from tests.web.test_routes_exports_support import (
    FakeRender,
    export_saved,
    install_render,
    install_slot,
)
from tests.web.test_routes_graphs_support import BUDGET, code, grid_source, save, save_source

if TYPE_CHECKING:
    from sankey_studio.models import GraphDefinition, Theme
    from tests.web.conftest import AppFactory, WebApp

TRANSPARENT = "rgba(0,0,0,0)"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([exports.router])


@pytest.fixture
def render(monkeypatch: pytest.MonkeyPatch) -> FakeRender:
    return install_render(monkeypatch)


@pytest.fixture
def stored(web: WebApp) -> GraphDefinition:
    return save(web, "Household", *BUDGET)


class Size(NamedTuple):
    params: dict[str, Any]
    width: int
    height: int | None  # None: the height of the figure
    scale: float


def sized(render: FakeRender) -> ResolvedImage:
    return render.calls[-1][1]


def test_the_defaults_are_1200_wide_at_scale_2_with_the_height_of_the_figure(
    web: WebApp, stored: GraphDefinition, render: FakeRender
) -> None:
    export_saved(web, stored.id, format="png")
    figure, resolved = render.calls[0]
    assert resolved == ResolvedImage("png", 1200, figure["layout"]["height"], 2.0)


@pytest.mark.parametrize(
    "case",
    [
        Size({"width": 800, "height": 600, "scale": 3}, 800, 600, 3.0),
        Size({"width": 1}, 200, None, 2.0),
        Size({"width": 199}, 200, None, 2.0),
        Size({"width": 200}, 200, None, 2.0),
        Size({"width": 4000}, 4000, None, 2.0),
        Size({"width": 4001}, 4000, None, 2.0),
        Size({"width": 100000}, 4000, None, 2.0),
        Size({"height": 1}, 1200, 200, 2.0),
        Size({"height": 199}, 1200, 200, 2.0),
        Size({"height": 4000}, 1200, 4000, 2.0),
        Size({"height": 100000}, 1200, 4000, 2.0),
        Size({"scale": 0.001}, 1200, None, 1.0),
        Size({"scale": 0.99}, 1200, None, 1.0),
        Size({"scale": 1}, 1200, None, 1.0),
        Size({"scale": 4}, 1200, None, 4.0),
        Size({"scale": 4.01}, 1200, None, 4.0),
        Size({"scale": 100}, 1200, None, 4.0),
    ],
    ids=lambda case: str(case.params),
)
def test_the_size_is_clamped_by_the_renderer(
    web: WebApp, stored: GraphDefinition, render: FakeRender, case: Size
) -> None:
    response = export_saved(web, stored.id, format="svg", **case.params)
    assert response.status_code == 200
    figure, resolved = render.calls[0]
    height = figure["layout"]["height"] if case.height is None else case.height
    assert (resolved.width, resolved.height, resolved.scale) == (case.width, height, case.scale)


class Pixels(NamedTuple):
    params: dict[str, Any]
    status: int


@pytest.mark.parametrize(
    "case",
    [
        Pixels({"width": 4000, "height": 2250, "scale": 2}, 200),  # exactly 36,000,000
        Pixels({"width": 4000, "height": 2251, "scale": 2}, 422),
        Pixels({"width": 4000, "height": 1125, "scale": 4}, 422),
        Pixels({"width": 20000, "height": 20000}, 422),
        Pixels({"width": 100000, "height": 100000, "scale": 100}, 422),
    ],
    ids=lambda case: str(case.params),
)
@pytest.mark.usefixtures("render")
def test_the_pixel_cap_is_36_million(web: WebApp, stored: GraphDefinition, case: Pixels) -> None:
    response = export_saved(web, stored.id, format="png", **case.params)
    assert response.status_code == case.status
    if case.status == 422:
        assert code(response) == "export_too_large"


def test_a_refused_size_never_reaches_chrome(
    web: WebApp, stored: GraphDefinition, render: FakeRender
) -> None:
    export_saved(web, stored.id, format="svg", width=20000, height=20000)
    assert render.calls == []


def test_transparent_clears_both_backgrounds(
    web: WebApp, stored: GraphDefinition, render: FakeRender
) -> None:
    export_saved(web, stored.id, format="png", transparent="true")
    layout = render.calls[0][0]["layout"]
    assert layout["paper_bgcolor"] == TRANSPARENT
    assert layout["plot_bgcolor"] == TRANSPARENT


@pytest.mark.parametrize("params", [{}, {"transparent": "false"}])
def test_the_backgrounds_are_opaque_unless_asked(
    web: WebApp, stored: GraphDefinition, render: FakeRender, params: dict[str, str]
) -> None:
    export_saved(web, stored.id, format="png", **params)
    layout = render.calls[0][0]["layout"]
    assert layout["paper_bgcolor"] == TOKENS["light"].surface
    assert layout["plot_bgcolor"] != TRANSPARENT


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_theme_reaches_the_chrome_figure(
    web: WebApp, stored: GraphDefinition, render: FakeRender, theme: Theme
) -> None:
    export_saved(web, stored.id, format="svg", theme=theme)
    assert render.calls[0][0]["layout"]["paper_bgcolor"] == TOKENS[theme].surface


class Failure(NamedTuple):
    error: BaseException
    status: int
    code: str


FAILURES = [
    Failure(ChromeNotFoundError("/usr/bin/secret-chrome"), 501, "export_unavailable"),
    Failure(TimeoutError("secret timeout"), 504, "export_timeout"),
    Failure(BrowserFailedError("secret crash"), 502, "export_failed"),
    Failure(RuntimeError("secret runtime"), 502, "export_failed"),
    Failure(OSError("secret disk"), 502, "export_failed"),
]


@pytest.mark.parametrize("case", FAILURES, ids=lambda case: type(case.error).__name__)
def test_a_renderer_failure_has_its_own_status_and_code(
    web: WebApp, stored: GraphDefinition, render: FakeRender, case: Failure
) -> None:
    render.error = case.error
    response = export_saved(web, stored.id, format="svg")
    assert response.status_code == case.status
    assert code(response) == case.code
    assert "secret" not in response.text
    assert "content-disposition" not in response.headers


def test_without_chrome_only_the_images_fail(
    web: WebApp, stored: GraphDefinition, render: FakeRender
) -> None:
    render.error = ChromeNotFoundError("none")
    assert export_saved(web, stored.id, format="png").status_code == 501
    for fmt in ("html", "json", "csv"):
        assert export_saved(web, stored.id, format=fmt).status_code == 200


def test_a_busy_exporter_is_a_503_export_busy(
    web: WebApp, stored: GraphDefinition, render: FakeRender, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot = install_slot(monkeypatch, free=False)
    response = export_saved(web, stored.id, format="svg")
    assert response.status_code == 503
    assert code(response) == "export_busy"
    assert render.calls == []
    assert slot.released == 0


def test_the_exporter_is_released_after_a_success_and_after_a_failure(
    web: WebApp, stored: GraphDefinition, render: FakeRender, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot = install_slot(monkeypatch, free=True)
    assert export_saved(web, stored.id, format="svg").status_code == 200
    assert slot.released == 1
    render.error = RuntimeError("boom")
    assert export_saved(web, stored.id, format="svg").status_code == 502
    assert slot.released == 2


class Rows(NamedTuple):
    rows: int
    status: int


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("case", [Rows(5000, 200), Rows(5001, 422)], ids=lambda c: str(c.rows))
def test_an_image_of_more_than_5000_links_is_refused(make_app: AppFactory, case: Rows) -> None:
    web = make_app([exports.router], settings=AppSettings(max_drawn_links=6000))
    big = save_source(web, "Big", grid_source(case.rows))
    response = export_saved(web, big.id, format="svg")
    assert response.status_code == case.status
    if case.status == 422:
        assert code(response) == "export_too_large"


class Nodes(NamedTuple):
    nodes: int
    status: int


def star_source(nodes: int) -> dict[str, Any]:
    """An inline CSV of ``nodes`` nodes: a hub with one link to each of ``nodes - 1`` targets."""
    lines = ["source,target,value", *(f"hub,t{i},1" for i in range(nodes - 1))]
    return {"type": "text", "origin": "inline", "format": "csv", "content": "\n".join(lines)}


@pytest.mark.parametrize("case", [Nodes(2000, 200), Nodes(2001, 422)], ids=lambda c: str(c.nodes))
def test_an_image_of_more_than_2000_nodes_is_refused(
    make_app: AppFactory, render: FakeRender, case: Nodes
) -> None:
    web = make_app([exports.router], settings=AppSettings(max_drawn_links=6000))
    big = save_source(web, "Big", star_source(case.nodes))
    response = export_saved(web, big.id, format="svg")
    assert response.status_code == case.status
    if case.status == 422:
        assert code(response) == "export_too_large"
        assert (
            f"{case.nodes - 1} links and {case.nodes} nodes" in response.json()["error"]["message"]
        )
        assert render.calls == []
    else:
        assert len(render.calls) == 1


@pytest.mark.usefixtures("render")
def test_the_size_limit_of_images_does_not_apply_to_the_other_formats(
    make_app: AppFactory,
) -> None:
    web = make_app([exports.router], settings=AppSettings(max_drawn_links=6000))
    big = save_source(web, "Big", grid_source(5001))
    for fmt in ("json", "csv"):
        assert export_saved(web, big.id, format=fmt).status_code == 200
