"""GET /api/v1/graphs/export and POST /api/v1/graphs/import: JSON bundles of saved graphs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.web.routers import graphs
from tests.web.test_routes_graphs_support import (
    API,
    BUDGET,
    PLAIN,
    UNKNOWN_ID,
    code,
    graph_json,
    ids_of,
    put_graph,
    save,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from sankey_studio.models import AppSettings
    from tests.web.conftest import AppFactory, WebApp

EXPORT = f"{API}/graphs/export"
IMPORT = f"{API}/graphs/import"
BUNDLE = "sankey-studio/graphs"
NAMES = ("One", "Two", "Three")
DISPOSITION = (
    "attachment; filename=\"sankey-studio-graphs.json\"; filename*=UTF-8''sankey-studio-graphs.json"
)


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


def bundle_of(graphs_: list[Any]) -> dict[str, Any]:
    return {"format": BUNDLE, "version": 2, "graphs": graphs_}


def stored_json(name: str) -> dict[str, Any]:
    """A graph as a bundle holds it: the persisted shape, with id and timestamps."""
    stamps = {"created_at": "2020-01-01T00:00:00Z", "updated_at": "2020-01-02T00:00:00Z"}
    return {**graph_json(name, *PLAIN), "id": "a" * 32, **stamps}


def test_the_export_is_a_json_attachment(web: WebApp) -> None:
    stored = save(web, "Household", *BUDGET)
    response = web.client.get(f"{EXPORT}?ids={stored.id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == DISPOSITION
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith('{\n  "format": "sankey-studio/graphs",\n  "version": 2,')


def test_the_bundle_holds_the_graphs_in_the_order_of_the_ids(web: WebApp) -> None:
    # fixed ids (1 < 2 < 3): the order asked for is neither the sorted nor the reversed one
    first, second, third = (put_graph(web, n, name) for n, name in enumerate(NAMES, start=1))
    ids = f"{third},{first},{second},{first}"
    bundle = web.client.get(f"{EXPORT}?ids={ids}").json()
    assert (bundle["format"], bundle["version"]) == (BUNDLE, 2)
    assert [graph["name"] for graph in bundle["graphs"]] == ["Three", "One", "Two"]
    assert [graph["id"] for graph in bundle["graphs"]] == [third, first, second]


def test_a_repeated_ids_parameter_works_too(web: WebApp) -> None:
    first, second = put_graph(web, 1, "One"), put_graph(web, 2, "Two")
    bundle = web.client.get(f"{EXPORT}?ids={second}&ids={first}").json()
    assert [graph["name"] for graph in bundle["graphs"]] == ["Two", "One"]


def test_an_unknown_id_fails_the_whole_export(web: WebApp) -> None:
    stored = save(web, "Household", *PLAIN)
    response = web.client.get(f"{EXPORT}?ids={stored.id},{UNKNOWN_ID}")
    assert response.status_code == 404
    assert code(response) == "not_found"
    assert "content-disposition" not in response.headers


class Cap(NamedTuple):
    ids: int
    status: int


@pytest.mark.parametrize(
    "case", [Cap(1, 404), Cap(200, 404), Cap(201, 422), Cap(1000, 422)], ids=lambda c: str(c.ids)
)
def test_at_most_200_ids_are_taken(client: TestClient, case: Cap) -> None:
    # none of the ids is stored: 404 means the list passed the cap and the lookup ran
    response = client.get(f"{EXPORT}?ids={ids_of(case.ids)}")
    assert response.status_code == case.status
    assert code(response) == ("not_found" if case.status == 404 else "validation_error")


@pytest.mark.parametrize("query", ["", "?ids=", "?ids=abc", f"?ids={UNKNOWN_ID},", "?format=json"])
def test_a_bad_ids_list_is_a_422(client: TestClient, query: str) -> None:
    response = client.get(EXPORT + query)
    assert response.status_code == 422
    assert code(response) == "validation_error"


def test_a_bundle_names_a_connection_and_never_holds_its_uri(
    make_app: AppFactory, app_settings: AppSettings
) -> None:
    web = make_app([graphs.router], settings=app_settings)
    source = {"type": "mongo", "connection": "test", "database": "flows", "collection": "moves"}
    stored = web.client.post(f"{API}/graphs", json={"name": "From Mongo", "source": source}).json()
    response = web.client.get(f"{EXPORT}?ids={stored['id']}")
    assert response.json()["graphs"][0]["source"]["connection"] == "test"
    assert "hunter2" not in response.text
    assert "mongodb://" not in response.text


def test_an_exported_bundle_imports_as_new_graphs(web: WebApp) -> None:
    one, two = save(web, "One", *BUDGET), save(web, "Two", *PLAIN, tags=["x"])
    text = web.client.get(f"{EXPORT}?ids={one.id},{two.id}").text
    response = web.client.post(IMPORT, content=text, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    report = response.json()
    assert (report["imported"], report["failed"], report["errors"]) == (2, 0, [])
    assert len(report["ids"]) == 2
    assert not {one.id, two.id} & set(report["ids"])
    imported = [web.client.get(f"{API}/graphs/{graph_id}").json() for graph_id in report["ids"]]
    assert [graph["name"] for graph in imported] == ["One", "Two"]
    assert imported[1]["tags"] == ["x"]
    assert web.client.get(f"{API}/graphs").json()["total"] == 4


def test_an_import_gives_every_graph_a_fresh_identity(client: TestClient) -> None:
    graph = {**stored_json("Old"), "revision": 7}
    report = client.post(IMPORT, json=bundle_of([graph])).json()
    assert report["imported"] == 1
    stored = client.get(f"{API}/graphs/{report['ids'][0]}").json()
    assert stored["id"] != "a" * 32
    assert stored["revision"] == 1
    assert stored["created_at"] > "2021"


def test_an_invalid_graph_is_reported_and_the_others_are_kept(client: TestClient) -> None:
    good = stored_json("Good")
    bad = stored_json("")
    report = client.post(IMPORT, json=bundle_of([bad, good, 5])).json()
    assert (report["imported"], report["failed"]) == (1, 2)
    assert len(report["ids"]) == 1
    assert report["errors"][0].startswith("graph 1: ")
    assert report["errors"][1] == "graph 3: not an object"
    assert client.get(f"{API}/graphs").json()["total"] == 1


class Unusable(NamedTuple):
    label: str
    body: Any


@pytest.mark.parametrize(
    "case",
    [
        Unusable("object", {}),
        Unusable("list", []),
        Unusable("number", 5),
        Unusable("format", {"format": "other", "version": 2, "graphs": []}),
        Unusable("version 1 is refused", {"format": BUNDLE, "version": 1, "graphs": []}),
        Unusable("version", {"format": BUNDLE, "version": 3, "graphs": []}),
        Unusable("no list", {"format": BUNDLE, "version": 2, "graphs": {}}),
        Unusable("folders", {"format": BUNDLE, "version": 2, "graphs": [], "folders": {}}),
    ],
    ids=lambda case: case.label,
)
def test_an_unusable_bundle_is_a_422_and_stores_nothing(client: TestClient, case: Unusable) -> None:
    response = client.post(IMPORT, json=case.body)
    assert response.status_code == 422
    assert code(response) == "bundle_error"
    assert client.get(f"{API}/graphs").json()["total"] == 0


def test_a_body_that_is_not_json_is_a_422(client: TestClient) -> None:
    response = client.post(
        IMPORT, content="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert code(response) == "validation_error"


def test_an_empty_bundle_imports_nothing(client: TestClient) -> None:
    response = client.post(IMPORT, json=bundle_of([]))
    assert response.status_code == 200
    assert response.json() == {"imported": 0, "failed": 0, "ids": [], "errors": [], "folders": 0}
