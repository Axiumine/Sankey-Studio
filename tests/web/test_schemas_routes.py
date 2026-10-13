"""The query models behind real FastAPI routes: parsing, bounds and unknown parameters.

No ``from __future__ import annotations`` here: FastAPI reads the route annotations at runtime.
"""

from typing import Annotated, Any, NamedTuple

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from sankey_studio.web.schemas import (
    CollectionsQuery,
    CompareQuery,
    EntriesQuery,
    ExportQuery,
    IdsQuery,
    ListQuery,
    RenderQuery,
    SampleQuery,
    ThemeQuery,
)
from tests.web.test_schemas_support import gid

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/theme")
def theme(query: Annotated[ThemeQuery, Query()]) -> dict[str, Any]:
    return query.model_dump()


@app.get("/render")
def render(query: Annotated[RenderQuery, Query()]) -> dict[str, Any]:
    return query.model_dump()


@app.get("/compare")
def compare(query: Annotated[CompareQuery, Query()]) -> dict[str, Any]:
    return query.model_dump()


@app.get("/export-ids")
def export_ids(query: Annotated[IdsQuery, Query()]) -> dict[str, Any]:
    return query.model_dump()


@app.get("/list")
def list_(query: Annotated[ListQuery, Query()]) -> dict[str, Any]:
    return query.model_dump()


@app.get("/entries")
def entries(query: Annotated[EntriesQuery, Query()]) -> dict[str, Any]:
    return {**query.model_dump(), "options": repr(query.options())}


@app.get("/export")
def export(query: Annotated[ExportQuery, Query()]) -> dict[str, Any]:
    return {**query.model_dump(), "image": repr(query.image_options())}


@app.get("/collections")
def collections(query: Annotated[CollectionsQuery, Query()]) -> dict[str, Any]:
    return query.model_dump()


@app.get("/sample")
def sample(query: Annotated[SampleQuery, Query()]) -> dict[str, Any]:
    return query.model_dump()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def problems(response: Any) -> list[tuple[list[Any], str]]:
    return [(item["loc"], item["type"]) for item in response.json()["detail"]]


def test_comma_separated_and_repeated_ids_parse_to_a_list(client: TestClient) -> None:
    one = client.get("/compare", params={"ids": f"{gid(1)},{gid(2)}", "theme": "dark"})
    assert one.status_code == 200
    assert one.json() == {"ids": [gid(1), gid(2)], "theme": "dark"}
    many = client.get("/compare", params=[("ids", gid(3)), ("ids", f"{gid(4)},{gid(3)}")])
    assert many.json() == {"ids": [gid(3), gid(4)], "theme": "light"}


@pytest.mark.parametrize(("count", "status"), [(12, 200), (13, 422)])
def test_compare_takes_at_most_12_graphs(client: TestClient, count: int, status: int) -> None:
    response = client.get("/compare", params={"ids": ",".join(gid(n) for n in range(count))})
    assert response.status_code == status
    if status == 422:
        assert problems(response) == [(["query", "ids"], "too_long")]


@pytest.mark.parametrize(("count", "status"), [(200, 200), (201, 422)])
def test_the_bundle_export_takes_at_most_200_graphs(
    client: TestClient, count: int, status: int
) -> None:
    response = client.get("/export-ids", params={"ids": ",".join(gid(n) for n in range(count))})
    assert response.status_code == status
    if status == 200:
        assert len(response.json()["ids"]) == 200


def test_a_malformed_or_missing_id_is_a_422_on_the_query(client: TestClient) -> None:
    bad = client.get("/compare", params={"ids": f"{gid(1)},../x"})
    assert bad.status_code == 422
    assert problems(bad) == [(["query", "ids", 1], "string_pattern_mismatch")]
    missing = client.get("/compare")
    assert missing.status_code == 422
    assert problems(missing) == [(["query", "ids"], "missing")]
    assert client.get("/compare", params={"ids": ""}).status_code == 422


class Route(NamedTuple):
    """A route of this module: the model it takes and the smallest valid query string."""

    model: type
    params: dict[str, str]


ROUTES = {
    "/theme": Route(ThemeQuery, {}),
    "/render": Route(RenderQuery, {}),
    "/compare": Route(CompareQuery, {"ids": gid(1)}),
    "/export-ids": Route(IdsQuery, {"ids": gid(1)}),
    "/list": Route(ListQuery, {}),
    "/entries": Route(EntriesQuery, {}),
    "/export": Route(ExportQuery, {}),
    "/collections": Route(CollectionsQuery, {"database": "d"}),
    "/sample": Route(SampleQuery, {"database": "d", "collection": "c"}),
}


@pytest.mark.parametrize("path", list(ROUTES))
def test_an_unknown_query_parameter_is_a_422(client: TestClient, path: str) -> None:
    route = ROUTES[path]
    assert client.get(path, params=route.params).status_code == 200
    response = client.get(path, params={**route.params, "colour": "red"})
    assert response.status_code == 422
    assert problems(response) == [(["query", "colour"], "extra_forbidden")]


def test_list_query_from_the_query_string(client: TestClient) -> None:
    response = client.get("/list", params={"q": " food ", "tag": "", "limit": "5", "offset": "10"})
    assert response.json() == {"q": "food", "tag": None, "limit": 5, "offset": 10}
    assert client.get("/list", params={"limit": "200"}).status_code == 200
    assert client.get("/list", params={"limit": "201"}).status_code == 422
    assert client.get("/list", params={"offset": "-1"}).status_code == 422


def test_entries_query_from_the_query_string(client: TestClient) -> None:
    params = {
        "offset": "3",
        "limit": "500",
        "q": "x",
        "only_uncategorized": "true",
        "sort": "target",
    }
    response = client.get("/entries", params=params)
    assert response.status_code == 200
    body = response.json()
    assert (body["offset"], body["limit"], body["only_uncategorized"]) == (3, 500, True)
    assert "sort='target'" in body["options"]
    assert client.get("/entries", params={"limit": "501"}).status_code == 422
    assert client.get("/entries", params={"sort": "nope"}).status_code == 422
    assert client.get("/entries", params={"only_uncategorized": "perhaps"}).status_code == 422


def test_export_query_from_the_query_string(client: TestClient) -> None:
    params = {"chart": "donut", "format": "png", "theme": "dark", "width": "640", "height": "480"}
    params |= {"scale": "1.5", "transparent": "true"}
    response = client.get("/export", params=params)
    assert response.status_code == 200
    assert (
        response.json()["image"]
        == "ImageOptions(width=640, height=480, scale=1.5, transparent=True)"
    )
    huge = client.get("/export", params={"width": "20000", "height": "20000"})
    assert huge.status_code == 200  # the pixel cap is resolve_image's job, not the model's
    for bad in ({"width": "100001"}, {"scale": "nan"}, {"format": "pdf"}, {"chart": "pie"}):
        assert client.get("/export", params=bad).status_code == 422


SWITCHES = ("node_values", "donut_percent", "donut_value")


@pytest.mark.parametrize("path", ["/render", "/export"])
def test_the_label_switches_default_to_not_chosen(client: TestClient, path: str) -> None:
    body = client.get(path).json()
    assert [body[name] for name in SWITCHES] == [None, None, None]


@pytest.mark.parametrize("path", ["/render", "/export"])
@pytest.mark.parametrize(("text", "value"), [("true", True), ("false", False), ("1", True)])
def test_a_label_switch_is_a_boolean_from_the_query_string(
    client: TestClient, path: str, text: str, value: object
) -> None:
    for name in SWITCHES:
        response = client.get(path, params={name: text})
        assert response.status_code == 200
        body = response.json()
        assert body[name] is value
        assert [body[other] for other in SWITCHES if other != name] == [None, None]


@pytest.mark.parametrize("path", ["/render", "/export"])
@pytest.mark.parametrize("name", SWITCHES)
@pytest.mark.parametrize("bad", ["maybe", "2", "yes please"])
def test_a_label_switch_that_is_not_a_boolean_is_a_422(
    client: TestClient, path: str, name: str, bad: str
) -> None:
    response = client.get(path, params={name: bad})
    assert response.status_code == 422
    assert problems(response) == [(["query", name], "bool_parsing")]


def test_render_query_from_the_query_string(client: TestClient) -> None:
    body = client.get("/render", params={"theme": "dark", "donut_value": "true"}).json()
    assert (body["theme"], body["donut_value"]) == ("dark", True)
    assert client.get("/render", params={"theme": "sepia"}).status_code == 422


def test_mongo_queries_from_the_query_string(client: TestClient) -> None:
    assert client.get("/collections", params={"database": "flows"}).json() == {"database": "flows"}
    assert client.get("/collections").status_code == 422
    base = {"database": "flows", "collection": "links"}
    assert client.get("/sample", params=base).json()["n"] == 5
    assert client.get("/sample", params={**base, "n": "20"}).json()["n"] == 20
    assert client.get("/sample", params={**base, "n": "21"}).status_code == 422
    assert client.get("/sample", params={**base, "n": "0"}).status_code == 422
    assert client.get("/sample", params={"database": "flows"}).status_code == 422
