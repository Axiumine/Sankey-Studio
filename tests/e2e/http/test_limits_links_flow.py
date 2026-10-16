# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md A.9, part 1: ``max_links`` (413) and cycles (422, ``on_cycle=break`` -> 200 + warning).

The cap counts the links of the SOURCE (rows or documents that give a link), before merging; it is
a live setting. A cycle is refused with the chain of nodes in the message unless it is broken.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import CYCLE, csv_text, graph_draft, many_links, unique_name
from tests.e2e.support.clients import json_of, make_client, seed_graph
from tests.e2e.support.http_b_limits import API, change_settings
from tests.e2e.support.http_b_mongo_flows import configure, preview
from tests.e2e.support.http_b_world import mongomock_world, open_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

    from tests.e2e.support.http_b_world import FlowEnv
    from tests.e2e.support.server import LiveServer, ServerFactory

CAP = 100
TOO_MANY = (
    f"The source has more than {CAP} links; raise max_links in the settings or narrow the data"
)


@pytest.fixture(scope="module")
def capped_server(module_make_server: ServerFactory) -> LiveServer:
    """One server with ``max_links`` = 100 for the tests that do not change the settings."""
    return module_make_server(settings={"max_links": CAP})


@pytest.fixture
def live_server(capped_server: LiveServer) -> LiveServer:
    return capped_server


def draft_of(links: int) -> dict[str, Any]:
    return graph_draft(many_links(links).csv)


# ------------------------------------------------------------------------------ max_links


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"{API}/preview"),
        ("POST", f"{API}/entries"),
        ("POST", f"{API}/export?format=csv"),
        ("POST", f"{API}/export?format=json"),
    ],
)
def test_one_link_over_the_cap_is_a_413_and_the_cap_itself_is_drawn(
    api: httpx.Client, method: str, path: str
) -> None:
    at_cap = api.request(method, path, json=draft_of(CAP))
    assert at_cap.status_code == 200
    over = api.request(method, path, json=draft_of(CAP + 1))
    assert over.status_code == 413
    assert over.json() == {"error": {"code": "graph_too_large", "message": TOO_MANY, "details": []}}


def test_a_saved_graph_over_the_cap_is_kept_but_cannot_be_drawn_or_exported(
    api: httpx.Client,
) -> None:
    big = seed_graph(api, unique_name("big"), draft_of(CAP + 1))  # saving does not draw
    ok = seed_graph(api, unique_name("ok"), draft_of(CAP))
    for suffix, params in (("render", {}), ("export", {"format": "csv"})):
        refused = api.get(f"{API}/graphs/{big['id']}/{suffix}", params=params)
        assert (refused.status_code, refused.json()["error"]["code"]) == (413, "graph_too_large")
    assert (
        api.get(f"{API}/compare/render", params={"ids": f"{ok['id']},{big['id']}"}).status_code
        == 413
    )
    drawn = json_of(api.get(f"{API}/graphs/{ok['id']}/render"))
    assert drawn["stats"]["links"] == CAP
    assert api.get(f"{API}/graphs/{big['id']}").status_code == 200  # still editable and listed


def test_the_cap_counts_the_rows_of_the_source_not_the_distinct_pairs(api: httpx.Client) -> None:
    rows = csv_text([("A", "B", 1)] * (CAP + 1))
    response = api.post(f"{API}/preview", json=graph_draft(rows))
    assert (response.status_code, response.json()["error"]["code"]) == (413, "graph_too_large")
    fewer = api.post(f"{API}/preview", json=graph_draft(csv_text([("A", "B", 1)] * CAP)))
    assert json_of(fewer)["stats"]["links"] == 1


def test_the_cap_is_a_live_setting(make_server: ServerFactory) -> None:
    with make_client(make_server(settings={"max_links": CAP})) as api:
        saved = seed_graph(api, unique_name("live"), draft_of(CAP + 1))
        render = f"{API}/graphs/{saved['id']}/render"
        assert api.get(render).status_code == 413
        assert change_settings(api, max_links=CAP + 50).status_code == 200
        assert json_of(api.get(render))["stats"]["links"] == CAP + 1
        assert change_settings(api, max_links=CAP).status_code == 200
        again = api.get(render)
        assert (again.status_code, again.json()["error"]["code"]) == (413, "graph_too_large")


# ------------------------------------------------------------------------------ Mongo documents


@pytest.fixture
def mongo_env(make_server: ServerFactory) -> Iterator[FlowEnv]:
    with open_env(make_server, mongomock_world(), {"max_links": CAP}) as env:
        yield env


def test_mongo_documents_count_against_the_cap_only_when_they_give_a_link(
    mongo_env: FlowEnv,
) -> None:
    configure(mongo_env)
    world = mongo_env.world
    world.insert("usable", [{"from": f"S{n}", "to": "T", "amount": 1} for n in range(CAP)])
    world.insert("usable", [{"from": "S", "to": "T"} for _ in range(50)])  # no value: skipped
    drawn = preview(mongo_env, collection="usable", category_field=None)
    assert drawn["stats"]["links"] == CAP
    assert len(drawn["warnings"]) == 50
    world.insert("usable", [{"from": "SX", "to": "T", "amount": 1}])
    over = mongo_env.api.post(f"{API}/preview", json=world.draft(collection="usable"))
    assert (over.status_code, over.json()["error"]["code"]) == (413, "graph_too_large")


# ------------------------------------------------------------------------------ cycles

CYCLE_MESSAGE = (
    "The links form a cycle: A -> B -> C -> A. "
    "Set on_cycle to 'break' to drop the links that close it"
)
SHAPES = (
    pytest.param(csv_text([("A", "B", 1), ("B", "A", 1)]), "A -> B -> A", id="two-nodes"),
    pytest.param(csv_text([("A", "A", 1)]), "A -> A", id="self-loop"),
    pytest.param(
        csv_text([("In", "A", 5), ("A", "B", 2), ("A", "C", 3), ("B", "D", 2), ("D", "A", 1)]),
        "A -> B -> D -> A",
        id="inside-a-bigger-graph",
    ),
)


def test_a_cycle_is_a_422_with_the_chain_of_nodes(api: httpx.Client) -> None:
    refused = api.post(f"{API}/preview", json=graph_draft(CYCLE.csv))
    assert refused.status_code == 422
    assert refused.json() == {
        "error": {"code": "graph_build_error", "message": CYCLE_MESSAGE, "details": []}
    }


def test_breaking_the_cycle_draws_the_rest_and_warns(api: httpx.Client) -> None:
    broken = json_of(
        api.post(f"{API}/preview", json=graph_draft(CYCLE.csv, transform={"on_cycle": "break"}))
    )
    assert broken["warnings"] == ["Removed 1 link(s) that closed a cycle"]
    assert (broken["stats"]["nodes"], broken["stats"]["links"]) == (4, 3)
    pairs = {(row["source"], row["target"]): row["value"] for row in broken["entries"]}
    assert pairs == {("Start", "A"): 4.0, ("A", "B"): 5.0, ("B", "C"): 3.0}  # C -> A closed it


@pytest.mark.parametrize(("content", "chain"), SHAPES)
def test_every_shape_of_cycle_is_refused_and_can_be_broken(
    api: httpx.Client, content: str, chain: str
) -> None:
    refused = api.post(f"{API}/preview", json=graph_draft(content))
    assert refused.status_code == 422
    assert chain in refused.json()["error"]["message"]
    broken = api.post(f"{API}/preview", json=graph_draft(content, transform={"on_cycle": "break"}))
    assert broken.status_code == 200
    assert broken.json()["warnings"] == ["Removed 1 link(s) that closed a cycle"]


def test_a_saved_graph_with_a_cycle_is_fixed_by_choosing_to_break_it(api: httpx.Client) -> None:
    saved = seed_graph(api, unique_name("cycle"), graph_draft(CYCLE.csv))  # saving is allowed
    render = f"{API}/graphs/{saved['id']}/render"
    assert api.get(render).status_code == 422
    assert (
        api.get(f"{API}/graphs/{saved['id']}/export", params={"format": "csv"}).status_code == 422
    )
    body = {
        "name": saved["name"],
        "source": saved["source"],
        "transform": {**saved["transform"], "on_cycle": "break"},
        "style": saved["style"],
        "revision": saved["revision"],
    }
    assert api.put(f"{API}/graphs/{saved['id']}", json=body).status_code == 200
    fixed = json_of(api.get(render))
    assert fixed["warnings"] == ["Removed 1 link(s) that closed a cycle"]
    assert fixed["stats"]["links"] == 3
