# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md A.7: switching the graph store between files and MongoDB (mongomock behind the server).

The scenarios live in ``tests.e2e.support.http_b_storage_flows`` and are shared with the real-Mongo
suite (``tests/e2e/mongo``): file -> Mongo with ``migrate=true`` keeps ids and revisions and never
deletes the old store; switching back copies only what is new; a switch without ``migrate`` loses
nothing; a target that does not answer leaves the old backend active and ``settings.json``
untouched; a damaged graph file is counted, not fatal. The test below adds the one thing only the
in-memory server can do: the ACTIVE Mongo store going down and coming back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import graph_create
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.http_b_mongo_flows import SETTINGS, configure, finish, put_settings
from tests.e2e.support.http_b_storage_flows import (
    GRAPHS,
    STORAGE_FLOWS,
    active_backend,
    library,
    seed_library,
    storage_body,
    switch,
)
from tests.e2e.support.http_b_world import MAIN, mongomock_world, open_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv
    from tests.e2e.support.server import ServerFactory


@pytest.fixture
def env(make_server: ServerFactory) -> Iterator[FlowEnv]:
    with open_env(make_server, mongomock_world()) as flow_env:
        yield flow_env


@pytest.mark.parametrize("scenario", STORAGE_FLOWS)
def test_storage_flow(env: FlowEnv, scenario: Scenario) -> None:
    scenario(env)


def test_the_active_mongo_store_going_down_is_a_503_and_the_backend_does_not_change(
    env: FlowEnv,
) -> None:
    configure(env)
    before = seed_library(env, 2)
    assert json_of(switch(env, storage_body(env, "mongo", MAIN), migrate=True))["copy_report"]
    assert env.world.outage is not None
    env.world.outage(True)
    listing = env.api.get(GRAPHS)
    creating = env.api.post(GRAPHS, json=graph_create("While down"))
    for refused in (listing, creating):
        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == "storage_error"
    leaving = switch(env, storage_body(env, "file"), migrate=True)  # the copy cannot read Mongo
    assert (leaving.status_code, leaving.json()["error"]["code"]) == (503, "storage_error")
    assert active_backend(env) == ("mongo", MAIN)
    assert env.api.get(SETTINGS).status_code == 200  # settings are local, not on the Mongo store
    assert put_settings(env, theme="dark")["settings"]["theme"] == "dark"  # and stay editable
    assert active_backend(env) == ("mongo", MAIN)
    env.world.outage(False)
    assert library(env) == before
    assert seed_graph(env.api, "After the outage")["revision"] == 1
    finish(env)
