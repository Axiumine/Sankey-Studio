# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The Mongo refusals of E2E.md A.6: unsafe stages, operators and names, and NOTHING written.

``MONGO_GUARDS`` is the pytest parameter list that ``tests/e2e/http`` (mongomock) and
``tests/e2e/mongo`` (real server) both run. Every unsafe source is refused with a 422 that names
the reason but never echoes the pipeline, on every route that takes a source, and the database is
exactly as it was before (``MongoWorld.counts``).
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Final

from tests.e2e.support.clients import json_of
from tests.e2e.support.http_b_mongo_cases import DB, INSPECT_REFUSALS, UNSAFE_CASES, UnsafeCase
from tests.e2e.support.http_b_mongo_flows import (
    BASE,
    FLOW_ENTRIES,
    PREVIEW,
    aggregate,
    finish,
    prepare,
    scenario_param,
)
from tests.e2e.support.http_b_world import DATA_COLLECTION, MAIN, FlowEnv

if TYPE_CHECKING:
    from _pytest.mark.structures import ParameterSet


def check_unsafe_case(env: FlowEnv, case: UnsafeCase) -> None:
    """422 naming the reason, no echo of the pipeline, and the database is exactly as it was."""
    prepare(env)
    before = env.world.counts()
    response = env.api.post(PREVIEW, json=env.world.draft(**case.build(env.world.database)))
    assert response.status_code == 422, case.label
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(case.reason in detail for detail in error["details"]), error["details"]
    assert "smuggled" not in response.text
    assert env.world.counts() == before == {DATA_COLLECTION: len(FLOW_ENTRIES)}
    finish(env)


def check_unsafe_on_every_route(env: FlowEnv) -> None:
    """The same unsafe pipeline is refused by preview, entries, export, create and update."""
    prepare(env)
    api, world = env.api, env.world
    safe = json_of(api.post("/api/v1/graphs", json={"name": "Safe", **world.draft()}), 201)
    unsafe = world.draft(**aggregate({"$out": "smuggled"}))
    attempts = {
        "preview": api.post(PREVIEW, json=unsafe),
        "entries": api.post("/api/v1/entries", json=unsafe),
        "export": api.post("/api/v1/export", params={"format": "csv"}, json=unsafe),
        "create": api.post("/api/v1/graphs", json={"name": "Unsafe", **unsafe}),
        "update": api.put(
            f"/api/v1/graphs/{safe['id']}", json={"name": "Safe", "revision": 1, **unsafe}
        ),
    }
    statuses = {route: response.status_code for route, response in attempts.items()}
    assert statuses == dict.fromkeys(attempts, 422)
    listing = json_of(api.get("/api/v1/graphs"))
    assert [item["name"] for item in listing["items"]] == ["Safe"]
    stored = json_of(api.get(f"/api/v1/graphs/{safe['id']}"))
    assert (stored["revision"], stored["source"]["mode"]) == (1, "find")
    assert world.counts() == {DATA_COLLECTION: len(FLOW_ENTRIES)}
    finish(env)


def check_inspect_guards(env: FlowEnv) -> None:
    """System databases and collections and malformed names are refused before any driver call."""
    prepare(env)
    for path, query, status, code in INSPECT_REFUSALS:
        params = {key: env.world.database if value == DB else value for key, value in query.items()}
        response = env.api.get(f"{BASE}/{MAIN}/{path}", params=params)
        assert response.status_code == status, (path, query)
        assert response.json()["error"]["code"] == code, (path, query)
    unknown = env.api.get(f"{BASE}/nope/databases")
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "source_not_found")
    assert env.world.counts() == {DATA_COLLECTION: len(FLOW_ENTRIES)}
    finish(env)


MONGO_GUARDS: Final[list[ParameterSet]] = [
    *[
        scenario_param(partial(check_unsafe_case, case=case), f"unsafe-{case.label}")
        for case in UNSAFE_CASES
    ],
    scenario_param(check_unsafe_on_every_route, "unsafe-on-every-route"),
    scenario_param(check_inspect_guards, "inspect-guards"),
]
