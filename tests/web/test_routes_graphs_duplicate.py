# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""POST /api/v1/graphs/{id}/duplicate: save a stored graph again as a copy."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.web.routers import graphs
from tests.web.test_routes_graphs_support import API, BUDGET, UNKNOWN_ID, code, save

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

URL = f"{API}/graphs"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


def test_a_duplicate_is_a_new_graph_named_copy(web: WebApp) -> None:
    original = save(web, "Household", *BUDGET, description="Monthly", tags=["home"])
    response = web.client.post(f"{URL}/{original.id}/duplicate")
    assert response.status_code == 201
    copy = response.json()
    assert copy["id"] != original.id
    assert (copy["name"], copy["revision"]) == ("Household (copy)", 1)
    assert (copy["description"], copy["tags"]) == ("Monthly", ["home"])
    for part in ("source", "transform", "style"):
        assert copy[part] == web.client.get(f"{URL}/{original.id}").json()[part]
    assert web.client.get(f"{URL}/{copy['id']}").json() == copy


def test_the_transform_and_the_style_are_copied(web: WebApp) -> None:
    transform = {"min_link_value": 1000, "hide_nodes": ["Food"]}
    style = {"title": "Budget", "color_mode": "mono", "category_colors": {"Income": "#112233"}}
    original = save(web, "Household", *BUDGET, transform=transform, style=style)
    copy = web.client.post(f"{URL}/{original.id}/duplicate").json()
    assert copy["transform"]["min_link_value"] == 1000
    assert copy["transform"]["hide_nodes"] == ["Food"]
    assert copy["style"]["title"] == "Budget"
    assert copy["style"]["color_mode"] == "mono"
    assert copy["style"]["category_colors"] == {"Income": "#112233"}


def test_the_original_is_left_alone(web: WebApp) -> None:
    original = save(web, "Household", *BUDGET)
    web.client.post(f"{URL}/{original.id}/duplicate")
    assert web.services.graphs().get(original.id) == original
    assert web.client.get(URL).json()["total"] == 2


def test_every_duplicate_gets_its_own_id(web: WebApp) -> None:
    original = save(web, "Household", *BUDGET)
    first = web.client.post(f"{URL}/{original.id}/duplicate").json()
    second = web.client.post(f"{URL}/{original.id}/duplicate").json()
    assert len({original.id, first["id"], second["id"]}) == 3
    assert first["name"] == second["name"] == "Household (copy)"


def test_a_copy_of_a_copy_adds_another_suffix(web: WebApp) -> None:
    original = save(web, "Household", *BUDGET)
    copy = web.client.post(f"{URL}/{original.id}/duplicate").json()
    again = web.client.post(f"{URL}/{copy['id']}/duplicate").json()
    assert again["name"] == "Household (copy) (copy)"


class Cut(NamedTuple):
    chars: int
    kept: int


@pytest.mark.parametrize(
    "case", [Cut(1, 1), Cut(192, 192), Cut(193, 193), Cut(194, 193), Cut(200, 193)]
)
def test_the_copy_name_is_cut_to_fit_200_characters(web: WebApp, case: Cut) -> None:
    original = save(web, "n" * case.chars, *BUDGET)
    name = web.client.post(f"{URL}/{original.id}/duplicate").json()["name"]
    assert name == "n" * case.kept + " (copy)"
    assert len(name) <= 200


def test_a_graph_that_does_not_exist_cannot_be_duplicated(web: WebApp) -> None:
    response = web.client.post(f"{URL}/{UNKNOWN_ID}/duplicate")
    assert response.status_code == 404
    assert code(response) == "not_found"
    assert web.client.get(URL).json()["total"] == 0
