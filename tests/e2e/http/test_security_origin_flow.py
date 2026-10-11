"""E2E.md A.8, part 1: who may talk to the live server (Host, Origin, Fetch-Metadata, content type).

Every refusal is checked twice: the status and error envelope, and the proof that nothing changed
(no graph created, no file stored, no graph deleted). The allowed variants are checked too, so a
guard that simply refuses everything cannot pass.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import graph_create, unique_name
from tests.e2e.support.clients import json_of, make_client, seed_graph, upload_source
from tests.e2e.support.http_b_security import (
    SAFE_POST_ROUTES,
    WRITE_ROUTES,
    Route,
    send,
    snapshot,
)

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

GRAPHS = "/api/v1/graphs"
CROSS_ORIGIN = "Cross-origin request refused"
ROUTES = [pytest.param(route, id=route.label) for route in (*WRITE_ROUTES, *SAFE_POST_ROUTES)]
BAD_HOSTS = (
    "evil.example",
    "evil.example:{port}",
    "127.0.0.1.evil.example",
    "localhost.evil.example:{port}",
    "127.0.0.2:{port}",
)
GOOD_HOSTS = ("127.0.0.1:{port}", "127.0.0.1", "localhost:{port}", "LOCALHOST:{port}", "Localhost")


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: every test uses unique graph names and compares snapshots."""
    return module_server


@pytest.fixture
def clean_server(make_server: ServerFactory) -> LiveServer:
    """A server of its own, for the tests that count the files on disk."""
    return make_server()


def names(client: httpx.Client) -> list[str]:
    """The names of all saved graphs."""
    return [item["name"] for item in json_of(client.get(GRAPHS))["items"]]


def post_graph(client: httpx.Client, name: str, **kwargs: Any) -> httpx.Response:
    """``POST /graphs`` of a small valid graph named ``name`` (extra request arguments pass on)."""
    if "content" not in kwargs and "files" not in kwargs:
        kwargs["json"] = graph_create(name)
    return client.post(GRAPHS, **kwargs)


# ------------------------------------------------------------------------------ Host


@pytest.mark.parametrize("host", BAD_HOSTS)
@pytest.mark.parametrize("path", ["/", "/api/v1/health", "/static/css/tokens.css"])
def test_a_host_header_that_is_not_ours_is_refused_as_plain_text(
    live_server: LiveServer, api: httpx.Client, host: str, path: str
) -> None:
    response = api.get(path, headers={"Host": host.format(port=live_server.port)})
    assert response.status_code == 400
    assert response.text == "Invalid host header"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize("host", GOOD_HOSTS)
def test_our_own_host_names_are_accepted_in_any_letter_case(
    live_server: LiveServer, api: httpx.Client, host: str
) -> None:
    response = api.get("/api/v1/health", headers={"Host": host.format(port=live_server.port)})
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_a_write_to_a_wrong_host_is_refused_before_anything_is_stored(
    clean_server: LiveServer,
) -> None:
    with make_client(clean_server) as api:
        response = post_graph(api, unique_name("rebind"), headers={"Host": "evil.example"})
        assert (response.status_code, response.text) == (400, "Invalid host header")
        assert names(api) == []
    assert not list(clean_server.graphs_dir.glob("*.json"))


# ------------------------------------------------------------------------------ Origin


@pytest.mark.parametrize("route", ROUTES)
def test_a_hostile_origin_is_refused_on_every_unsafe_route_and_changes_nothing(
    live_server: LiveServer, api: httpx.Client, foreign: httpx.Client, route: Route
) -> None:
    graph = seed_graph(api, unique_name("kept"))
    assert upload_source(api, "keep.csv", "a,b,1\n", overwrite=True).status_code == 201
    before = snapshot(api, live_server)
    response = send(foreign, route, graph["id"])
    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "forbidden", "message": CROSS_ORIGIN, "details": []}
    }
    assert snapshot(api, live_server) == before


ORIGINS = (
    pytest.param("http://evil.example", 403, id="foreign-site"),
    pytest.param("null", 403, id="null-origin"),
    pytest.param("http://127.0.0.1:{other}", 403, id="own-host-other-port"),
    pytest.param("https://127.0.0.1:{port}", 403, id="own-host-other-scheme"),
    pytest.param("http://localhost:{port}", 403, id="other-name-for-the-host"),
    pytest.param("http://user@127.0.0.1:{port}", 403, id="origin-with-user-info"),
    pytest.param("http://127.0.0.1:{port}", 201, id="own-origin"),
)


@pytest.mark.parametrize(("origin", "status"), ORIGINS)
def test_only_the_servers_own_origin_may_write(
    live_server: LiveServer, bare: httpx.Client, origin: str, status: int
) -> None:
    value = origin.format(port=live_server.port, other=live_server.port + 1)
    name = unique_name("origin")
    response = post_graph(bare, name, headers={"Origin": value})
    assert response.status_code == status
    assert (name in names(bare)) is (status == 201)


SITES = (("cross-site", 403), ("same-site", 403), ("same-origin", 201), ("none", 201))


@pytest.mark.parametrize(("site", "status"), SITES)
def test_the_fetch_metadata_header_decides_when_there_is_no_origin(
    bare: httpx.Client, site: str, status: int
) -> None:
    name = unique_name("site")
    response = post_graph(bare, name, headers={"Sec-Fetch-Site": site})
    assert response.status_code == status
    assert (name in names(bare)) is (status == 201)


# ------------------------------------------------------------------------------ content type


def test_a_script_without_any_browser_header_may_send_json_only(bare: httpx.Client) -> None:
    created = json_of(post_graph(bare, unique_name("curl")), 201)
    renamed = unique_name("renamed")
    body = {**graph_create(renamed), "revision": 1}
    assert bare.put(f"{GRAPHS}/{created['id']}", json=body).status_code == 200
    # a bodiless DELETE / duplicate carries no JSON content type: curl is refused
    for response in (
        bare.delete(f"{GRAPHS}/{created['id']}"),
        bare.post(f"{GRAPHS}/{created['id']}/duplicate"),
    ):
        assert response.status_code == 403
    assert renamed in names(bare)  # still there: neither request got past the guard


def test_bodiless_deletes_pass_with_the_own_origin(api: httpx.Client) -> None:
    name = unique_name("gone")
    graph = seed_graph(api, name)
    copy = json_of(api.post(f"{GRAPHS}/{graph['id']}/duplicate"), 201)
    assert {name, f"{name} (copy)"} <= set(names(api))
    assert api.delete(f"{GRAPHS}/{graph['id']}").status_code == 204
    assert api.delete(f"{GRAPHS}/{copy['id']}").status_code == 204
    assert not {name, f"{name} (copy)"} & set(names(api))


TYPES = (
    pytest.param("api", "text/plain", 415, id="own-origin-text-plain"),
    pytest.param("api", "application/x-www-form-urlencoded", 415, id="own-origin-form"),
    pytest.param("api", "application/xml", 415, id="own-origin-xml"),
    pytest.param("api", "application/json; charset=utf-8", 201, id="own-origin-json-charset"),
    pytest.param("api", "APPLICATION/JSON", 201, id="own-origin-json-upper-case"),
    pytest.param("bare", "text/plain", 403, id="curl-text-plain"),
    pytest.param("bare", None, 403, id="curl-no-content-type"),
    pytest.param("bare", "application/json", 201, id="curl-json"),
)


@pytest.mark.parametrize(("who", "content_type", "status"), TYPES)
def test_a_json_body_with_another_content_type_is_refused(
    request: pytest.FixtureRequest, who: str, content_type: str | None, status: int
) -> None:
    client: httpx.Client = request.getfixturevalue(who)
    name = unique_name("type")
    payload = json.dumps(graph_create(name))
    headers = {"Content-Type": content_type} if content_type else {}
    response = client.post(GRAPHS, content=payload, headers=headers)
    assert response.status_code == status
    if status == 415:
        assert response.json()["error"]["code"] == "unsupported_media_type"
    assert (name in names(client)) is (status == 201)


# ------------------------------------------------------------------------------ uploads


def test_an_upload_needs_a_same_origin_signal(clean_server: LiveServer) -> None:
    def put(origin: str | None, name: str, **headers: str) -> int:
        parts = {"file": (name, b"a,b,1\n", "text/csv")}
        with make_client(clean_server, origin=origin) as client:
            return client.post("/api/v1/sources/files", files=parts, headers=headers).status_code

    own = clean_server.url
    assert put(None, "curl.csv") == 403  # multipart without Origin / Sec-Fetch-Site
    assert put("http://evil.example", "evil.csv") == 403
    assert not list(clean_server.sources_dir.glob("*"))
    assert put(own, "browser.csv") == 201  # a page of the app sends its own origin
    assert put(None, "fetch.csv", **{"Sec-Fetch-Site": "same-origin"}) == 201
    stored = sorted(p.name for p in clean_server.sources_dir.glob("*"))
    assert stored == ["browser.csv", "fetch.csv"]


def test_multipart_is_accepted_on_the_upload_route_only(api: httpx.Client) -> None:
    name = unique_name("multipart")
    refused = post_graph(api, name, files={"file": ("x.json", b"{}", "application/json")})
    assert (refused.status_code, refused.json()["error"]["code"]) == (415, "unsupported_media_type")
    assert name not in names(api)


# ------------------------------------------------------------------------------ cross-site GET


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/graphs", {}),
        ("/api/v1/settings", {}),
        ("/api/v1/graphs/{gid}/export", {"format": "csv"}),
    ],
)
def test_a_cross_site_read_of_the_api_is_refused_but_a_navigation_is_not(
    api: httpx.Client, path: str, params: dict[str, str]
) -> None:
    graph = seed_graph(api, unique_name("read"))
    url = path.format(gid=graph["id"])
    cross = api.get(url, params=params, headers={"Sec-Fetch-Site": "cross-site"})
    assert (cross.status_code, cross.json()["error"]["message"]) == (403, CROSS_ORIGIN)
    for site in ("same-origin", "same-site", "none"):
        assert api.get(url, params=params, headers={"Sec-Fetch-Site": site}).status_code == 200
    page = api.get("/", headers={"Accept": "text/html", "Sec-Fetch-Site": "cross-site"})
    assert page.status_code == 200  # following a link to the app is allowed
