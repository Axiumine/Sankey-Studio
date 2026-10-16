# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""GET /api/v1/graphs/{id}/export: both charts in every format, as attachments."""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.models import AppSettings, GraphCreate
from sankey_studio.render.palette import TOKENS
from sankey_studio.web.routers import exports
from tests.web.test_routes_exports_support import (
    IMAGES,
    MEDIA,
    FakeRender,
    disposition,
    export_saved,
    install_render,
)
from tests.web.test_routes_graphs_support import (
    BUDGET,
    MALFORMED_IDS,
    PLAIN,
    UNKNOWN_ID,
    code,
    save,
    save_csv,
)

if TYPE_CHECKING:
    from sankey_studio.models import GraphDefinition, Theme
    from tests.web.conftest import AppFactory, WebApp

FORMATS = ["svg", "png", "html", "json", "csv"]


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([exports.router])


@pytest.fixture
def render(monkeypatch: pytest.MonkeyPatch) -> FakeRender:
    return install_render(monkeypatch)


@pytest.fixture
def stored(web: WebApp) -> GraphDefinition:
    return save(web, "Household", *BUDGET)


class Combo(NamedTuple):
    chart: str
    fmt: str


COMBOS = [Combo(chart, fmt) for chart in ("sankey", "donut") for fmt in FORMATS]


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("case", COMBOS, ids=lambda case: f"{case.chart}-{case.fmt}")
def test_every_export_is_a_sandboxed_attachment(
    web: WebApp, stored: GraphDefinition, case: Combo
) -> None:
    response = export_saved(web, stored.id, chart=case.chart, format=case.fmt)
    assert response.status_code == 200
    assert response.headers["content-type"] == MEDIA[case.fmt]
    stem = "Household-donut" if case.chart == "donut" else "Household"
    assert response.headers["content-disposition"] == disposition(stem, case.fmt)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers.get_list("content-security-policy") == ["sandbox"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("fmt", FORMATS)
def test_the_two_charts_of_a_graph_never_share_a_file_name(
    web: WebApp, stored: GraphDefinition, fmt: str
) -> None:
    names = {
        chart: export_saved(web, stored.id, chart=chart, format=fmt).headers["content-disposition"]
        for chart in ("sankey", "donut")
    }
    assert (
        names["sankey"]
        == f"attachment; filename=\"Household.{fmt}\"; filename*=UTF-8''Household.{fmt}"
    )
    assert names["donut"] == (
        f"attachment; filename=\"Household-donut.{fmt}\"; filename*=UTF-8''Household-donut.{fmt}"
    )
    assert names["sankey"] != names["donut"]


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("fmt", FORMATS)
def test_the_defaults_name_the_sankey_file(web: WebApp, stored: GraphDefinition, fmt: str) -> None:
    response = export_saved(web, stored.id, format=fmt)
    assert response.headers["content-disposition"] == disposition("Household", fmt)


@pytest.mark.usefixtures("render")
class TestDonutFileNames:
    """The suffix goes after the sanitising: unsafe characters, non-ASCII text, long names."""

    def test_unsafe_and_non_ascii_names_keep_the_suffix(self, web: WebApp) -> None:
        stored = save(web, 'grafico é "a/b"; c', *BUDGET)
        value = export_saved(web, stored.id, chart="donut", format="json").headers[
            "content-disposition"
        ]
        assert value == (
            'attachment; filename="grafico_a_b_c-donut.json"; '
            "filename*=UTF-8''grafico%20%C3%A9%20%22a%2Fb%22%3B%20c-donut.json"
        )

    @pytest.mark.parametrize("length", [1, 73, 74, 75, 80, 200])
    def test_a_long_name_is_cut_before_the_suffix_is_added(self, web: WebApp, length: int) -> None:
        stored = save(web, "n" * length, *BUDGET)
        sankey = export_saved(web, stored.id, format="csv").headers["content-disposition"]
        donut = export_saved(web, stored.id, chart="donut", format="csv").headers[
            "content-disposition"
        ]
        stem = "n" * min(length, 80)
        assert sankey == disposition(stem, "csv")
        assert donut == disposition("n" * min(length, 74) + "-donut", "csv")
        assert len(donut.split('"')[1]) <= 80 + len(".csv")

    def test_the_html_title_is_the_graph_name_without_the_suffix(self, web: WebApp) -> None:
        stored = save(web, "Household", *BUDGET)
        page = export_saved(web, stored.id, chart="donut", format="html").text
        assert "<title>Household</title>" in page


@pytest.mark.usefixtures("render")
def test_the_defaults_are_a_sankey_svg(web: WebApp, stored: GraphDefinition) -> None:
    response = export_saved(web, stored.id)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.content == IMAGES["svg"]


@pytest.mark.parametrize("fmt", ["svg", "png"])
def test_images_come_from_the_chrome_seam(
    web: WebApp, stored: GraphDefinition, render: FakeRender, fmt: str
) -> None:
    response = export_saved(web, stored.id, format=fmt)
    assert response.content == IMAGES[fmt]
    (figure, resolved), *rest = render.calls
    assert not rest
    assert resolved.fmt == fmt
    assert figure["data"][0]["type"] == "sankey"


def test_the_donut_image_is_a_pie(web: WebApp, stored: GraphDefinition, render: FakeRender) -> None:
    export_saved(web, stored.id, chart="donut", format="png")
    assert [trace["type"] for trace in render.calls[0][0]["data"]] == ["pie"]


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize(("chart", "trace"), [("sankey", "sankey"), ("donut", "pie")])
def test_the_json_export_is_the_figure(
    web: WebApp, stored: GraphDefinition, chart: str, trace: str
) -> None:
    figure = export_saved(web, stored.id, chart=chart, format="json").json()
    assert set(figure) == {"data", "layout"}
    assert figure["data"][0]["type"] == trace


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("chart", ["sankey", "donut"])
def test_the_html_export_is_a_standalone_page(
    web: WebApp, stored: GraphDefinition, chart: str
) -> None:
    page = export_saved(web, stored.id, chart=chart, format="html").text
    assert page.startswith("<!DOCTYPE html>")
    assert "<title>Household</title>" in page
    assert "Plotly.newPlot" in page


@pytest.mark.usefixtures("render")
def test_the_html_title_is_escaped(web: WebApp) -> None:
    named = save(web, "<script>alert(1)</script>", *BUDGET)
    page = export_saved(web, named.id, format="html").text
    assert "<title>&lt;script&gt;alert(1)&lt;/script&gt;</title>" in page


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("chart", ["sankey", "donut"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_theme_reaches_every_figure_format(
    web: WebApp, stored: GraphDefinition, chart: str, theme: Theme
) -> None:
    surface = TOKENS[theme].surface
    figure = export_saved(web, stored.id, chart=chart, format="json", theme=theme).json()
    assert figure["layout"]["paper_bgcolor"] == surface
    page = export_saved(web, stored.id, chart=chart, format="html", theme=theme).text
    assert f"margin: 0; background: {surface}; color: {TOKENS[theme].ink};" in page


@pytest.mark.usefixtures("render")
def test_an_export_builds_the_graph_through_the_app_cache(
    web: WebApp, stored: GraphDefinition
) -> None:
    cache = web.app.state.result_cache
    for fmt in ("csv", "json"):
        export_saved(web, stored.id, format=fmt)
        assert cache.size == 1


def rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


@pytest.mark.usefixtures("render")
def test_the_sankey_csv_lists_every_link(web: WebApp, stored: GraphDefinition) -> None:
    text = export_saved(web, stored.id, format="csv").text
    assert rows(text) == [
        ["source", "target", "value", "category"],
        ["Salary", "Budget", "3000.0", "Income"],
        ["Freelance", "Budget", "1000.0", "Income"],
        ["Budget", "Rent", "1200.0", "Housing"],
        ["Budget", "Food", "600.0", ""],
    ]


@pytest.mark.usefixtures("render")
def test_the_donut_csv_lists_the_slices(web: WebApp, stored: GraphDefinition) -> None:
    text = export_saved(web, stored.id, chart="donut", format="csv").text
    table = rows(text)
    assert table[0] == ["category", "value", "share"]
    assert [row[:2] for row in table[1:]] == [
        ["Income", "4000.0"],
        ["Housing", "1200.0"],
        ["Uncategorized", "600.0"],
    ]


class Basis(NamedTuple):
    basis: str
    slices: list[str]


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize(
    "case",
    [
        Basis("all", ["Income", "Housing", "Uncategorized"]),
        Basis("initial", ["Income"]),
        Basis("terminal", ["Housing", "Uncategorized"]),
    ],
    ids=lambda case: case.basis,
)
def test_the_donut_csv_follows_the_basis_of_the_style(web: WebApp, case: Basis) -> None:
    named = save(web, "Basis", *BUDGET, style={"donut": {"basis": case.basis}})
    text = export_saved(web, named.id, chart="donut", format="csv").text
    assert [row[0] for row in rows(text)[1:]] == case.slices


@pytest.mark.usefixtures("render")
def test_the_csv_neutralises_spreadsheet_formulas(web: WebApp) -> None:
    named = save(web, "Formulas", ("=cmd|calc", "+1", 5.0, "@SUM"), ("-2", "x", 1.0, None))
    table = rows(export_saved(web, named.id, format="csv").text)
    assert table[1] == ["'=cmd|calc", "'+1", "5.0", "'@SUM"]
    assert table[2][0] == "'-2"


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("fmt", FORMATS)
def test_a_donut_of_a_graph_without_categories_is_a_422(web: WebApp, fmt: str) -> None:
    plain = save(web, "Plain", *PLAIN)
    response = export_saved(web, plain.id, chart="donut", format=fmt)
    assert response.status_code == 422
    assert code(response) == "no_categories"
    assert "content-disposition" not in response.headers


def test_a_sankey_of_a_graph_without_categories_exports_fine(
    web: WebApp, render: FakeRender
) -> None:
    plain = save(web, "Plain", *PLAIN)
    assert export_saved(web, plain.id, format="png").content == IMAGES["png"]
    assert len(render.calls) == 1


def test_the_figure_is_capped_like_the_page_but_the_csv_is_not(make_app: AppFactory) -> None:
    web = make_app([exports.router], settings=AppSettings(max_drawn_links=50))
    big = save_csv(web, "Big", 60)
    figure = export_saved(web, big.id, format="json").json()
    assert len(figure["data"][0]["link"]["value"]) == 50
    assert len(rows(export_saved(web, big.id, format="csv").text)) == 61


def test_an_unknown_graph_is_a_404(web: WebApp) -> None:
    response = export_saved(web, UNKNOWN_ID, format="json")
    assert response.status_code == 404
    assert code(response) == "not_found"


@pytest.mark.parametrize("graph_id", MALFORMED_IDS)
def test_a_malformed_graph_id_is_a_404(web: WebApp, graph_id: str) -> None:
    response = export_saved(web, graph_id, format="json")
    assert response.status_code == 404
    assert code(response) == "not_found"


def test_a_graph_whose_file_is_gone_is_a_404_source_not_found(web: WebApp) -> None:
    gone = web.services.graphs().create(
        GraphCreate.model_validate(
            {"name": "Gone", "source": {"type": "text", "origin": "file", "path": "gone.csv"}}
        )
    )
    response = export_saved(web, gone.id, format="csv")
    assert response.status_code == 404
    assert code(response) == "source_not_found"


@pytest.mark.usefixtures("render")
def test_exports_stay_available_in_read_only_remote_mode(make_app: AppFactory) -> None:
    web = make_app([exports.router], mode="remote_read_only")
    named = save(web, "Household", *BUDGET)
    for fmt in FORMATS:
        assert export_saved(web, named.id, format=fmt).status_code == 200
