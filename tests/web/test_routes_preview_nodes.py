"""POST /api/v1/preview: the drawn nodes, a stored node order and graph-only extra links."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import AppSettings
from sankey_studio.render.text import escape_label
from sankey_studio.web.routers import compare, graphs, preview
from tests.web.test_routes_graphs_support import (
    API,
    BUDGET,
    PLAIN,
    draft_json,
    save,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from tests.web.conftest import AppFactory, WebApp

URL = f"{API}/preview"
ROW_KEYS = {"name", "layer", "node_in", "node_out"}
HOSTILE = ("<b>x</b>", "R&D", "evil\u202egnp", "n" * 40)
ORDER = ["Rent", "Food", "Salary"]


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([preview.router, graphs.router, compare.router])


def post(client: TestClient, body: dict[str, Any], query: str = "") -> dict[str, Any]:
    response = client.post(URL + query, json=body)
    assert response.status_code == 200
    bundle: dict[str, Any] = response.json()
    return bundle


def trace(bundle: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = bundle["figure"]["data"][0]
    return node


def names(bundle: dict[str, Any]) -> list[str]:
    return [row["name"] for row in bundle["nodes"]]


def test_the_preview_lists_every_drawn_node_with_its_layer_and_flows(client: TestClient) -> None:
    bundle = post(client, draft_json(*BUDGET))
    assert all(set(row) == ROW_KEYS for row in bundle["nodes"])
    assert names(bundle) == ["Salary", "Budget", "Freelance", "Rent", "Food"]
    assert bundle["nodes"][1] == {
        "name": "Budget",
        "layer": 1,
        "node_in": 4000.0,
        "node_out": 1800.0,
    }
    assert bundle["nodes"][0]["layer"] == 0


def test_the_rows_line_up_with_the_figure_labels_whatever_the_names(client: TestClient) -> None:
    links = [(HOSTILE[0], HOSTILE[1], 5.0, None), (HOSTILE[2], HOSTILE[3], 2.0, None)]
    bundle = post(client, draft_json(*links))
    assert names(bundle) == list(HOSTILE)  # raw, not escaped, not cut
    hover = [row[0] for row in trace(bundle)["node"]["customdata"]]
    assert [escape_label(name) for name in names(bundle)] == hover
    assert len(trace(bundle)["node"]["label"]) == len(bundle["nodes"])


def test_a_stored_order_arranges_the_rows_and_the_figure(client: TestClient) -> None:
    bundle = post(client, draft_json(*BUDGET, style={"node_order": ORDER}))
    assert names(bundle)[:3] == ORDER
    assert trace(bundle)["node"]["sort"] == "input"
    assert [row[0] for row in trace(bundle)["node"]["customdata"]] == names(bundle)


def test_without_a_stored_order_the_figure_keeps_the_automatic_sort(client: TestClient) -> None:
    bundle = post(client, draft_json(*BUDGET))
    assert "sort" not in trace(bundle)["node"]


def test_the_drawing_cap_limits_the_rows_to_the_drawn_nodes(web: WebApp) -> None:
    web.services.update_settings(AppSettings(max_drawn_links=50))
    links = [(f"s{i}", f"t{i}", float(i + 1), None) for i in range(60)]
    bundle = post(web.client, draft_json(*links))
    assert len(bundle["nodes"]) == 100
    assert len(trace(bundle)["node"]["label"]) == 100
    assert bundle["stats"]["nodes"] == 120  # the stats still count the whole graph


def test_extra_links_are_drawn_listed_and_counted(client: TestClient) -> None:
    extra = {"source": "Budget", "target": "Gifts", "value": 50, "category": "Fun"}
    draft = draft_json(("Budget", "Rent", 10.0, None), transform={"extra_links": [extra]})
    bundle = post(client, draft)
    assert names(bundle) == ["Budget", "Rent", "Gifts"]
    assert bundle["stats"]["links"] == 2
    assert bundle["category_names"] == ["Fun"]
    entries = [(row["source"], row["target"], row["value"]) for row in bundle["entries"]]
    assert ("Budget", "Gifts", 50.0) in entries


def test_the_entries_route_sees_the_extra_links_too(client: TestClient) -> None:
    extra = {"source": "a", "target": "z", "value": 7}
    response = client.post(
        f"{API}/entries", json=draft_json(*PLAIN, transform={"extra_links": [extra]})
    )
    assert response.status_code == 200
    assert response.json()["total"] == 3


def test_a_cycle_made_by_an_extra_link_is_a_422(client: TestClient) -> None:
    back = {"source": "c", "target": "a", "value": 1}
    response = client.post(URL, json=draft_json(*PLAIN, transform={"extra_links": [back]}))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "graph_build_error"


def test_the_write_back_preference_never_reaches_the_cache_key(web: WebApp) -> None:
    csv = "source,target,value\na,b,1\n"
    plain = {"type": "text", "origin": "inline", "content": csv}
    pref = {"mode": "graph", "target": "file:flows.csv"}
    post(web.client, {"source": plain})
    post(web.client, {"source": {**plain, "write_back": pref}})
    assert web.app.state.result_cache.size == 1


def test_a_stored_order_costs_a_redraw_not_a_new_load(web: WebApp) -> None:
    post(web.client, draft_json(*PLAIN))
    post(web.client, draft_json(*PLAIN, style={"node_order": ["c", "b", "a"]}))
    assert web.app.state.result_cache.size == 1


def test_a_saved_graph_render_carries_no_node_rows(web: WebApp) -> None:
    stored = save(web, "Household", *BUDGET)
    bundle = web.client.get(f"{API}/graphs/{stored.id}/render").json()
    assert bundle["nodes"] == []
    assert "sort" not in trace(bundle)["node"]


def test_a_saved_graph_keeps_its_stored_order_in_the_render(web: WebApp) -> None:
    stored = save(web, "Ordered", *BUDGET, style={"node_order": ORDER})
    bundle = web.client.get(f"{API}/graphs/{stored.id}/render").json()
    assert trace(bundle)["node"]["label"][:3] == ORDER
    assert bundle["nodes"] == []


def test_compare_bundles_carry_no_node_rows(web: WebApp) -> None:
    one, two = save(web, "One", *PLAIN), save(web, "Two", *BUDGET)
    bundles = web.client.get(f"{API}/compare/render?ids={one.id},{two.id}").json()
    assert [bundle["nodes"] for bundle in bundles] == [[], []]


def test_the_theme_does_not_change_the_node_rows(client: TestClient) -> None:
    light = post(client, draft_json(*BUDGET), "?theme=light")
    dark = post(client, draft_json(*BUDGET), "?theme=dark")
    assert light["nodes"] == dark["nodes"]
