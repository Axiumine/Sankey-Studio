"""Regression tests added by the wave-2 assembly verifier.

* The compare page keeps the order of ``ids`` (the ids are fixed, so a sorted or reversed list is
  always different; random ids would only catch a sort half of the time).
* An existing id is found only in its exact spelling: upper case, padding, a trailing newline (the
  ``$`` of Starlette's path regex lets one through the router) and look-alike characters are 404.
* A method-override header or query parameter never changes the method of a request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from tests.web.test_pages_support import parse
from tests.web.test_routes_graphs_support import API, put_graph

if TYPE_CHECKING:
    from tests.web.conftest import WebApp

OVERRIDE_HEADERS: Final = [
    "X-HTTP-Method-Override",
    "X-Method-Override",
    "X-HTTP-Method",
    "X-Original-Method",
    "X-Forwarded-Method",
]
#: Spellings of a stored id that are not that id (its letters make upper case differ).
BAD_SPELLINGS: Final = [
    "{upper}",
    "{id}%0a",
    "{id}%0d%0a",
    "{id}%20",
    "%20{id}",
    "{id}%00",
    "{id}x",
]


def stored_ids(web: WebApp) -> list[str]:
    return [put_graph(web, number, f"Graph {number}") for number in (10, 11, 12)]


def test_compare_keeps_the_order_of_the_ids_whatever_their_values(web: WebApp) -> None:
    first, second, third = stored_ids(web)
    for wanted in ([third, first, second], [second, third, first], [third, second, first]):
        response = web.client.get("/compare", params={"ids": ",".join(wanted)})
        data = parse(response).data()
        assert response.status_code == 200
        assert data["ids"] == wanted
        assert [g["id"] for g in data["graphs"]] == wanted


def test_compare_lists_graph_links_in_the_order_of_the_ids(web: WebApp) -> None:
    first, _second, third = stored_ids(web)
    html = web.client.get("/compare", params={"ids": f"{third},{first}"}).text
    assert html.index(f"/graphs/{third}") < html.index(f"/graphs/{first}")


@pytest.mark.parametrize("spelling", BAD_SPELLINGS)
def test_only_the_exact_id_finds_the_graph_on_the_pages(web: WebApp, spelling: str) -> None:
    (stored, *_rest) = stored_ids(web)
    wrong = spelling.format(id=stored, upper=stored.upper())
    for path in (f"/graphs/{wrong}", f"/graphs/{wrong}/edit"):
        response = web.client.get(path)
        assert (response.status_code, response.json()["error"]["code"]) == (404, "not_found")
    assert web.client.get(f"/graphs/{stored}").status_code == 200


@pytest.mark.parametrize("spelling", BAD_SPELLINGS)
def test_only_the_exact_id_reaches_the_api_routes(web: WebApp, spelling: str) -> None:
    (stored, *_rest) = stored_ids(web)
    wrong = spelling.format(id=stored, upper=stored.upper())
    statuses = [
        web.client.get(f"{API}/graphs/{wrong}").status_code,
        web.client.delete(f"{API}/graphs/{wrong}").status_code,
        web.client.post(f"{API}/graphs/{wrong}/duplicate").status_code,
        web.client.get(f"{API}/graphs/{wrong}/render").status_code,
    ]
    assert statuses == [404, 404, 404, 404]
    assert web.client.get(f"{API}/graphs/{stored}").status_code == 200
    assert len(web.services.graphs().list_graphs()) == 3


@pytest.mark.parametrize("header", OVERRIDE_HEADERS)
def test_a_method_override_header_does_not_change_the_method(web: WebApp, header: str) -> None:
    (stored, *_rest) = stored_ids(web)
    path = f"{API}/graphs/{stored}"
    assert web.client.get(path, headers={header: "DELETE"}).status_code == 200
    cross_site = {header: "DELETE", "Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"}
    refused = web.bare.post(
        path, headers={**cross_site, "Content-Type": "text/plain"}, content=b"x"
    )
    assert refused.status_code == 403
    assert web.client.get(path).status_code == 200


def test_a_method_override_parameter_does_not_change_the_method(web: WebApp) -> None:
    (stored, *_rest) = stored_ids(web)
    assert web.client.get(f"{API}/graphs/{stored}?_method=DELETE").status_code == 200
    assert web.client.post(f"{API}/graphs/{stored}?_method=DELETE").status_code == 405
    assert web.client.get(f"{API}/graphs/{stored}").status_code == 200
