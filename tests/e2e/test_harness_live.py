"""Self-tests of the harness against the live server: options, samples and the HTTP side.

The browser side (watcher, artefacts, waits, fixtures) is in ``test_harness_browser``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import (
    BUDGET,
    BUDGET_CATEGORISED,
    CYCLE,
    LAYERED,
    MANY_LINKS,
    MONGO_PASSWORD,
    Sample,
    graph_draft,
    mongo_settings,
    seed_flows,
    unique_name,
)
from tests.e2e.support.clients import (
    content_type_of,
    json_of,
    make_client,
    post_multipart,
    seed_graph,
    upload_source,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

BREAK = {"on_cycle": "break"}
SAMPLES = [
    pytest.param(BUDGET, {}, id="budget"),
    pytest.param(BUDGET_CATEGORISED, {}, id="budget-categorised"),
    pytest.param(LAYERED, {}, id="layered"),
    pytest.param(CYCLE, BREAK, id="cycle-broken"),
    pytest.param(MANY_LINKS, {}, id="many-links"),
]


# ------------------------------------------------------------------------------ the samples


@pytest.mark.parametrize(("sample", "transform"), SAMPLES)
def test_every_sample_is_what_the_app_reports_for_it(
    api: httpx.Client, sample: Sample, transform: Mapping[str, Any]
) -> None:
    bundle = json_of(api.post("/api/v1/preview", json=graph_draft(sample.csv, transform=transform)))
    stats = bundle["stats"]
    assert (stats["nodes"], stats["links"], stats["layers"]) == (
        sample.nodes,
        sample.links,
        sample.layers,
    )
    assert stats["total_in"] == pytest.approx(sample.total)
    assert stats["category_count"] == sample.category_count
    shares = {c["name"]: c["value"] for c in bundle["categories"] if c["kind"] == "category"}
    assert shares == dict(sample.categories)
    assert bundle["donut_available"] is bool(sample.categories)


def test_the_cycle_sample_is_refused_unless_the_cycle_is_broken(api: httpx.Client) -> None:
    refused = api.post("/api/v1/preview", json=graph_draft(CYCLE.csv))
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "graph_build_error"
    broken = json_of(api.post("/api/v1/preview", json=graph_draft(CYCLE.csv, transform=BREAK)))
    assert any("cycle" in warning for warning in broken["warnings"])


def test_a_saved_sample_renders_the_same_way(api: httpx.Client) -> None:
    saved = seed_graph(api, unique_name("budget"), graph_draft(BUDGET_CATEGORISED.csv))
    bundle = json_of(api.get(f"/api/v1/graphs/{saved['id']}/render"))
    assert bundle["stats"]["nodes"] == BUDGET_CATEGORISED.nodes
    assert bundle["category_names"][0] == "Income"


# ------------------------------------------------------------------------------ server options


def test_the_settings_option_is_stored_before_the_server_starts(make_server: ServerFactory) -> None:
    server = make_server(settings={"max_links": 100, "max_drawn_links": 50})
    assert server.settings_file.is_file()
    with make_client(server) as api:
        settings = json_of(api.get("/api/v1/settings"))
        assert (settings["max_links"], settings["max_drawn_links"]) == (100, 50)
        too_big = api.post("/api/v1/preview", json=graph_draft(MANY_LINKS.csv))
        assert too_big.status_code == 413
        assert too_big.json()["error"]["code"] == "graph_too_large"


def test_the_default_server_has_default_settings_and_no_connections(
    live_server: LiveServer, api: httpx.Client
) -> None:
    settings = json_of(api.get("/api/v1/settings"))
    assert settings["mongo_connections"] == []
    assert settings["max_links"] == 200_000
    assert settings["bootstrap"]["remote_mode"] is False
    assert not live_server.settings_file.exists()


def test_remote_variants_differ_in_their_write_permission(make_server: ServerFactory) -> None:
    read_only = make_server(remote_mode=True)
    with_writes = make_server(remote_mode=True, allow_remote_writes=True)
    assert (read_only.read_only, with_writes.read_only) == (True, False)
    with make_client(with_writes) as api:
        assert json_of(api.get("/api/v1/settings"))["bootstrap"]["writes_allowed"] is True
        assert api.put("/api/v1/settings", json={"max_links": 150}).status_code == 200


def test_writes_without_remote_mode_are_not_a_valid_combination(
    make_server: ServerFactory,
) -> None:
    with pytest.raises(ValueError, match="remote_writes needs remote_mode"):
        make_server(allow_remote_writes=True)


def test_a_seeded_mongomock_answers_for_a_configured_connection(
    make_server: ServerFactory,
) -> None:
    server = make_server(settings=mongo_settings("main"), seed_mongo=seed_flows)
    with make_client(server) as api:
        assert json_of(api.get("/api/v1/mongo/main/databases")) == ["flows"]
        collections = api.get("/api/v1/mongo/main/collections", params={"database": "flows"})
        assert json_of(collections) == ["transfers"]
        stored = json_of(api.get("/api/v1/settings"))["mongo_connections"][0]
        assert stored["has_secret"] is True
        assert MONGO_PASSWORD not in api.get("/api/v1/settings").text
        assert json_of(api.post("/api/v1/settings/mongo/main/test"))["ok"] is True


def test_the_outage_switch_makes_mongo_unreachable_at_once_and_back(
    make_server: ServerFactory,
) -> None:
    server = make_server(settings=mongo_settings("main"), seed_mongo=seed_flows)
    with make_client(server) as api:
        server.mongo.unreachable = True
        down = api.get("/api/v1/mongo/main/databases")
        assert down.status_code == 422
        assert "unreachable" in down.json()["error"]["message"]
        assert api.post("/api/v1/settings/mongo/main/test").status_code == 503
        server.mongo.unreachable = False
        assert json_of(api.get("/api/v1/mongo/main/databases")) == ["flows"]


def test_unknown_mongo_connections_are_404_on_a_default_server(api: httpx.Client) -> None:
    assert api.get("/api/v1/mongo/nope/databases").status_code == 404


def test_the_mongomock_client_of_a_server_is_the_one_its_app_uses(
    make_server: ServerFactory,
) -> None:
    server = make_server(settings=mongo_settings("main"))
    server.mongo["late"]["docs"].insert_one({"x": 1})
    with make_client(server) as api:
        assert "late" in json_of(api.get("/api/v1/mongo/main/databases"))


# ------------------------------------------------------------------------------ clients


def test_upload_source_is_a_multipart_post_that_lands_in_the_sources_dir(
    live_server: LiveServer, api: httpx.Client
) -> None:
    created = json_of(upload_source(api, "flows.csv", BUDGET.csv), 201)
    assert created["name"] == "flows.csv"
    assert (live_server.sources_dir / "flows.csv").read_text() == BUDGET.csv
    again = upload_source(api, "flows.csv", BUDGET.csv)
    assert again.status_code == 409
    assert upload_source(api, "flows.csv", "a,b,1\n", overwrite=True).status_code == 201
    assert json_of(api.get("/api/v1/sources/files/flows.csv/preview"))["lines"] == ["a,b,1"]


def test_post_multipart_sends_exactly_the_parts_and_fields_it_is_given(api: httpx.Client) -> None:
    response = post_multipart(
        api,
        "/api/v1/sources/files",
        {"file": ("x.csv", b"a,b,1", "text/csv")},
        {"overwite": "true"},
    )
    assert response.status_code == 422  # a misspelt form field is refused: it was really sent
    assert response.json()["error"]["details"] == ["body.overwite: Extra inputs are not permitted"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.csv", "text/csv"),
        ("A.CSV", "text/csv"),
        ("a.tsv", "text/tab-separated-values"),
        ("a.json", "application/json"),
        ("a.sankey", "text/plain"),
        ("noext", "text/plain"),
    ],
)
def test_content_type_of_follows_the_suffix(name: str, expected: str) -> None:
    assert content_type_of(name) == expected


def test_json_of_names_the_request_and_the_body_when_the_status_is_wrong(
    api: httpx.Client,
) -> None:
    with pytest.raises(
        AssertionError, match=r"GET /api/v1/graphs/zzz: expected 200, got 404.*not_found"
    ):
        json_of(api.get("/api/v1/graphs/zzz"))
    assert json_of(api.delete("/api/v1/graphs/zzz"), 404)["error"]["code"] == "not_found"
