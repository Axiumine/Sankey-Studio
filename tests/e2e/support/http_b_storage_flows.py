# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The storage-backend flows of E2E.md A.7, written once for mongomock (A) and a real server (C).

File store -> Mongo store with ``migrate``, back again, a switch without ``migrate`` that loses
nothing, a target that does not answer (the old backend stays active, ``settings.json`` is
byte-identical), and a damaged graph file that is counted instead of blocking the copy.
``STORAGE_FLOWS`` is the pytest parameter list both suites run. The graph store of Mongo lives in
``world.database``, next to the source collections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from sankey_studio.storage.base import MONGO_GRAPHS_COLLECTION
from tests.e2e.support.builders import (
    BUDGET,
    BUDGET_CATEGORISED,
    LAYERED,
    graph_create,
    graph_draft,
)
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.http_b_mongo_flows import (
    SETTINGS,
    configure,
    current_settings,
    finish,
    scenario_param,
)
from tests.e2e.support.http_b_world import DEAD, MAIN, FlowEnv

if TYPE_CHECKING:
    import httpx
    from _pytest.mark.structures import ParameterSet

GRAPHS: Final = "/api/v1/graphs"
SAMPLES: Final = (BUDGET, BUDGET_CATEGORISED, LAYERED)
NO_REPORT: Final = {
    "copied": 0,
    "skipped": 0,
    "unreadable": 0,
    "unreadable_ids": [],
    "folders": 0,
    "folders_skipped": 0,
}
DAMAGED_ID: Final = "0" * 31 + "b"


# ------------------------------------------------------------------------------ helpers


def storage_body(env: FlowEnv, backend: str, connection: str | None = None) -> dict[str, Any]:
    """The current settings with another storage target (a full ``PUT`` body)."""
    target = {
        "storage_backend": backend,
        "storage_connection": connection,
        "storage_database": env.world.database,
    }
    return {**current_settings(env), **target}


def switch(env: FlowEnv, body: dict[str, Any], *, migrate: bool) -> httpx.Response:
    """``PUT /settings?migrate=...`` with ``body``."""
    flag = "true" if migrate else "false"
    return env.api.put(SETTINGS, params={"migrate": flag}, json=body)


def seed_library(env: FlowEnv, count: int = 3) -> dict[str, dict[str, Any]]:
    """``count`` saved graphs in the current store; the last one is edited once (revision 2)."""
    graphs: dict[str, dict[str, Any]] = {}
    for number in range(count):
        sample = SAMPLES[number % len(SAMPLES)]
        graph = seed_graph(env.api, f"Library {number}", graph_draft(sample.csv))
        graphs[graph["id"]] = graph
    last = graph  # the loop ran at least once
    edit = {**graph_create(last["name"], graph_draft(SAMPLES[-1].csv)), "revision": 1}
    edit["description"] = "edited once"
    graphs[last["id"]] = json_of(env.api.put(f"{GRAPHS}/{last['id']}", json=edit))
    return graphs


def library(env: FlowEnv) -> dict[str, dict[str, Any]]:
    """Every graph of the current store as ``GET /graphs/{id}`` shows it, by id."""
    listing = json_of(env.api.get(GRAPHS))
    return {item["id"]: json_of(env.api.get(f"{GRAPHS}/{item['id']}")) for item in listing["items"]}


def stored_in_mongo(env: FlowEnv) -> int:
    """How many graph documents the Mongo store of the world holds."""
    return env.world.counts().get(MONGO_GRAPHS_COLLECTION, 0)


def files_on_disk(env: FlowEnv) -> list[str]:
    """The ids of the graph files of the file store."""
    return sorted(path.stem for path in env.server.graphs_dir.glob("*.json"))


def active_backend(env: FlowEnv) -> tuple[str, str | None]:
    """``(storage_backend, storage_connection)`` as ``GET /settings`` reports them."""
    settings = json_of(env.api.get(SETTINGS))
    return settings["storage_backend"], settings["storage_connection"]


# ------------------------------------------------------------------------------ the flows


def check_switch_there_and_back(env: FlowEnv) -> None:
    """file -> mongo with migrate copies every graph with its id and revision; and back."""
    configure(env)
    before = seed_library(env)
    assert {graph["revision"] for graph in before.values()} == {1, 2}
    candidate = storage_body(env, "mongo", MAIN)
    assert json_of(env.api.post(f"{SETTINGS}/storage/test", json=candidate)) == {"ok": True}
    assert active_backend(env) == ("file", None)  # a probe saves nothing
    saved = json_of(switch(env, candidate, migrate=True))
    assert saved["copy_report"] == {**NO_REPORT, "copied": 3}
    assert active_backend(env) == ("mongo", MAIN)
    assert library(env) == before  # same ids, revisions, content
    assert stored_in_mongo(env) == 3
    assert files_on_disk(env) == sorted(before)  # the old store is never deleted
    check_new_graph_goes_to_the_active_store(env, before)
    finish(env)


def check_new_graph_goes_to_the_active_store(env: FlowEnv, before: dict[str, Any]) -> None:
    """A graph made on Mongo is in Mongo only; switching back copies just that one."""
    fresh = seed_graph(env.api, "Made on Mongo")
    assert stored_in_mongo(env) == 4
    assert files_on_disk(env) == sorted(before)
    saved = json_of(switch(env, storage_body(env, "file"), migrate=True))
    assert saved["copy_report"] == {**NO_REPORT, "copied": 1, "skipped": 3}
    assert active_backend(env) == ("file", None)
    assert sorted(library(env)) == sorted([*before, fresh["id"]])
    assert files_on_disk(env) == sorted([*before, fresh["id"]])
    assert env.api.get(f"{GRAPHS}/{fresh['id']}/render").status_code == 200


def check_switch_without_migrate(env: FlowEnv) -> None:
    """Without migrate nothing is copied and nothing is deleted: the stores stay separate."""
    configure(env)
    before = seed_library(env, 2)
    saved = json_of(switch(env, storage_body(env, "mongo", MAIN), migrate=False))
    assert saved["copy_report"] is None
    assert json_of(env.api.get(GRAPHS))["total"] == 0  # the Mongo store starts empty
    assert files_on_disk(env) == sorted(before)
    seed_graph(env.api, "Only on Mongo")
    assert stored_in_mongo(env) == 1
    assert json_of(switch(env, storage_body(env, "file"), migrate=False))["copy_report"] is None
    assert library(env) == before  # the file graphs are back, the Mongo-only one is not copied
    assert stored_in_mongo(env) == 1
    finish(env)


def check_failed_target_keeps_the_old_backend(env: FlowEnv) -> None:
    """A target that does not answer: 503, the file backend stays active, settings untouched."""
    configure(env)
    before = seed_library(env, 2)
    stored = env.server.settings_file.read_bytes()
    dead = storage_body(env, "mongo", DEAD)
    for attempt in (switch(env, dead, migrate=True), switch(env, dead, migrate=False)):
        assert attempt.status_code == 503
        assert attempt.json()["error"]["code"] == "storage_error"
        assert attempt.json()["error"]["message"] == f"MongoDB connection '{DEAD}' is unreachable"
        assert "invalid" not in attempt.text
    probe = env.api.post(f"{SETTINGS}/storage/test", json=dead)
    assert (probe.status_code, probe.json()["error"]["code"]) == (503, "storage_error")
    assert active_backend(env) == ("file", None)
    assert env.server.settings_file.read_bytes() == stored
    assert library(env) == before
    seed_graph(env.api, "Still on files")
    assert len(files_on_disk(env)) == 3
    saved = json_of(switch(env, storage_body(env, "mongo", MAIN), migrate=True))
    assert saved["copy_report"] == {**NO_REPORT, "copied": 3}  # the next switch is not wedged
    finish(env)


def check_damaged_graph_is_counted(env: FlowEnv) -> None:
    """A damaged graph file is reported and left behind; the readable graphs are copied."""
    configure(env)
    before = seed_library(env, 2)
    damaged = env.server.graphs_dir / f"{DAMAGED_ID}.json"
    damaged.write_bytes(b"{broken")
    saved = json_of(switch(env, storage_body(env, "mongo", MAIN), migrate=True))
    assert saved["copy_report"] == {
        **NO_REPORT,
        "copied": 2,
        "unreadable": 1,
        "unreadable_ids": [DAMAGED_ID],
    }
    assert library(env) == before
    assert damaged.read_bytes() == b"{broken"
    finish(env)


def check_invalid_targets_are_refused(env: FlowEnv) -> None:
    """Mongo storage needs a configured connection; the answer is a 422, nothing changes."""
    configure(env)
    before = seed_library(env, 1)
    stored = env.server.settings_file.read_bytes()
    for connection in (None, "nope"):
        refused = switch(env, storage_body(env, "mongo", connection), migrate=True)
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "settings_error"
    assert env.server.settings_file.read_bytes() == stored
    assert active_backend(env) == ("file", None)
    assert library(env) == before
    finish(env)


STORAGE_FLOWS: Final[list[ParameterSet]] = [
    scenario_param(check_switch_there_and_back, "switch-there-and-back"),
    scenario_param(check_switch_without_migrate, "switch-without-migrate"),
    scenario_param(check_failed_target_keeps_the_old_backend, "failed-target-keeps-old-backend"),
    scenario_param(check_damaged_graph_is_counted, "damaged-graph-is-counted"),
    scenario_param(check_invalid_targets_are_refused, "invalid-targets-are-refused"),
]
