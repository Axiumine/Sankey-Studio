"""POST /api/v1/preview: the live bundle of an unsaved draft."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.models import AppSettings
from sankey_studio.render.palette import TOKENS
from sankey_studio.web.routers import preview
from tests.web.test_routes_graphs_support import (
    API,
    BUDGET,
    PLAIN,
    code,
    csv_source,
    draft_json,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from sankey_studio.models import Theme
    from tests.web.conftest import AppFactory, WebApp

URL = f"{API}/preview"
BUNDLE_KEYS = {
    "figure",
    "legend",
    "donut_available",
    "donut",
    "donut_empty_reason",
    "categories",
    "category_names",
    "stats",
    "entries",
    "entries_total",
    "warnings",
}


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([preview.router])


def test_a_draft_is_drawn_as_a_bundle(client: TestClient) -> None:
    response = client.post(URL, json=draft_json(*BUDGET))
    assert response.status_code == 200
    bundle = response.json()
    assert set(bundle) == BUNDLE_KEYS
    assert bundle["figure"]["data"][0]["type"] == "sankey"
    assert bundle["stats"] == {
        "nodes": 5,
        "links": 4,
        "drawn_links": 4,
        "total_in": 4000.0,
        "total_out": 1800.0,
        "layers": 3,
        "category_count": 2,
    }
    assert bundle["warnings"] == []


def test_a_categorised_draft_offers_the_donut(client: TestClient) -> None:
    bundle = client.post(URL, json=draft_json(*BUDGET)).json()
    assert bundle["donut_available"] is True
    assert bundle["donut_empty_reason"] is None
    assert bundle["donut"]["data"][0]["type"] == "pie"
    assert bundle["category_names"] == ["Income", "Housing"]
    assert [row["name"] for row in bundle["categories"]] == ["Income", "Housing", "Uncategorized"]
    assert [row["kind"] for row in bundle["categories"]] == [
        "category",
        "category",
        "uncategorized",
    ]
    assert bundle["entries_total"] == 4
    assert [(e["source"], e["target"], e["value"]) for e in bundle["entries"]] == [
        ("Salary", "Budget", 3000.0),
        ("Budget", "Rent", 1200.0),
        ("Freelance", "Budget", 1000.0),
        ("Budget", "Food", 600.0),
    ]


def test_a_draft_without_categories_is_a_plain_sankey(client: TestClient) -> None:
    bundle = client.post(URL, json=draft_json(*PLAIN)).json()
    assert bundle["donut_available"] is False
    assert bundle["donut"] is None
    assert bundle["donut_empty_reason"] == "no_categories"
    assert bundle["categories"] == []
    assert bundle["category_names"] == []
    assert bundle["stats"]["category_count"] == 0


class ThemeCase(NamedTuple):
    query: str
    theme: Theme


@pytest.mark.parametrize(
    "case",
    [ThemeCase("", "light"), ThemeCase("?theme=light", "light"), ThemeCase("?theme=dark", "dark")],
)
def test_the_theme_picks_the_surface_colour(client: TestClient, case: ThemeCase) -> None:
    bundle = client.post(URL + case.query, json=draft_json(*PLAIN)).json()
    assert bundle["figure"]["layout"]["paper_bgcolor"] == TOKENS[case.theme].surface


@pytest.mark.parametrize("query", ["?theme=sepia", "?theme=", "?theme=Light", "?colour=1"])
def test_a_bad_query_is_a_422(client: TestClient, query: str) -> None:
    response = client.post(URL + query, json=draft_json(*PLAIN))
    assert response.status_code == 422
    assert code(response) == "validation_error"


def test_a_body_that_is_not_a_draft_is_a_422_that_names_the_field(client: TestClient) -> None:
    response = client.post(URL, json={})
    assert response.status_code == 422
    assert response.json()["error"]["details"] == ["body.source: Field required"]


def test_a_422_never_echoes_what_was_submitted(client: TestClient) -> None:
    body = {**draft_json(*PLAIN), "figure": {"layout": {"images": [{"source": "hunter2"}]}}}
    response = client.post(URL, json=body)
    assert response.status_code == 422
    assert "hunter2" not in response.text
    assert response.json()["error"]["details"] == ["body.figure: Extra inputs are not permitted"]


def test_an_invalid_link_is_a_422(client: TestClient) -> None:
    body = draft_json(("a", "b", 0.0, None))
    response = client.post(URL, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0].startswith("body.source.manual.links.0.value:")


def test_a_missing_file_is_a_404(client: TestClient) -> None:
    source = {"type": "text", "origin": "file", "path": "missing.csv"}
    response = client.post(URL, json={"source": source})
    assert response.status_code == 404
    assert code(response) == "source_not_found"


def test_a_cycle_is_a_graph_build_error(client: TestClient) -> None:
    body = draft_json(("a", "b", 1.0, None), ("b", "a", 1.0, None))
    response = client.post(URL, json=body)
    assert response.status_code == 422
    assert code(response) == "graph_build_error"


def bad_row_draft(*, strict: bool) -> dict[str, Any]:
    content = "source,target,value\na,b,10\nc,d,oops\n"
    source = {"type": "text", "origin": "inline", "format": "csv", "content": content}
    return {"source": source, "transform": {"strict": strict}}


def test_a_bad_row_is_skipped_with_a_warning_when_lenient(client: TestClient) -> None:
    response = client.post(URL, json=bad_row_draft(strict=False))
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["stats"]["links"] == 1
    assert len(bundle["warnings"]) == 1


def test_a_bad_row_fails_the_preview_when_strict(client: TestClient) -> None:
    response = client.post(URL, json=bad_row_draft(strict=True))
    assert response.status_code == 422
    assert code(response) == "source_error"


def test_a_mongo_source_is_read_through_the_configured_connection(
    make_app: AppFactory, app_settings: AppSettings
) -> None:
    web = make_app([preview.router], settings=app_settings)
    web.mongo["flows"]["moves"].insert_many(
        [{"source": "a", "target": "b", "value": 5}, {"source": "b", "target": "c", "value": 2}]
    )
    source = {"type": "mongo", "connection": "test", "collection": "moves"}
    response = web.client.post(URL, json={"source": source})
    assert response.status_code == 200
    assert response.json()["stats"]["total_in"] == 5.0


def test_an_unknown_connection_is_a_source_error(client: TestClient) -> None:
    source = {"type": "mongo", "connection": "nope", "database": "flows", "collection": "moves"}
    response = client.post(URL, json={"source": source})
    assert response.status_code == 404
    assert code(response) == "source_not_found"


def test_the_drawing_cap_follows_the_settings(make_app: AppFactory) -> None:
    web = make_app([preview.router], settings=AppSettings(max_drawn_links=50))
    bundle = web.client.post(URL, json={"source": csv_source(60)}).json()
    assert bundle["stats"]["links"] == 60
    assert bundle["stats"]["drawn_links"] == 50
    assert len(bundle["figure"]["data"][0]["link"]["value"]) == 50
    assert len(bundle["warnings"]) == 1


def test_the_entries_preview_holds_at_most_2000_rows(client: TestClient) -> None:
    bundle = client.post(URL, json={"source": csv_source(2001)}).json()
    assert len(bundle["entries"]) == 2000
    assert bundle["entries_total"] == 2001


def test_a_preview_stays_available_in_read_only_remote_mode(make_app: AppFactory) -> None:
    web = make_app([preview.router], mode="remote_read_only")
    assert web.client.post(URL, json=draft_json(*PLAIN)).status_code == 200


def test_the_preview_goes_through_the_app_cache(web: WebApp) -> None:
    cache = web.app.state.result_cache
    assert cache.size == 0
    web.client.post(URL, json=draft_json(*PLAIN))
    assert cache.size == 1
    web.client.post(URL, json=draft_json(*PLAIN, style={"title": "Another look"}))
    assert cache.size == 1  # the style is not part of the key
    web.client.post(URL, json=draft_json(*PLAIN, transform={"min_link_value": 5}))
    assert cache.size == 2
