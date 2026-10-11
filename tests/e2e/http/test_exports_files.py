"""E2E A.4 (exports without Chrome): file names, headers, formats and refusals of the routes."""

from __future__ import annotations

import csv
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.http_a_exports import (
    assert_download,
    export,
    export_draft,
    parse_disposition,
)

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer

HOSTILE = 'a"b\r\nX: y'
LONG = "x" * 120


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: every graph here has its own name."""
    return module_server


@dataclass(frozen=True, slots=True)
class NameCase:
    """A graph name and the file stem the ASCII fallback and the UTF-8 name must have."""

    name: str
    fallback: str
    utf8: str
    donut_fallback: str
    donut_utf8: str


NAMES = [
    pytest.param(
        NameCase(
            "Household budget",
            "Household_budget",
            "Household budget",
            "Household_budget-donut",
            "Household budget-donut",
        ),
        id="plain",
    ),
    pytest.param(
        NameCase(HOSTILE, "a_b_X_y", HOSTILE, "a_b_X_y-donut", f"{HOSTILE}-donut"),
        id="quote-and-header-injection",
    ),
    pytest.param(
        NameCase(
            "Smoke éü ☃",
            "Smoke_",
            "Smoke éü ☃",
            "Smoke_-donut",
            "Smoke éü ☃-donut",
        ),
        id="unicode",
    ),
    pytest.param(
        NameCase(LONG, "x" * 80, "x" * 80, "x" * 74 + "-donut", "x" * 74 + "-donut"),
        id="longer-than-80",
    ),
]


@pytest.mark.parametrize("fmt", ["csv", "json", "html"])
@pytest.mark.parametrize("case", NAMES)
def test_the_donut_files_add_a_suffix_and_the_sankey_files_keep_the_name(
    api: httpx.Client, case: NameCase, fmt: str
) -> None:
    graph = seed_graph(api, case.name, graph_draft(BUDGET_CATEGORISED.csv))
    sankey = export(api, graph["id"], format=fmt)
    donut = export(api, graph["id"], format=fmt, chart="donut")
    for answer in (sankey, donut):
        assert_download(answer, fmt)
        assert "\r" not in answer.headers["content-disposition"]
        assert "\n" not in answer.headers["content-disposition"]
    assert "x" not in {name.lower() for name in sankey.headers}  # no injected "X: y" header
    plain, suffixed = parse_disposition(sankey), parse_disposition(donut)
    assert plain.fallback == f"{case.fallback}.{fmt}"
    assert plain.utf8 == f"{case.utf8}.{fmt}"
    assert suffixed.fallback == f"{case.donut_fallback}.{fmt}"
    assert suffixed.utf8 == f"{case.donut_utf8}.{fmt}"
    assert plain.fallback != suffixed.fallback  # the two charts never share a file name


def test_the_encoded_name_is_percent_encoded_only(api: httpx.Client) -> None:
    graph = seed_graph(api, "Q1 / Q2 ü", graph_draft(BUDGET.csv))
    answer = export(api, graph["id"], format="csv")
    disposition = parse_disposition(answer)
    assert disposition.encoded == "Q1%20%2F%20Q2%20%C3%BC.csv"
    assert disposition.fallback == "Q1_Q2_.csv"
    assert urllib.parse.quote(disposition.utf8, safe="") == disposition.encoded


@pytest.mark.parametrize("fmt", ["csv", "json", "html"])
def test_a_draft_is_named_after_its_title_or_graph(api: httpx.Client, fmt: str) -> None:
    titled = graph_draft(BUDGET_CATEGORISED.csv, style={"title": "Draft title"})
    untitled = graph_draft(BUDGET_CATEGORISED.csv)
    names = {
        (label, chart): parse_disposition(export_draft(api, draft, format=fmt, chart=chart)).utf8
        for label, draft in (("title", titled), ("none", untitled))
        for chart in ("sankey", "donut")
    }
    assert names == {
        ("title", "sankey"): f"Draft title.{fmt}",
        ("title", "donut"): f"Draft title-donut.{fmt}",
        ("none", "sankey"): f"graph.{fmt}",
        ("none", "donut"): f"graph-donut.{fmt}",
    }


def test_the_html_title_stays_the_graph_name_for_both_charts(api: httpx.Client) -> None:
    name = unique_name("Title check")
    graph = seed_graph(api, name, graph_draft(BUDGET_CATEGORISED.csv))
    for chart in ("sankey", "donut"):
        page = export(api, graph["id"], format="html", chart=chart)
        assert f"<title>{name}</title>" in page.text


def test_the_sankey_csv_lists_every_link(api: httpx.Client) -> None:
    graph = seed_graph(api, unique_name("Csv"), graph_draft(BUDGET_CATEGORISED.csv))
    answer = export(api, graph["id"], format="csv")
    assert_download(answer, "csv")
    rows = list(csv.reader(answer.text.splitlines()))
    assert rows[0] == ["source", "target", "value", "category"]
    assert len(rows) - 1 == BUDGET_CATEGORISED.links
    assert ["Budget", "Rent", "1200.0", "Housing"] in rows
    assert sum(float(row[2]) for row in rows[1:]) == 8240.0


def test_the_donut_csv_is_category_value_share(api: httpx.Client) -> None:
    graph = seed_graph(api, unique_name("Donut csv"), graph_draft(BUDGET_CATEGORISED.csv))
    rows = list(csv.reader(export(api, graph["id"], format="csv", chart="donut").text.splitlines()))
    assert rows[0] == ["category", "value", "share"]
    values = {row[0]: float(row[1]) for row in rows[1:]}
    assert values == pytest.approx(dict(BUDGET_CATEGORISED.categories))
    assert sum(float(row[2]) for row in rows[1:]) == pytest.approx(1.0)


@pytest.mark.parametrize(("chart", "trace"), [("sankey", "sankey"), ("donut", "pie")])
def test_the_json_export_is_the_figure_of_the_chart(
    api: httpx.Client, chart: str, trace: str
) -> None:
    graph = seed_graph(api, unique_name("Json"), graph_draft(BUDGET_CATEGORISED.csv))
    light = export(api, graph["id"], format="json", chart=chart)
    dark = export(api, graph["id"], format="json", chart=chart, theme="dark")
    assert_download(light, "json")
    assert light.json()["data"][0]["type"] == trace
    assert light.json()["layout"]["paper_bgcolor"] != dark.json()["layout"]["paper_bgcolor"]


REFUSED = [
    pytest.param({"width": 0}, "query.width", id="width-0"),
    pytest.param({"width": 100_001}, "query.width", id="width-too-big"),
    pytest.param({"height": 0}, "query.height", id="height-0"),
    pytest.param({"scale": 0}, "query.scale", id="scale-0"),
    pytest.param({"scale": 101}, "query.scale", id="scale-101"),
    pytest.param({"chart": "pie"}, "query.chart", id="chart"),
    pytest.param({"format": "pdf"}, "query.format", id="format"),
    pytest.param({"theme": "blue"}, "query.theme", id="theme"),
    pytest.param({"transparent": "maybe"}, "query.transparent", id="transparent"),
    pytest.param({"_": "123"}, "query._", id="unknown-parameter"),
]


@pytest.mark.parametrize(("params", "where"), REFUSED)
def test_a_bad_export_query_is_a_422_naming_the_parameter(
    api: httpx.Client, params: dict[str, Any], where: str
) -> None:
    graph = seed_graph(api, unique_name("Bad query"))
    error = json_of(export(api, graph["id"], **params), 422)["error"]
    assert error["code"] == "validation_error"
    assert any(line.startswith(where) for line in error["details"]), error["details"]
    again = export_draft(api, graph_draft(), **params)
    assert again.status_code == 422


@pytest.mark.parametrize("fmt", ["svg", "png"])
def test_an_oversize_image_is_refused_before_any_browser_starts(
    api: httpx.Client, fmt: str
) -> None:
    graph = seed_graph(api, unique_name("Oversize"))
    answer = export(api, graph["id"], format=fmt, width=20_000, height=20_000)
    error = json_of(answer, 422)["error"]
    assert error["code"] == "export_too_large"
    assert "36,000,000" in error["message"]
    assert "content-disposition" not in answer.headers


def test_exports_of_unknown_graphs_are_404(api: httpx.Client) -> None:
    for graph_id in ("0" * 32, "not-an-id"):
        answer = export(api, graph_id, format="csv")
        assert json_of(answer, 404)["error"]["code"] == "not_found"


def test_a_draft_that_is_not_valid_is_a_422_and_a_cycle_is_a_build_error(
    api: httpx.Client,
) -> None:
    assert export_draft(api, {"transform": {}}, format="csv").status_code == 422
    cycle = graph_draft("source,target,value\nA,B,1\nB,A,1\n")
    error = json_of(export_draft(api, cycle, format="csv"), 422)["error"]
    assert error["code"] == "graph_build_error"
    assert "cycle" in error["message"]
