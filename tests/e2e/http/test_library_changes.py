"""E2E A.5 (library): create, duplicate, edit with the revision check, and delete."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import BUDGET, LAYERED, graph_create, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.http_a_library import GRAPHS, listed_ids, update_body
from tests.e2e.support.stamps import instant

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: each test works on graphs of its own and on deltas."""
    return module_server


def total(api: httpx.Client) -> int:
    return int(json_of(api.get(GRAPHS, params={"limit": 1}))["total"])


def test_a_new_graph_is_revision_one_and_comes_back_whole(api: httpx.Client) -> None:
    name = unique_name("Created")
    body = graph_create(name, tags=["a", "b"], description="Smoke graph")
    created = json_of(api.post(GRAPHS, json=body), 201)
    assert (created["name"], created["description"], created["tags"]) == (
        name,
        "Smoke graph",
        ["a", "b"],
    )
    assert (created["revision"], created["schema_version"]) == (1, 1)
    assert created["created_at"] == created["updated_at"]
    assert created["source"]["content"] == BUDGET.csv  # the CSV is stored with the graph
    assert json_of(api.get(f"{GRAPHS}/{created['id']}")) == created
    assert created["id"] in listed_ids(api, q=name)


def test_tags_are_trimmed_deduplicated_and_blanks_dropped(api: httpx.Client) -> None:
    body = graph_create(unique_name("Tags"), tags=[" a ", "a", "b", "  ", "B"])
    created = json_of(api.post(GRAPHS, json=body), 201)
    assert created["tags"] == ["a", "b", "B"]


@pytest.mark.parametrize(
    ("change", "where"),
    [
        ({"name": ""}, "body.name"),
        ({"name": "   "}, "body.name"),
        ({"name": "n" * 201}, "body.name"),
        ({"description": "d" * 2001}, "body.description"),
        ({"tags": [f"t{i}" for i in range(21)]}, "body.tags"),
        ({"tags": ["t" * 41]}, "body.tags"),
        ({"bogus": 1}, "body.bogus"),
    ],
    ids=[
        "no-name",
        "blank-name",
        "long-name",
        "long-description",
        "many-tags",
        "long-tag",
        "extra",
    ],
)
def test_an_invalid_graph_is_refused_and_nothing_is_saved(
    api: httpx.Client, change: dict[str, Any], where: str
) -> None:
    before = total(api)
    body = {**graph_create(unique_name("Invalid")), **change}
    error = json_of(api.post(GRAPHS, json=body), 422)["error"]
    assert error["code"] == "validation_error"
    assert any(line.startswith(where) for line in error["details"]), error["details"]
    assert total(api) == before


def test_the_edges_of_the_graph_limits_are_accepted(api: httpx.Client) -> None:
    body = graph_create("n" * 200, tags=[f"t{i:02d}" for i in range(20)], description="d" * 2000)
    body["tags"][0] = "t" * 40
    created = json_of(api.post(GRAPHS, json=body), 201)
    assert (len(created["name"]), len(created["tags"]), len(created["description"])) == (
        200,
        20,
        2000,
    )


def test_a_copy_is_a_new_graph_with_the_same_content(api: httpx.Client) -> None:
    original = seed_graph(api, unique_name("Original"), graph_draft(LAYERED.csv), tags=["x", "y"])
    before = total(api)
    copy = json_of(api.post(f"{GRAPHS}/{original['id']}/duplicate"), 201)
    assert copy["id"] != original["id"]
    assert copy["name"] == f"{original['name']} (copy)"
    assert (copy["revision"], copy["tags"]) == (1, ["x", "y"])
    for part in ("source", "transform", "style", "description"):
        assert copy[part] == original[part]
    assert total(api) == before + 1
    assert json_of(api.get(f"{GRAPHS}/{original['id']}")) == original  # untouched
    again = json_of(api.post(f"{GRAPHS}/{copy['id']}/duplicate"), 201)
    assert again["name"] == f"{original['name']} (copy) (copy)"
    assert json_of(api.get(f"{GRAPHS}/{copy['id']}/render"))["stats"]["nodes"] == LAYERED.nodes


def test_the_name_of_a_copy_never_goes_over_the_name_limit(api: httpx.Client) -> None:
    long = seed_graph(api, "L" * 200)
    copy = json_of(api.post(f"{GRAPHS}/{long['id']}/duplicate"), 201)
    assert len(copy["name"]) == 200
    assert copy["name"].endswith(" (copy)")
    assert copy["name"].startswith("L" * 193)


def test_a_copy_of_an_unknown_graph_is_a_404(api: httpx.Client) -> None:
    for graph_id in ("0" * 32, "nope"):
        error = json_of(api.post(f"{GRAPHS}/{graph_id}/duplicate"), 404)["error"]
        assert error["code"] == "not_found"


def test_an_edit_bumps_the_revision_and_moves_the_graph_to_the_top(api: httpx.Client) -> None:
    graph = seed_graph(api, unique_name("Edited"))
    newer = seed_graph(api, unique_name("Newer"))
    # so the order below cannot be a tie (instants: text would put "..46Z" after "..46.001Z")
    assert instant(newer["updated_at"]) > instant(graph["updated_at"])
    assert listed_ids(api)[:2] == [newer["id"], graph["id"]]
    changed = json_of(api.put(f"{GRAPHS}/{graph['id']}", json=update_body(graph, description="v2")))
    assert (changed["revision"], changed["description"]) == (2, "v2")
    assert changed["created_at"] == graph["created_at"]
    assert instant(changed["updated_at"]) > instant(newer["updated_at"])
    assert listed_ids(api)[:2] == [graph["id"], newer["id"]]
    stored = json_of(api.get(f"{GRAPHS}/{graph['id']}"))
    assert stored == changed


def test_a_stale_revision_is_a_conflict_that_changes_nothing(api: httpx.Client) -> None:
    graph = seed_graph(api, unique_name("Contended"))
    first = json_of(api.put(f"{GRAPHS}/{graph['id']}", json=update_body(graph, description="mine")))
    stale = api.put(f"{GRAPHS}/{graph['id']}", json=update_body(graph, description="theirs"))
    error = json_of(stale, 409)["error"]
    assert error["code"] == "conflict"
    assert "reload it or save a copy" in error["message"]
    assert error["details"][0] == "revision=2"  # the revision that is stored now
    assert error["details"][1].startswith("updated_at=")
    assert json_of(api.get(f"{GRAPHS}/{graph['id']}"))["description"] == "mine"
    retry = json_of(api.put(f"{GRAPHS}/{graph['id']}", json=update_body(first, description="both")))
    assert (retry["revision"], retry["description"]) == (3, "both")


def test_a_revision_from_the_future_or_a_missing_one_is_not_accepted(api: httpx.Client) -> None:
    graph = seed_graph(api, unique_name("Revisions"))
    future = api.put(f"{GRAPHS}/{graph['id']}", json=update_body(graph, revision=9))
    assert json_of(future, 409)["error"]["code"] == "conflict"
    body = update_body(graph)
    del body["revision"]
    missing = json_of(api.put(f"{GRAPHS}/{graph['id']}", json=body), 422)["error"]
    assert "body.revision: Field required" in missing["details"]
    zero = api.put(f"{GRAPHS}/{graph['id']}", json=update_body(graph, revision=0))
    assert json_of(zero, 422)["error"]["code"] == "validation_error"
    assert json_of(api.get(f"{GRAPHS}/{graph['id']}"))["revision"] == 1


def test_an_edit_of_the_source_changes_what_is_drawn(api: httpx.Client) -> None:
    graph = seed_graph(api, unique_name("Redrawn"))
    render = f"{GRAPHS}/{graph['id']}/render"
    assert json_of(api.get(render))["stats"]["nodes"] == BUDGET.nodes
    source = graph_draft(LAYERED.csv)["source"]
    json_of(api.put(f"{GRAPHS}/{graph['id']}", json=update_body(graph, source=source)))
    assert json_of(api.get(render))["stats"]["nodes"] == LAYERED.nodes


def test_a_deleted_graph_is_gone_everywhere(api: httpx.Client) -> None:
    graph = seed_graph(api, unique_name("Doomed"), tags=["doomed-tag"])
    before = total(api)
    gone = api.delete(f"{GRAPHS}/{graph['id']}")
    assert (gone.status_code, gone.content) == (204, b"")
    assert total(api) == before - 1
    assert graph["id"] not in listed_ids(api)
    assert "doomed-tag" not in json_of(api.get("/api/v1/tags"))
    calls = [
        api.get(f"{GRAPHS}/{graph['id']}"),
        api.get(f"{GRAPHS}/{graph['id']}/render"),
        api.get(f"{GRAPHS}/{graph['id']}/export", params={"format": "csv"}),
        api.get(GRAPHS + "/export", params={"ids": graph["id"]}),
        api.put(f"{GRAPHS}/{graph['id']}", json=update_body(graph)),
        api.post(f"{GRAPHS}/{graph['id']}/duplicate"),
        api.delete(f"{GRAPHS}/{graph['id']}"),
    ]
    for call in calls:
        assert json_of(call, 404)["error"]["code"] == "not_found", call.request.url


@pytest.mark.parametrize("graph_id", ["not-an-id", "0" * 31, "0" * 33, "G" * 32])
def test_a_malformed_graph_id_is_a_404_on_every_path_route(
    api: httpx.Client, graph_id: str
) -> None:
    for call in (
        api.get(f"{GRAPHS}/{graph_id}"),
        api.delete(f"{GRAPHS}/{graph_id}"),
        api.get(f"{GRAPHS}/{graph_id}/render"),
    ):
        assert call.status_code == 404
        assert call.json()["error"]["code"] == "not_found"


def test_graphs_are_deleted_one_at_a_time(api: httpx.Client) -> None:
    keep = seed_graph(api, unique_name("Keep"))
    drop = seed_graph(api, unique_name("Drop"))
    assert api.delete(f"{GRAPHS}/{drop['id']}").status_code == 204
    assert json_of(api.get(f"{GRAPHS}/{keep['id']}")) == keep
