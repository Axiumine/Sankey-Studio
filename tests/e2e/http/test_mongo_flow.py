"""E2E.md A.6, first half: MongoDB through the live API (mongomock behind the server).

The scenarios live in ``tests.e2e.support.http_b_mongo_flows`` and are shared with the real-Mongo
suite (``tests/e2e/mongo``, section C): connection -> databases -> collections -> sample ->
suggested fields -> preview; ``find`` filters and ``aggregate`` pipelines (the values come from
the pipeline, so it really ran); counting mode; the truncation warning; a saved Mongo graph; a
server that does not answer. The refusals (unsafe stages, system databases) are in
``test_mongo_guards_flow``. The tests below are what only the in-memory server can do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.clients import json_of
from tests.e2e.support.http_b_mongo_flows import (
    BASE,
    FLOW_ENTRIES,
    MONGO_FLOWS,
    MONGO_QUERIES,
    PREVIEW,
    configure,
    entries_of,
    finish,
    prepare,
    preview,
    put_settings,
)
from tests.e2e.support.http_b_world import MAIN, NEIGHBOUR, mongomock_world, open_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv
    from tests.e2e.support.server import ServerFactory


@pytest.fixture
def env(make_server: ServerFactory) -> Iterator[FlowEnv]:
    with open_env(make_server, mongomock_world()) as flow_env:
        yield flow_env


@pytest.fixture(scope="module")
def shared_env(module_make_server: ServerFactory) -> Iterator[FlowEnv]:
    """One server and one world for the independent query cases (they only read)."""
    with open_env(module_make_server, mongomock_world()) as flow_env:
        yield flow_env


@pytest.mark.parametrize("scenario", MONGO_QUERIES)
def test_mongo_query(shared_env: FlowEnv, scenario: Scenario) -> None:
    scenario(shared_env)


@pytest.mark.parametrize("scenario", MONGO_FLOWS)
def test_mongo_flow(env: FlowEnv, scenario: Scenario) -> None:
    scenario(env)


def test_the_server_going_down_and_coming_back_is_reported_not_hidden(env: FlowEnv) -> None:
    prepare(env)
    assert env.world.outage is not None
    env.world.outage(True)
    probe = env.api.post(f"/api/v1/settings/mongo/{MAIN}/test")
    listing = env.api.get(f"{BASE}/{MAIN}/databases")
    drawn = env.api.post(PREVIEW, json=env.world.draft())
    assert (probe.status_code, listing.status_code, drawn.status_code) == (503, 422, 422)
    assert "is unreachable" in drawn.json()["error"]["message"]
    assert "mongo.invalid" not in drawn.text
    env.world.outage(False)
    assert entries_of(preview(env)) == FLOW_ENTRIES
    finish(env)


def test_a_connection_is_usable_right_after_it_is_saved_and_gone_after_it_is_removed(
    env: FlowEnv,
) -> None:
    env.world.seed()
    assert env.api.get(f"{BASE}/{MAIN}/databases").status_code == 404
    configure(env)
    listed = json_of(env.api.get(f"{BASE}/{MAIN}/databases"))
    assert listed == sorted([env.world.database, NEIGHBOUR])  # admin, local, config are hidden
    assert put_settings(env, mongo_connections=[])["settings"]["mongo_connections"] == []
    gone = env.api.post(PREVIEW, json=env.world.draft())
    assert (gone.status_code, gone.json()["error"]["code"]) == (404, "source_not_found")
    finish(env)
