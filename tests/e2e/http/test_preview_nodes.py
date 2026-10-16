# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E: ``/preview`` lists the drawn nodes; a stored node order and extra links reach every view.

The order is part of the saved graph (``style.node_order``) and the extra links are part of its
transform: the preview, the saved graph's render, its exports and its CSV all use them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import BUDGET, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.http_a_exports import export, need_chrome
from tests.e2e.support.http_b_limits import API

if TYPE_CHECKING:
    import httpx

#: The nodes of the last column of the budget sample, in data order.
LAST_COLUMN = ["Groceries", "Restaurants"]
ORDER = ["Restaurants", "Groceries", "Savings", "Utilities"]
GIFT = {"source": "Budget", "target": "Gifts", "value": 250, "category": "Fun"}
NODE_IN_SVG = re.compile(
    r'<g class="sankey-node" transform="translate\(([\d.]+),([\d.-]+)\)".*?'
    r'class="node-label"[^>]*>([^<]*)</text>',
    re.DOTALL,
)


def preview(api: httpx.Client, **parts: Any) -> dict[str, Any]:
    bundle: dict[str, Any] = json_of(
        api.post(f"{API}/preview", json=graph_draft(BUDGET.csv, **parts))
    )
    return bundle


def labels(bundle: dict[str, Any]) -> list[str]:
    result: list[str] = bundle["figure"]["data"][0]["node"]["label"]
    return result


def test_the_preview_names_every_node_of_the_figure_in_figure_order(api: httpx.Client) -> None:
    bundle = preview(api)
    assert len(bundle["nodes"]) == bundle["stats"]["nodes"] == BUDGET.nodes
    assert [row["name"] for row in bundle["nodes"]] == labels(bundle)
    first = bundle["nodes"][0]
    assert set(first) == {"name", "layer", "node_in", "node_out"}
    assert first["layer"] == 0
    assert "sort" not in bundle["figure"]["data"][0]["node"]


def test_a_stored_order_sets_the_order_of_the_rows_and_the_figure(api: httpx.Client) -> None:
    bundle = preview(api, style={"node_order": ORDER})
    assert [row["name"] for row in bundle["nodes"]][: len(ORDER)] == ORDER
    assert labels(bundle)[: len(ORDER)] == ORDER
    assert bundle["figure"]["data"][0]["node"]["sort"] == "input"
    assert bundle["stats"]["nodes"] == BUDGET.nodes  # the same nodes, only the order moved


def test_a_stored_order_survives_save_render_and_the_json_export(api: httpx.Client) -> None:
    draft = graph_draft(BUDGET.csv, style={"node_order": ORDER})
    saved = seed_graph(api, unique_name("Ordered"), draft)
    assert saved["style"]["node_order"] == ORDER
    rendered = json_of(api.get(f"{API}/graphs/{saved['id']}/render"))
    assert labels(rendered)[: len(ORDER)] == ORDER
    assert rendered["nodes"] == []  # only the editor's preview asks for the rows
    figure = json_of(export(api, saved["id"], format="json"))
    assert figure["data"][0]["node"]["label"][: len(ORDER)] == ORDER
    assert figure["data"][0]["node"]["sort"] == "input"


def test_extra_links_are_drawn_saved_and_exported(api: httpx.Client) -> None:
    transform = {"extra_links": [GIFT]}
    bundle = preview(api, transform=transform)
    assert "Gifts" in [row["name"] for row in bundle["nodes"]]
    assert bundle["stats"]["links"] == BUDGET.links + 1
    assert "Fun" in bundle["category_names"]
    saved = seed_graph(api, unique_name("Gifts"), graph_draft(BUDGET.csv, transform=transform))
    rendered = json_of(api.get(f"{API}/graphs/{saved['id']}/render"))
    assert rendered["stats"]["links"] == BUDGET.links + 1
    csv_lines = export(api, saved["id"], format="csv").text.splitlines()
    assert "Budget,Gifts,250.0,Fun" in csv_lines


def test_the_entries_table_pages_over_the_extra_links_too(api: httpx.Client) -> None:
    body = graph_draft(BUDGET.csv, transform={"extra_links": [GIFT]})
    answer = json_of(api.post(f"{API}/entries", params={"q": "gifts"}, json=body))
    assert [(row["source"], row["target"]) for row in answer["rows"]] == [("Budget", "Gifts")]


def test_an_extra_link_that_closes_a_cycle_is_refused(api: httpx.Client) -> None:
    back = {"source": "Groceries", "target": "Salary", "value": 1}
    response = api.post(
        f"{API}/preview", json=graph_draft(BUDGET.csv, transform={"extra_links": [back]})
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "graph_build_error"


@pytest.mark.slow
def test_chrome_stacks_the_last_column_in_the_stored_order(api: httpx.Client) -> None:
    draft = graph_draft(BUDGET.csv, style={"node_order": ["Restaurants", "Groceries"]})
    answer = need_chrome(api.post(f"{API}/export", params={"format": "svg"}, json=draft))
    assert answer.status_code == 200
    found = NODE_IN_SVG.finditer(answer.text)
    top = {m.group(3): float(m.group(2)) for m in found}
    assert top["Restaurants"] < top["Groceries"]
    plain = need_chrome(
        api.post(f"{API}/export", params={"format": "svg"}, json=graph_draft(BUDGET.csv))
    )
    data_order = {m.group(3): float(m.group(2)) for m in NODE_IN_SVG.finditer(plain.text)}
    assert data_order["Groceries"] < data_order["Restaurants"]
