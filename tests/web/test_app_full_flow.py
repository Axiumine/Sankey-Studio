# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The happy path through the API of the FULL app, with a text source.

create -> read -> render -> entries -> export svg (Chrome mocked), png, csv, json, html ->
compare -> update (and a stale update) -> duplicate -> bundle export and import -> delete. Every
step uses the same app, the same-origin client and the real pipeline; only Chrome is replaced.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest

from tests.web.test_routes_exports_support import IMAGES, FakeRender, disposition, install_render
from tests.web.test_routes_graphs_support import API, code

if TYPE_CHECKING:
    from httpx2 import Response

    from tests.web.conftest import WebApp

CSV: Final = (
    "source,target,value,category\n"
    "Salary,Budget,3000,Income\n"
    "Freelance,Budget,1000,Income\n"
    "Budget,Rent,1200,Housing\n"
    "Budget,Food,600,\n"
)
OTHER_CSV: Final = (
    "source,target,value,category\nSavings,Trips,500,Travel\nSavings,Rent,250,Housing\n"
)
JSON: Final = {"Content-Type": "application/json"}


def text_source(content: str) -> dict[str, Any]:
    return {"type": "text", "origin": "inline", "format": "csv", "content": content}


def create(web: WebApp, name: str, content: str) -> dict[str, Any]:
    body = {"name": name, "tags": ["home"], "source": text_source(content)}
    response = web.client.post(f"{API}/graphs", json=body)
    assert response.status_code == 201
    created: dict[str, Any] = response.json()
    assert created["name"] == name
    return created


def colours(bundle: dict[str, Any]) -> dict[str, str]:
    return {row["name"]: row["color"] for row in bundle["categories"]}


@pytest.fixture
def chrome(monkeypatch: pytest.MonkeyPatch) -> FakeRender:
    return install_render(monkeypatch)


def check_created(web: WebApp, created: dict[str, Any]) -> None:
    graph_id = created["id"]
    assert (created["revision"], created["tags"]) == (1, ["home"])
    assert web.client.get(f"{API}/graphs/{graph_id}").json() == created
    page = web.client.get(f"/graphs/{graph_id}")
    assert page.status_code == 200
    assert "<h1>Quarterly</h1>" in page.text
    listed = web.client.get(f"{API}/graphs").json()
    assert [g["id"] for g in listed["items"]] == [graph_id]
    assert (listed["total"], web.client.get(f"{API}/tags").json()) == (1, ["home"])


def check_render(web: WebApp, graph_id: str) -> None:
    response = web.client.get(f"{API}/graphs/{graph_id}/render", params={"theme": "dark"})
    bundle = response.json()
    assert response.status_code == 200
    assert bundle["stats"] == {
        "nodes": 5,
        "links": 4,
        "drawn_links": 4,
        "total_in": 4000.0,
        "total_out": 1800.0,
        "layers": 3,
        "category_count": 2,
    }
    assert bundle["donut_available"] is True
    assert bundle["category_names"] == ["Income", "Housing"]
    assert bundle["figure"]["data"][0]["type"] == "sankey"
    assert bundle["entries_total"] == len(bundle["entries"]) == 4
    assert bundle["warnings"] == []


def check_entries(web: WebApp, graph_id: str) -> None:
    draft = {"source": web.client.get(f"{API}/graphs/{graph_id}").json()["source"]}
    page = web.client.post(f"{API}/entries", params={"limit": 2, "sort": "value"}, json=draft)
    only = web.client.post(f"{API}/entries", params={"only_uncategorized": True}, json=draft)
    assert page.status_code == 200
    assert page.json()["total"] == 4
    assert [(r["source"], r["target"]) for r in page.json()["rows"]] == [
        ("Salary", "Budget"),
        ("Budget", "Rent"),
    ]
    assert [(r["source"], r["target"]) for r in only.json()["rows"]] == [("Budget", "Food")]


def check_exports(web: WebApp, graph_id: str, chrome: FakeRender) -> None:
    base = f"{API}/graphs/{graph_id}/export"
    exports = {fmt: web.client.get(base, params={"format": fmt}) for fmt in ("svg", "png")}
    for fmt, response in exports.items():
        assert response.status_code == 200
        assert response.content == IMAGES[fmt]
        assert response.headers["content-disposition"] == disposition("Quarterly", fmt)
        assert response.headers["content-security-policy"] == "sandbox"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert [resolved.fmt for _, resolved in chrome.calls] == ["svg", "png"]
    donut = web.client.get(base, params={"format": "svg", "chart": "donut"})
    assert donut.content == IMAGES["svg"]
    assert chrome.calls[-1][0]["data"][0]["type"] == "pie"


def check_text_exports(web: WebApp, graph_id: str) -> None:
    base = f"{API}/graphs/{graph_id}/export"
    csv_ = web.client.get(base, params={"format": "csv"})
    figure = web.client.get(base, params={"format": "json"})
    html = web.client.get(base, params={"format": "html"})
    assert csv_.headers["content-type"] == "text/csv; charset=utf-8"
    assert csv_.text.splitlines()[0].startswith("source,target,value")
    assert "Salary" in csv_.text
    assert figure.headers["content-type"] == "application/json"
    assert json.loads(figure.content)["data"][0]["type"] == "sankey"
    assert html.headers["content-type"] == "text/html; charset=utf-8"
    assert "<title>Quarterly</title>" in html.text
    assert "Plotly" in html.text


def check_compare(web: WebApp, first: str, second: str) -> None:
    response = web.client.get(f"{API}/compare/render", params={"ids": f"{first},{second}"})
    cards = response.json()
    assert response.status_code == 200
    assert [card["stats"]["links"] for card in cards] == [4, 2]
    assert colours(cards[0])["Housing"] == colours(cards[1])["Housing"]
    assert colours(cards[1])["Travel"] != colours(cards[1])["Housing"]
    page = web.client.get("/compare", params={"ids": f"{first},{second}"})
    assert page.status_code == 200
    assert 'data-page="compare"' in page.text


def check_update_and_conflict(web: WebApp, created: dict[str, Any]) -> dict[str, Any]:
    graph_id = created["id"]
    body = {**{k: created[k] for k in ("name", "tags", "source")}, "revision": 1}
    renamed = web.client.put(f"{API}/graphs/{graph_id}", json={**body, "name": "Quarterly v2"})
    stale = web.client.put(f"{API}/graphs/{graph_id}", json={**body, "name": "Lost update"})
    assert (renamed.status_code, renamed.json()["revision"]) == (200, 2)
    assert (stale.status_code, code(stale)) == (409, "conflict")
    assert stale.json()["error"]["details"][0] == "revision=2"
    updated: dict[str, Any] = renamed.json()
    return updated


def check_duplicate_bundle_delete(web: WebApp, updated: dict[str, Any]) -> None:
    graph_id = updated["id"]
    copy = web.client.post(f"{API}/graphs/{graph_id}/duplicate")
    assert copy.status_code == 201
    assert copy.json()["name"] == "Quarterly v2 (copy)"
    assert (copy.json()["id"] != graph_id, copy.json()["revision"]) == (True, 1)
    bundle = web.client.get(
        f"{API}/graphs/export", params={"ids": f"{graph_id},{copy.json()['id']}"}
    )
    report = web.client.post(f"{API}/graphs/import", content=bundle.content, headers=JSON)
    assert (bundle.status_code, report.status_code) == (200, 200)
    assert report.json()["imported"] == 2
    assert web.client.get(f"{API}/graphs").json()["total"] == 5  # two, a copy, two imported
    assert web.client.delete(f"{API}/graphs/{graph_id}").status_code == 204
    gone = web.client.get(f"{API}/graphs/{graph_id}")
    assert (gone.status_code, code(gone)) == (404, "not_found")
    assert web.client.delete(f"{API}/graphs/{graph_id}").status_code == 404
    assert web.client.get(f"/graphs/{graph_id}").status_code == 404
    assert web.client.get(f"{API}/graphs").json()["total"] == 4


def test_a_graph_lives_from_creation_to_deletion(web: WebApp, chrome: FakeRender) -> None:
    created = create(web, "Quarterly", CSV)
    graph_id = created["id"]
    assert created["source"]["content"] == CSV
    check_created(web, created)
    other = create(web, "Elsewhere", OTHER_CSV)
    check_render(web, graph_id)
    check_entries(web, graph_id)
    check_exports(web, graph_id, chrome)
    check_text_exports(web, graph_id)
    check_compare(web, graph_id, other["id"])
    check_duplicate_bundle_delete(web, check_update_and_conflict(web, created))


def test_the_answers_of_the_steps_are_json_with_the_api_headers(web: WebApp) -> None:
    created = create(web, "Quarterly", CSV)
    responses: list[Response] = [
        web.client.get(f"{API}/graphs/{created['id']}"),
        web.client.get(f"{API}/graphs/{created['id']}/render"),
        web.client.get(f"{API}/tags"),
    ]
    for response in responses:
        assert response.headers["content-type"] == "application/json"
        assert response.headers["cache-control"] == "no-store"
