# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Exports with the label switches: GET /graphs/{id}/export and POST /export (CSV ignores them)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.render.sankey import LABEL_BREAK
from sankey_studio.web.routers import exports
from tests.web.test_routes_exports_support import (
    FakeRender,
    export_draft,
    export_saved,
    install_render,
)
from tests.web.test_routes_graphs_support import BUDGET, PLAIN, code, draft_json, save

if TYPE_CHECKING:
    from httpx2 import Response

    from sankey_studio.models import GraphDefinition
    from tests.web.conftest import AppFactory, WebApp

ALL_ON = {"node_values": "true", "donut_percent": "true", "donut_value": "true"}
SAVED_ON = {"show_values_in_labels": True, "donut": {"show_percent": True, "show_value": True}}


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([exports.router])


@pytest.fixture
def render(monkeypatch: pytest.MonkeyPatch) -> FakeRender:
    return install_render(monkeypatch)


@pytest.fixture
def stored(web: WebApp) -> GraphDefinition:
    return save(web, "Household", *BUDGET)


def labels(figure: dict[str, Any]) -> list[str]:
    found: list[str] = figure["data"][0]["node"]["label"]
    return found


def pie(figure: dict[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = figure["data"][0]
    assert trace["type"] == "pie"
    return trace


def figure_of(response: Response) -> dict[str, Any]:
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_the_sankey_json_export_draws_node_values(web: WebApp, stored: GraphDefinition) -> None:
    off = labels(figure_of(export_saved(web, stored.id, format="json")))
    on = labels(figure_of(export_saved(web, stored.id, format="json", node_values="true")))
    assert "Salary" in off
    assert "Salary" + LABEL_BREAK + "3,000" in on
    assert not any(LABEL_BREAK in label for label in off)
    assert all(label.count(LABEL_BREAK) == 1 for label in on)


class Donut(NamedTuple):
    query: dict[str, str]
    info: str
    text: list[str] | None


DONUTS = [
    Donut({}, "label+percent", None),
    Donut({"donut_percent": "false"}, "label", None),
    Donut({"donut_value": "true"}, "label+text+percent", ["4,000", "1,200", "600"]),
    Donut(
        {"donut_value": "true", "donut_percent": "false"}, "label+text", ["4,000", "1,200", "600"]
    ),
]


@pytest.mark.parametrize("case", DONUTS, ids=lambda case: repr(case.query))
def test_the_donut_json_export_draws_the_donut_switches(
    web: WebApp, stored: GraphDefinition, case: Donut
) -> None:
    response = export_saved(web, stored.id, chart="donut", format="json", **case.query)
    trace = pie(figure_of(response))
    assert trace["textinfo"] == case.info
    assert trace.get("text") == case.text


def test_a_donut_switch_does_not_touch_the_sankey_and_node_values_not_the_donut(
    web: WebApp, stored: GraphDefinition
) -> None:
    sankey_plain = export_saved(web, stored.id, format="json").json()
    sankey_donut = export_saved(web, stored.id, format="json", donut_value="true").json()
    assert sankey_donut == sankey_plain
    donut_plain = export_saved(web, stored.id, chart="donut", format="json").json()
    donut_nodes = export_saved(web, stored.id, chart="donut", format="json", node_values="true")
    assert donut_nodes.json() == donut_plain


@pytest.mark.parametrize("fmt", ["svg", "png"])
def test_the_image_exports_get_the_styled_figure(
    web: WebApp, stored: GraphDefinition, render: FakeRender, fmt: str
) -> None:
    export_saved(web, stored.id, format=fmt, node_values="true")
    export_saved(web, stored.id, chart="donut", format=fmt, donut_value="true")
    sankey_figure, donut_figure = render.calls[0][0], render.calls[1][0]
    assert "Salary" + LABEL_BREAK + "3,000" in labels(sankey_figure)
    assert pie(donut_figure)["text"] == ["4,000", "1,200", "600"]


#: What the styled figure adds to the page (plotly writes the less-than sign as a unicode escape).
HTML_NEEDLES = {
    "sankey": '"Salary\\u003cbr\\u003e3,000"',
    "donut": '"text":["4,000","1,200","600"]',
}


@pytest.mark.parametrize("chart", ["sankey", "donut"])
def test_the_html_export_embeds_the_styled_figure(
    web: WebApp, stored: GraphDefinition, chart: str
) -> None:
    plain = export_saved(web, stored.id, chart=chart, format="html").text
    styled = export_saved(web, stored.id, chart=chart, format="html", **ALL_ON).text
    assert HTML_NEEDLES[chart] in styled
    assert HTML_NEEDLES[chart] not in plain


def test_a_false_switch_overrides_a_saved_true(web: WebApp) -> None:
    graph = save(web, "On", *BUDGET, style=SAVED_ON)
    saved_sankey = labels(figure_of(export_saved(web, graph.id, format="json")))
    off = {"node_values": "false", "donut_value": "false", "donut_percent": "false"}
    sankey = labels(figure_of(export_saved(web, graph.id, format="json", **off)))
    donut = pie(figure_of(export_saved(web, graph.id, chart="donut", format="json", **off)))
    assert "Salary" + LABEL_BREAK + "3,000" in saved_sankey
    assert "Salary" in sankey
    assert not any(LABEL_BREAK in label for label in sankey)
    assert (donut["textinfo"], "text" in donut) == ("label", False)


def test_the_csv_export_ignores_the_switches(web: WebApp, stored: GraphDefinition) -> None:
    for chart in ("sankey", "donut"):
        plain = export_saved(web, stored.id, chart=chart, format="csv")
        styled = export_saved(web, stored.id, chart=chart, format="csv", **ALL_ON)
        assert styled.status_code == 200
        assert styled.text == plain.text


def test_exporting_with_switches_never_changes_the_saved_graph(
    web: WebApp, stored: GraphDefinition
) -> None:
    for chart in ("sankey", "donut"):
        export_saved(web, stored.id, chart=chart, format="json", **ALL_ON)
    again = web.services.graphs().get(stored.id)
    assert again == stored
    assert (again.revision, again.updated_at) == (stored.revision, stored.updated_at)
    assert again.style.show_values_in_labels is False
    assert again.style.donut.show_value is False


@pytest.mark.parametrize("chart", ["sankey", "donut"])
def test_post_export_honours_the_switches_over_the_style_of_the_draft(
    web: WebApp, chart: str
) -> None:
    draft = draft_json(*BUDGET, style={"title": "Q3"})
    plain = export_draft(web, draft, chart=chart, format="json").json()
    styled = export_draft(web, draft, chart=chart, format="json", **ALL_ON).json()
    assert styled != plain
    if chart == "sankey":
        assert "Salary" + LABEL_BREAK + "3,000" in labels(styled)
    else:
        assert pie(styled)["text"] == ["4,000", "1,200", "600"]


def test_post_export_lets_a_false_switch_override_the_draft_style(web: WebApp) -> None:
    draft = draft_json(*BUDGET, style=SAVED_ON)
    kept = labels(figure_of(export_draft(web, draft, format="json")))
    off = labels(figure_of(export_draft(web, draft, format="json", node_values="false")))
    assert "Salary" + LABEL_BREAK + "3,000" in kept
    assert "Salary" in off


@pytest.mark.usefixtures("render")
def test_post_export_images_and_csv_take_the_switches_too(web: WebApp) -> None:
    draft = draft_json(*BUDGET)
    assert export_draft(web, draft, format="svg", node_values="true").status_code == 200
    plain = export_draft(web, draft, chart="donut", format="csv")
    styled = export_draft(web, draft, chart="donut", format="csv", **ALL_ON)
    assert styled.text == plain.text


@pytest.mark.parametrize(
    "query",
    [{"node_values": "maybe"}, {"donut_percent": "2"}, {"donut_value": ""}, {"donut_label": "1"}],
)
def test_a_bad_switch_is_a_422_on_both_routes(
    web: WebApp, stored: GraphDefinition, query: dict[str, str]
) -> None:
    saved = export_saved(web, stored.id, format="json", **query)
    posted = export_draft(web, draft_json(*PLAIN), format="json", **query)
    for response in (saved, posted):
        assert response.status_code == 422
        assert code(response) == "validation_error"
