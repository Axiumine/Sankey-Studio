# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""GET /api/v1/compare/render: several saved graphs, one shared category colour map."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.models import GraphDraft
from sankey_studio.pipeline import BundleOptions, render_bundle
from sankey_studio.render.palette import TOKENS
from sankey_studio.web.routers import compare
from tests.web.test_routes_graphs_support import (
    API,
    PLAIN,
    UNKNOWN_ID,
    Link,
    code,
    ids_of,
    save,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from sankey_studio.models import GraphDefinition, Theme
    from tests.web.conftest import AppFactory, WebApp

URL = f"{API}/compare/render"
#: Three graphs whose categories rank differently alone (X/Y/Z) and together.
GRAPH_A: tuple[Link, ...] = (("s", "t", 100.0, "X"), ("s", "u", 10.0, "Y"))
GRAPH_B: tuple[Link, ...] = (("s", "t", 10.0, "X"), ("s", "u", 100.0, "Y"))
GRAPH_C: tuple[Link, ...] = (("s", "t", 5.0, "Z"), ("s", "u", 100.0, "Y"))
#: Four links in a row.
CHAIN: tuple[Link, ...] = tuple((a, b, 1.0, None) for a, b in zip("pqrs", "qrst", strict=True))


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([compare.router])


def trio(web: WebApp) -> list[GraphDefinition]:
    return [
        save(web, name, *links) for name, links in (("A", GRAPH_A), ("B", GRAPH_B), ("C", GRAPH_C))
    ]


def colours(bundle: dict[str, Any]) -> dict[str, str]:
    return {row["name"]: row["color"] for row in bundle["categories"]}


def ids(graphs: list[GraphDefinition]) -> str:
    return ",".join(graph.id for graph in graphs)


def test_the_cards_share_one_category_colour_map(web: WebApp) -> None:
    response = web.client.get(f"{URL}?ids={ids(trio(web))}")
    assert response.status_code == 200
    cards = [colours(bundle) for bundle in response.json()]
    assert len(cards) == 3
    assert cards[0]["Y"] == cards[1]["Y"] == cards[2]["Y"]
    assert cards[0]["X"] == cards[1]["X"]
    assert len({cards[0]["X"], cards[0]["Y"], cards[2]["Z"]}) == 3


def test_drawn_one_by_one_the_same_graphs_would_reuse_a_colour(web: WebApp) -> None:
    graphs = trio(web)
    alone = []
    for graph in (graphs[0], graphs[2]):
        draft = GraphDraft(source=graph.source, transform=graph.transform, style=graph.style)
        alone.append(
            colours(render_bundle(web.services, draft, BundleOptions("light")).model_dump())
        )
    assert alone[0]["X"] == alone[1]["Z"]  # the shared map is what keeps them apart


def test_the_cards_come_in_the_order_of_the_ids(web: WebApp) -> None:
    small, big = save(web, "Small", *PLAIN), save(web, "Big", *CHAIN)
    forward = web.client.get(f"{URL}?ids={small.id},{big.id}").json()
    backward = web.client.get(f"{URL}?ids={big.id},{small.id}").json()
    assert [card["stats"]["links"] for card in forward] == [2, 4]
    assert [card["stats"]["links"] for card in backward] == [4, 2]


def test_a_single_graph_is_a_list_of_one_card(web: WebApp) -> None:
    stored = save(web, "One", *GRAPH_A)
    cards = web.client.get(f"{URL}?ids={stored.id}").json()
    assert len(cards) == 1
    assert cards[0]["donut_available"] is True


def test_a_repeated_id_is_drawn_once(web: WebApp) -> None:
    stored = save(web, "One", *PLAIN)
    assert len(web.client.get(f"{URL}?ids={stored.id},{stored.id}").json()) == 1
    assert len(web.client.get(f"{URL}?ids={stored.id}&ids={stored.id}").json()) == 1


class Cap(NamedTuple):
    ids: int
    status: int


@pytest.mark.parametrize("case", [Cap(1, 404), Cap(12, 404), Cap(13, 422), Cap(200, 422)])
def test_at_most_12_ids_are_taken(client: TestClient, case: Cap) -> None:
    # none of the ids is stored: 404 means the list passed the cap and the lookup ran
    response = client.get(f"{URL}?ids={ids_of(case.ids)}")
    assert response.status_code == case.status
    assert code(response) == ("not_found" if case.status == 404 else "validation_error")


def test_twelve_graphs_are_twelve_cards(web: WebApp) -> None:
    stored = [save(web, f"Graph {n}", *PLAIN) for n in range(12)]
    cards = web.client.get(f"{URL}?ids={ids(stored)}").json()
    assert len(cards) == 12


def test_one_unknown_id_fails_the_whole_request(web: WebApp) -> None:
    stored = save(web, "One", *PLAIN)
    response = web.client.get(f"{URL}?ids={stored.id},{UNKNOWN_ID}")
    assert response.status_code == 404
    assert code(response) == "not_found"


@pytest.mark.parametrize("query", ["", "?ids=", "?ids=abc", f"?ids={UNKNOWN_ID},", "?theme=dark"])
def test_a_bad_ids_list_is_a_422(client: TestClient, query: str) -> None:
    response = client.get(URL + query)
    assert response.status_code == 422
    assert code(response) == "validation_error"


@pytest.mark.parametrize("query", ["&theme=sepia", "&theme=", "&sort=1"])
def test_a_bad_query_is_a_422(client: TestClient, query: str) -> None:
    assert client.get(f"{URL}?ids={UNKNOWN_ID}{query}").status_code == 422


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_theme_applies_to_every_card(web: WebApp, theme: Theme) -> None:
    stored = [save(web, "One", *PLAIN), save(web, "Two", *GRAPH_A)]
    cards = web.client.get(f"{URL}?ids={ids(stored)}&theme={theme}").json()
    assert [card["figure"]["layout"]["paper_bgcolor"] for card in cards] == [
        TOKENS[theme].surface
    ] * 2


def test_the_default_theme_is_light(web: WebApp) -> None:
    stored = save(web, "One", *PLAIN)
    card = web.client.get(f"{URL}?ids={stored.id}").json()[0]
    assert card["figure"]["layout"]["paper_bgcolor"] == TOKENS["light"].surface


def test_a_graph_that_cannot_be_loaded_fails_the_request(web: WebApp) -> None:
    good = save(web, "Good", *PLAIN)
    gone = web.services.graphs().create(
        type(good).model_validate(
            {**good.model_dump(), "source": {"type": "text", "origin": "file", "path": "gone.csv"}}
        )
    )
    response = web.client.get(f"{URL}?ids={good.id},{gone.id}")
    assert response.status_code == 404
    assert code(response) == "source_not_found"


def test_the_graphs_are_built_through_the_app_cache(web: WebApp) -> None:
    cache = web.app.state.result_cache
    query = f"{URL}?ids={ids(trio(web))}"
    for _ in range(2):
        assert web.client.get(query).status_code == 200
        assert cache.size == 3


def test_compare_stays_available_in_read_only_remote_mode(make_app: AppFactory) -> None:
    web = make_app([compare.router], mode="remote_read_only")
    stored = save(web, "One", *PLAIN)
    assert web.client.get(f"{URL}?ids={stored.id}").status_code == 200
