"""POST /api/v1/export: an unsaved draft, exported; and the rule that no figure is accepted."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.web.routers import exports
from tests.web.ids import stable_id
from tests.web.test_routes_exports_support import (
    IMAGES,
    MEDIA,
    FakeRender,
    disposition,
    export_draft,
    install_render,
)
from tests.web.test_routes_graphs_support import (
    API,
    BUDGET,
    PLAIN,
    code,
    draft_json,
)

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

FORMATS = ["svg", "png", "html", "json", "csv"]


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([exports.router])


@pytest.fixture
def render(monkeypatch: pytest.MonkeyPatch) -> FakeRender:
    return install_render(monkeypatch)


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("fmt", FORMATS)
def test_a_draft_is_exported_as_an_attachment_named_graph(web: WebApp, fmt: str) -> None:
    response = export_draft(web, draft_json(*BUDGET), format=fmt)
    assert response.status_code == 200
    assert response.headers["content-type"] == MEDIA[fmt]
    assert response.headers["content-disposition"] == disposition("graph", fmt)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("fmt", FORMATS)
def test_a_draft_donut_adds_the_donut_suffix_to_the_name(web: WebApp, fmt: str) -> None:
    named = draft_json(*BUDGET, style={"title": "Q3 Budget"})
    untitled = draft_json(*BUDGET)
    donut = export_draft(web, named, chart="donut", format=fmt).headers["content-disposition"]
    plain = export_draft(web, untitled, chart="donut", format=fmt).headers["content-disposition"]
    assert donut == (
        f"attachment; filename=\"Q3_Budget-donut.{fmt}\"; filename*=UTF-8''Q3%20Budget-donut.{fmt}"
    )
    assert plain == disposition("graph-donut", fmt)


class Title(NamedTuple):
    title: str
    stem: str
    encoded: str


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize(
    "case",
    [
        Title("Q3 Budget", "Q3_Budget", "Q3%20Budget"),
        Title("a/b; c", "a_b_c", "a%2Fb%3B%20c"),
        Title("grafico é", "grafico_", "grafico%20%C3%A9"),
    ],
    ids=lambda case: stable_id(case.title),
)
def test_the_title_of_the_style_names_the_file(web: WebApp, case: Title) -> None:
    draft = draft_json(*BUDGET, style={"title": case.title})
    value = export_draft(web, draft, format="json").headers["content-disposition"]
    assert (
        value == f"attachment; filename=\"{case.stem}.json\"; filename*=UTF-8''{case.encoded}.json"
    )


@pytest.mark.usefixtures("render")
def test_the_title_is_also_the_html_title(web: WebApp) -> None:
    draft = draft_json(*BUDGET, style={"title": "A <b> & B"})
    page = export_draft(web, draft, format="html").text
    assert "<title>A &lt;b&gt; &amp; B</title>" in page


@pytest.mark.usefixtures("render")
def test_a_draft_without_a_title_has_the_title_graph(web: WebApp) -> None:
    assert "<title>graph</title>" in export_draft(web, draft_json(*BUDGET), format="html").text


def test_a_draft_image_goes_through_the_chrome_seam(web: WebApp, render: FakeRender) -> None:
    response = export_draft(web, draft_json(*BUDGET), format="png", width=800, height=600, scale=3)
    assert response.content == IMAGES["png"]
    figure, resolved = render.calls[0]
    assert (resolved.fmt, resolved.width, resolved.height, resolved.scale) == ("png", 800, 600, 3.0)
    assert figure["data"][0]["type"] == "sankey"


def test_a_draft_donut_without_categories_is_a_422(web: WebApp, render: FakeRender) -> None:
    response = export_draft(web, draft_json(*PLAIN), chart="donut", format="svg")
    assert response.status_code == 422
    assert code(response) == "no_categories"
    assert render.calls == []


@pytest.mark.usefixtures("render")
def test_the_csv_of_a_draft_follows_its_transform(web: WebApp) -> None:
    draft = draft_json(*BUDGET, transform={"min_link_value": 1000})
    lines = export_draft(web, draft, format="csv").text.splitlines()
    assert lines[0] == "source,target,value,category"
    assert len(lines) == 4  # the header and the three flows of 1000 or more


@pytest.mark.usefixtures("render")
def test_an_export_saves_nothing(web: WebApp) -> None:
    export_draft(web, draft_json(*BUDGET), format="json")
    assert web.services.graphs().count() == 0


@pytest.mark.usefixtures("render")
def test_a_draft_export_builds_the_graph_through_the_app_cache(web: WebApp) -> None:
    cache = web.app.state.result_cache
    assert cache.size == 0
    for fmt in ("csv", "json"):
        export_draft(web, draft_json(*BUDGET), format=fmt)
        assert cache.size == 1


class Figure(NamedTuple):
    label: str
    body: dict[str, Any]
    detail: str


FIGURES = [
    Figure(
        "a figure",
        {"data": [], "layout": {"images": [{"source": "http://169.254.169.254/"}]}},
        "body.source: Field required",
    ),
    Figure(
        "a figure next to a draft",
        {**draft_json(*PLAIN), "figure": {"layout": {"images": [{"source": "http://x.test/"}]}}},
        "body.figure: Extra inputs are not permitted",
    ),
    Figure(
        "a layout next to a draft",
        {**draft_json(*PLAIN), "layout": {}},
        "body.layout: Extra inputs are not permitted",
    ),
]


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("case", FIGURES, ids=lambda case: case.label)
def test_no_endpoint_takes_a_figure(
    web: WebApp, render: FakeRender, case: Figure, fmt: str
) -> None:
    response = export_draft(web, case.body, format=fmt)
    assert response.status_code == 422
    assert code(response) == "validation_error"
    assert case.detail in response.json()["error"]["details"]
    assert "169.254" not in response.text
    assert render.calls == []


def test_the_saved_export_has_no_body_either(web: WebApp) -> None:
    # a GET route reads its parameters from the query only: a body is ignored, never a figure
    response = web.client.request(
        "GET", f"{API}/graphs/{'0' * 32}/export", json={"data": [], "layout": {}}
    )
    assert response.status_code == 404


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("fmt", FORMATS)
def test_a_draft_export_stays_available_in_read_only_remote_mode(
    make_app: AppFactory, fmt: str
) -> None:
    web = make_app([exports.router], mode="remote_read_only")
    assert export_draft(web, draft_json(*BUDGET), format=fmt).status_code == 200


def test_a_failing_source_keeps_its_status(web: WebApp) -> None:
    source = {"type": "text", "origin": "file", "path": "gone.csv"}
    response = export_draft(web, {"source": source}, format="csv")
    assert response.status_code == 404
    assert code(response) == "source_not_found"


def test_a_draft_that_cannot_be_drawn_is_a_422(web: WebApp) -> None:
    cycle = draft_json(("a", "b", 1.0, None), ("b", "a", 1.0, None))
    response = export_draft(web, cycle, format="json")
    assert response.status_code == 422
    assert code(response) == "graph_build_error"


@pytest.mark.parametrize(
    "params",
    [
        {"chart": "pie"},
        {"format": "pdf"},
        {"format": "SVG"},
        {"theme": "sepia"},
        {"width": 0},
        {"width": 100001},
        {"height": 0},
        {"height": 100001},
        {"scale": 0},
        {"scale": -1},
        {"scale": 100.5},
        {"scale": "nan"},
        {"scale": "inf"},
        {"transparent": "maybe"},
        {"extra": 1},
    ],
    ids=str,
)
def test_a_bad_export_query_is_a_422(
    web: WebApp, render: FakeRender, params: dict[str, Any]
) -> None:
    response = export_draft(web, draft_json(*BUDGET), **params)
    assert response.status_code == 422
    assert code(response) == "validation_error"
    assert render.calls == []


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize(
    "params",
    [{"width": 1}, {"width": 100000}, {"height": 1}, {"height": 100000}, {"scale": 100}],
    ids=str,
)
def test_absurd_but_sane_sizes_are_clamped_not_refused(web: WebApp, params: dict[str, Any]) -> None:
    assert export_draft(web, draft_json(*BUDGET), format="svg", **params).status_code == 200


@pytest.mark.usefixtures("render")
def test_the_json_export_of_a_draft_is_the_figure(web: WebApp) -> None:
    figure = json.loads(export_draft(web, draft_json(*BUDGET), format="json").text)
    assert figure["data"][0]["type"] == "sankey"
