"""GET /api/v1/graphs/{id}/render: a stored graph, drawn."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.models import AppSettings, GraphCreate, GraphDraft
from sankey_studio.pipeline import BundleOptions, render_bundle
from sankey_studio.render.palette import TOKENS
from sankey_studio.web.routers import graphs
from tests.web.test_routes_graphs_support import (
    API,
    BUDGET,
    PLAIN,
    code,
    csv_source,
    save,
)

if TYPE_CHECKING:
    from sankey_studio.models import Theme
    from tests.web.conftest import AppFactory, WebApp


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


def url(graph_id: str, query: str = "") -> str:
    return f"{API}/graphs/{graph_id}/render{query}"


def test_a_stored_graph_is_drawn_like_its_draft(web: WebApp) -> None:
    transform = {"min_link_value": 1000}
    stored = save(web, "Household", *BUDGET, style={"title": "Budget"}, transform=transform)
    response = web.client.get(url(stored.id))
    assert response.status_code == 200
    draft = GraphDraft(source=stored.source, transform=stored.transform, style=stored.style)
    expected = render_bundle(web.services, draft, BundleOptions(theme="light"))
    assert response.json() == expected.model_dump(mode="json")
    assert response.json()["stats"]["links"] == 3  # the flow of 600 is below the minimum


class ThemeCase(NamedTuple):
    query: str
    theme: Theme


@pytest.mark.parametrize(
    "case",
    [ThemeCase("", "light"), ThemeCase("?theme=light", "light"), ThemeCase("?theme=dark", "dark")],
)
def test_the_theme_picks_the_surface_colour(web: WebApp, case: ThemeCase) -> None:
    stored = save(web, "Household", *PLAIN)
    layout = web.client.get(url(stored.id, case.query)).json()["figure"]["layout"]
    assert layout["paper_bgcolor"] == TOKENS[case.theme].surface


@pytest.mark.parametrize("query", ["?theme=sepia", "?theme=", "?ids=1"])
def test_a_bad_query_is_a_422(web: WebApp, query: str) -> None:
    stored = save(web, "Household", *PLAIN)
    response = web.client.get(url(stored.id, query))
    assert response.status_code == 422
    assert code(response) == "validation_error"


def test_a_graph_whose_file_is_gone_is_a_404_source_not_found(web: WebApp) -> None:
    stored = web.services.graphs().create(
        graph_create({"type": "text", "origin": "file", "path": "gone.csv"})
    )
    response = web.client.get(url(stored.id))
    assert response.status_code == 404
    assert code(response) == "source_not_found"


def graph_create(source: dict[str, str]) -> GraphCreate:
    return GraphCreate.model_validate({"name": "Gone", "source": source})


def test_the_drawing_cap_follows_the_settings(make_app: AppFactory) -> None:
    web = make_app([graphs.router], settings=AppSettings(max_drawn_links=50))
    stored = web.services.graphs().create(
        GraphCreate.model_validate({"name": "Big", "source": csv_source(60)})
    )
    stats = web.client.get(url(stored.id)).json()["stats"]
    assert (stats["links"], stats["drawn_links"]) == (60, 50)


def test_rendering_twice_builds_the_graph_once(web: WebApp) -> None:
    stored = save(web, "Household", *PLAIN)
    cache = web.app.state.result_cache
    for _ in range(2):
        web.client.get(url(stored.id))
        assert cache.size == 1
