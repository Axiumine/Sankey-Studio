# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""GET /api/v1/graphs/{id}/render with the label switches: drawn differently, saved unchanged."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.models import GraphDraft, StyleSpec
from sankey_studio.pipeline import BundleOptions, render_bundle
from sankey_studio.render.sankey import LABEL_BREAK
from sankey_studio.web.routers import graphs
from tests.web.test_routes_graphs_support import API, BUDGET, PLAIN, Link, code, save

if TYPE_CHECKING:
    from httpx2 import Response

    from sankey_studio.models import GraphDefinition
    from tests.web.conftest import AppFactory, WebApp

#: Six categories on one source: more slices than the donut writes a name on.
MANY: tuple[Link, ...] = tuple(("src", f"t{i}", 100.0 - i, f"cat{i}") for i in range(6))


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


def render(web: WebApp, graph_id: str, **params: Any) -> Response:
    return web.client.get(f"{API}/graphs/{graph_id}/render", params=params)


def node_labels(response: Response) -> dict[str, str]:
    """Node label by node name (the part before the line break)."""
    labels = response.json()["figure"]["data"][0]["node"]["label"]
    return {label.split(LABEL_BREAK)[0]: label for label in labels}


def pie(response: Response) -> dict[str, Any]:
    trace: dict[str, Any] = response.json()["donut"]["data"][0]
    return trace


def test_node_values_puts_the_value_on_a_line_under_the_name(web: WebApp) -> None:
    stored = save(web, "Household", *BUDGET)
    off = node_labels(render(web, stored.id))
    on = node_labels(render(web, stored.id, node_values="true"))
    assert off["Salary"] == "Salary"
    assert on["Salary"] == "Salary<br>3,000"
    assert on["Budget"] == "Budget<br>4,000"
    assert on["Rent"] == "Rent<br>1,200"
    assert set(on) == set(off)


def test_node_values_follows_the_value_format_and_the_suffix_of_the_style(web: WebApp) -> None:
    look = {"value_format": ",.1f", "value_suffix": "USD"}
    stored = save(web, "Household", *BUDGET, style=look)
    labels = node_labels(render(web, stored.id, node_values="true"))
    assert labels["Salary"] == "Salary<br>3,000.0 USD"


class Donut(NamedTuple):
    query: dict[str, str]
    info: str
    text: list[str] | None


DONUTS = [
    Donut({}, "label+percent", None),
    Donut({"donut_percent": "true"}, "label+percent", None),
    Donut({"donut_percent": "false"}, "label", None),
    Donut({"donut_value": "false"}, "label+percent", None),
    Donut({"donut_value": "true"}, "label+text+percent", ["4,000", "1,200", "600"]),
    Donut(
        {"donut_value": "true", "donut_percent": "false"}, "label+text", ["4,000", "1,200", "600"]
    ),
    Donut(
        {"donut_value": "true", "donut_percent": "true"},
        "label+text+percent",
        ["4,000", "1,200", "600"],
    ),
]


@pytest.mark.parametrize("case", DONUTS, ids=lambda case: repr(case.query))
def test_the_donut_switches_change_the_text_of_the_slices(web: WebApp, case: Donut) -> None:
    stored = save(web, "Household", *BUDGET)
    trace = pie(render(web, stored.id, **case.query))
    assert trace["textinfo"] == case.info
    assert trace.get("text") == case.text
    assert trace["textposition"] == "outside"


class Many(NamedTuple):
    query: dict[str, str]
    info: str
    position: str


MANY_SLICES = [
    Many({}, "percent", "auto"),
    Many({"donut_percent": "false"}, "none", "none"),
    Many({"donut_value": "true"}, "text+percent", "auto"),
    Many({"donut_value": "true", "donut_percent": "false"}, "text", "auto"),
]


@pytest.mark.parametrize("case", MANY_SLICES, ids=lambda case: repr(case.query))
def test_beyond_four_slices_the_name_stays_in_the_legend(web: WebApp, case: Many) -> None:
    stored = save(web, "Many", *MANY)
    trace = pie(render(web, stored.id, **case.query))
    assert len(trace["labels"]) == 6
    assert (trace["textinfo"], trace["textposition"]) == (case.info, case.position)


def test_a_false_switch_overrides_a_saved_true_and_no_switch_keeps_it(web: WebApp) -> None:
    saved = {"show_values_in_labels": True, "donut": {"show_value": True, "show_percent": True}}
    stored = save(web, "Household", *BUDGET, style=saved)
    kept = render(web, stored.id)
    assert node_labels(kept)["Salary"] == "Salary<br>3,000"
    assert pie(kept)["textinfo"] == "label+text+percent"
    off = render(web, stored.id, node_values="false", donut_value="false", donut_percent="false")
    assert node_labels(off)["Salary"] == "Salary"
    assert (pie(off)["textinfo"], "text" in pie(off)) == ("label", False)


def test_the_switches_apply_with_the_theme(web: WebApp) -> None:
    stored = save(web, "Household", *BUDGET)
    dark = render(web, stored.id, theme="dark", node_values="true", donut_value="true")
    light = render(web, stored.id, theme="light", node_values="true", donut_value="true")
    assert node_labels(dark) == node_labels(light)
    assert pie(dark)["text"] == pie(light)["text"]
    assert (
        dark.json()["figure"]["layout"]["paper_bgcolor"]
        != light.json()["figure"]["layout"]["paper_bgcolor"]
    )


def test_the_response_is_the_bundle_of_the_styled_draft(web: WebApp) -> None:
    stored = save(web, "Household", *BUDGET, style={"title": "Budget"})
    response = render(web, stored.id, node_values="true", donut_percent="false", donut_value="true")
    draft = GraphDraft(source=stored.source, transform=stored.transform, style=stored.style)
    chosen = StyleSpec.model_validate(
        {
            **stored.style.model_dump(),
            "show_values_in_labels": True,
            "donut": {**stored.style.donut.model_dump(), "show_percent": False, "show_value": True},
        }
    )
    expected = render_bundle(web.services, draft, BundleOptions("light", style=chosen))
    assert response.status_code == 200
    assert response.json() == expected.model_dump(mode="json")


def stored_json(web: WebApp, graph: GraphDefinition) -> dict[str, Any]:
    body: dict[str, Any] = web.client.get(f"{API}/graphs/{graph.id}").json()
    return body


def test_rendering_with_switches_never_changes_the_saved_graph(web: WebApp) -> None:
    stored = save(web, "Household", *BUDGET, style={"title": "Budget"})
    before = stored_json(web, stored)
    assert before["style"]["show_values_in_labels"] is False
    for query in ({"node_values": "true"}, {"donut_value": "true", "donut_percent": "false"}):
        assert render(web, stored.id, **query).status_code == 200
    after = stored_json(web, stored)
    assert after == before
    assert (after["revision"], after["updated_at"]) == (before["revision"], before["updated_at"])
    assert after["style"]["donut"]["show_value"] is False
    assert web.services.graphs().get(stored.id) == stored


def test_the_switches_do_not_change_the_graph_cache(web: WebApp) -> None:
    stored = save(web, "Household", *PLAIN)
    cache = web.app.state.result_cache
    for query in ({}, {"node_values": "true"}, {"node_values": "false"}, {"donut_value": "true"}):
        assert render(web, stored.id, **query).status_code == 200
        assert cache.size == 1


@pytest.mark.parametrize(
    "query",
    [
        {"node_values": "maybe"},
        {"donut_percent": "2"},
        {"donut_value": ""},
        {"donut_value": "true", "colour": "red"},
        {"theme": "sepia", "node_values": "true"},
    ],
)
def test_a_bad_switch_is_a_422(web: WebApp, query: dict[str, str]) -> None:
    stored = save(web, "Household", *PLAIN)
    response = render(web, stored.id, **query)
    assert response.status_code == 422
    assert code(response) == "validation_error"
