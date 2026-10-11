"""The Mongo flows of E2E.md A.6, written once for mongomock (A) and a real server (C).

Each ``check_*`` function is one scenario over a ``FlowEnv`` (``http_b_world``): it seeds the
world, drives the live API and asserts what the API shows (status, error envelope, bundle) and
what the database holds. ``MONGO_QUERIES`` and ``MONGO_FLOWS`` are the pytest parameter lists that
``tests/e2e/http`` (mongomock) and ``tests/e2e/mongo`` (real server) both run:

* connection -> databases -> collections -> sample -> suggested fields -> preview;
* ``find`` filters and ``aggregate`` pipelines (the values come from the pipeline);
* counting mode, the truncation warning, a saved Mongo graph, a server that does not answer.

The refusals (unsafe stages, system databases) are in ``http_b_mongo_guards``. No scenario reads
or writes outside ``world.database``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Final

import pytest

from tests.e2e.support.clients import json_of
from tests.e2e.support.http_b_world import (
    DATA_COLLECTION,
    DEAD,
    DEAD_URI,
    MAIN,
    FlowEnv,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from _pytest.mark.structures import ParameterSet

Scenario = Callable[[FlowEnv], None]
Entries = dict[tuple[str, str], float]

BASE: Final = "/api/v1/mongo"
SETTINGS: Final = "/api/v1/settings"
PREVIEW: Final = "/api/v1/preview"
SYSTEM_DATABASES: Final = frozenset({"admin", "local", "config"})
SUGGESTED: Final = {"source": "from", "target": "to", "value": "amount", "category": "kind"}
CATEGORIES: Final = {"Income", "Housing", "Food", "Transport", "Savings"}
FLOW_ENTRIES: Final[Entries] = {
    ("Salary", "Account"): 3000.0,
    ("Account", "Rent"): 1200.0,
    ("Account", "Food"): 640.0,
    ("Account", "Transport"): 230.0,
    ("Account", "Savings"): 930.0,
}
EVENTS: Final = "events"
UNREACHABLE: Final = "is unreachable"


# ------------------------------------------------------------------------------ helpers


def entries_of(bundle: Mapping[str, Any]) -> Entries:
    """``{(source, target): value}`` of a render bundle's entries."""
    return {(row["source"], row["target"]): row["value"] for row in bundle["entries"]}


def current_settings(env: FlowEnv) -> dict[str, Any]:
    """``GET /settings`` as a ``PUT`` body: ``PUT`` replaces the whole document, so a change is
    always read-modify-write. The masked connections keep their stored secret when sent back."""
    settings: dict[str, Any] = dict(json_of(env.api.get(SETTINGS)))
    settings.pop("bootstrap")
    return settings


def put_settings(env: FlowEnv, **changes: Any) -> dict[str, Any]:
    """Save the current settings with ``changes`` applied; the ``SettingsSaved`` answer."""
    body = {**current_settings(env), **changes}
    return dict(json_of(env.api.put(SETTINGS, json=body)))


def configure(env: FlowEnv) -> dict[str, Any]:
    """Add the good and the dead connection (``PUT /settings``); returns the saved settings."""
    world = env.world
    connections = [world.connection(), world.connection(DEAD, DEAD_URI)]
    saved: dict[str, Any] = put_settings(env, mongo_connections=connections)["settings"]
    connections = saved["mongo_connections"]
    assert [c["name"] for c in connections] == [MAIN, DEAD]
    assert all("uri" not in c and c["has_secret"] is True for c in connections)
    assert not any(secret in connections[0]["uri_masked"] for secret in world.secrets)
    return saved


def prepare(env: FlowEnv) -> None:
    """Seed ``transfers`` and add the two connections."""
    env.world.seed()
    configure(env)


def preview(env: FlowEnv, **fields: Any) -> dict[str, Any]:
    """``POST /preview`` over ``transfers`` (``fields`` override the source); the bundle."""
    return dict(json_of(env.api.post(PREVIEW, json=env.world.draft(**fields))))


def finish(env: FlowEnv) -> None:
    """Every scenario ends here: no response of the whole scenario held a secret."""
    env.tape.assert_clean(env.world.secrets)


# ------------------------------------------------------------------------------ the chain


def check_connection_chain(env: FlowEnv) -> None:
    """Connection -> databases -> collections -> sample -> suggested fields -> preview."""
    world, api = env.world, env.api
    world.seed()
    saved = configure(env)
    assert saved["mongo_connections"][0]["default_database"] == world.database
    probe = json_of(api.post(f"/api/v1/settings/mongo/{MAIN}/test"))
    assert probe["ok"] is True
    assert probe["latency_ms"] >= 0
    databases = json_of(api.get(f"{BASE}/{MAIN}/databases"))
    assert world.database in databases
    assert SYSTEM_DATABASES.isdisjoint(databases)
    names = json_of(api.get(f"{BASE}/{MAIN}/collections", params={"database": world.database}))
    assert names == [DATA_COLLECTION]
    suggested = check_sample(env)
    check_preview_from(env, suggested)
    finish(env)


def check_sample(env: FlowEnv) -> dict[str, Any]:
    """The sample answer: bounded JSON-safe documents and the suggested field mapping."""
    params: dict[str, str | int] = {
        "database": env.world.database,
        "collection": DATA_COLLECTION,
        "n": 3,
    }
    sample = json_of(env.api.get(f"{BASE}/{MAIN}/sample", params=params))
    assert len(sample["documents"]) == 3
    assert all(isinstance(doc["_id"], str) for doc in sample["documents"])
    assert all({"from", "to", "amount", "kind"} <= set(doc) for doc in sample["documents"])
    assert sample["suggested"] == SUGGESTED
    return dict(sample["suggested"])


def check_preview_from(env: FlowEnv, suggested: Mapping[str, Any]) -> None:
    """A preview that uses exactly the suggested mapping draws the whole collection."""
    bundle = preview(
        env,
        source_field=suggested["source"],
        target_field=suggested["target"],
        value_field=suggested["value"],
        category_field=suggested["category"],
    )
    assert entries_of(bundle) == FLOW_ENTRIES
    stats = bundle["stats"]
    assert (stats["nodes"], stats["links"], stats["total_in"]) == (6, 5, 3000.0)
    assert bundle["donut_available"] is True
    assert set(bundle["category_names"]) == CATEGORIES
    assert bundle["warnings"] == []


# ------------------------------------------------------------------------------ find / aggregate


@dataclass(frozen=True, slots=True)
class QueryCase:
    """A ``find`` filter or ``aggregate`` pipeline and the links it must produce."""

    label: str
    source: Mapping[str, Any]
    expected: Entries


def _pick(*pairs: tuple[str, str]) -> Entries:
    return {pair: FLOW_ENTRIES[pair] for pair in pairs}


def aggregate(*stages: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    return {"mode": "aggregate", "pipeline": list(stages), **fields}


_GROUP = {"$group": {"_id": {"s": "$from", "t": "$to"}, "total": {"$sum": "$amount"}}}
_FLAT = {"$project": {"_id": 0, "from": "$_id.s", "to": "$_id.t", "total": 1}}
QUERY_CASES: Final = (
    QueryCase("find-all", {}, FLOW_ENTRIES),
    QueryCase(
        "find-filter",
        {"filter": {"amount": {"$gte": 900}}},
        _pick(("Salary", "Account"), ("Account", "Rent"), ("Account", "Savings")),
    ),
    QueryCase("find-category", {"filter": {"kind": "Food"}}, _pick(("Account", "Food"))),
    QueryCase(
        "aggregate-match",
        aggregate({"$match": {"kind": {"$in": ["Housing", "Transport"]}}}),
        _pick(("Account", "Rent"), ("Account", "Transport")),
    ),
    QueryCase(
        "aggregate-sort-limit",
        aggregate({"$sort": {"amount": -1}}, {"$limit": 2}),
        _pick(("Salary", "Account"), ("Account", "Rent")),
    ),
    QueryCase(
        "aggregate-computed-value",
        aggregate({"$addFields": {"amount": {"$multiply": ["$amount", 2]}}}),
        {pair: value * 2 for pair, value in FLOW_ENTRIES.items()},
    ),
    QueryCase(
        "aggregate-lookup-same-database",  # a join inside the database is allowed
        aggregate(
            {
                "$lookup": {
                    "from": DATA_COLLECTION,
                    "localField": "to",
                    "foreignField": "from",
                    "as": "next",
                }
            },
            {"$match": {"next": {"$ne": []}}},
        ),
        _pick(("Salary", "Account")),
    ),
    QueryCase(
        "aggregate-group",
        aggregate(_GROUP, _FLAT, value_field="total", category_field=None),
        FLOW_ENTRIES,
    ),
)


def check_query_case(env: FlowEnv, case: QueryCase) -> None:
    """The preview of ``case`` has exactly the expected links, with their values."""
    prepare(env)
    bundle = preview(env, **case.source)
    assert entries_of(bundle) == case.expected, case.label
    assert bundle["stats"]["links"] == len(case.expected)
    assert bundle["warnings"] == []
    finish(env)


# ------------------------------------------------------------------------------ counting, limit


def check_counting_mode(env: FlowEnv) -> None:
    """``value_field: null`` counts documents per (source, target); a missing field is skipped."""
    prepare(env)
    pairs = [("A", "B")] * 3 + [("A", "C")] * 2 + [("B", "D")]
    env.world.insert(EVENTS, [{"from": s, "to": t} for s, t in pairs])
    counted = preview(env, collection=EVENTS, value_field=None, category_field=None)
    assert entries_of(counted) == {("A", "B"): 3.0, ("A", "C"): 2.0, ("B", "D"): 1.0}
    assert counted["warnings"] == []
    # the same documents with a value field they do not have: every document is reported
    missing = preview(env, collection=EVENTS, category_field=None)
    assert missing["stats"]["links"] == 0
    assert len(missing["warnings"]) == len(pairs)
    assert "'amount' is missing" in missing["warnings"][0]
    finish(env)


def check_truncation(env: FlowEnv) -> None:
    """``limit`` below the document count warns; above it does not (find and aggregate)."""
    prepare(env)
    cut = preview(env, limit=3)
    assert "Result truncated at limit 3" in cut["warnings"]
    rows = entries_of(cut)
    assert len(rows) == 3
    assert all(FLOW_ENTRIES[pair] == value for pair, value in rows.items())
    full = preview(env, limit=100)
    assert not [w for w in full["warnings"] if "truncated" in w]
    assert entries_of(full) == FLOW_ENTRIES
    piped = preview(env, **aggregate({"$match": {}}, limit=2))
    assert "Result truncated at limit 2" in piped["warnings"]
    assert piped["stats"]["links"] == 2
    finish(env)


def check_truncation_boundary(env: FlowEnv) -> None:
    """A collection of exactly ``limit`` documents loses nothing, so it must not claim it did.

    The source asks the server for one document more than ``limit``; only that extra document
    makes it warn, so ``limit`` == the document count is silent and one less is not.
    """
    prepare(env)
    exact = preview(env, limit=len(FLOW_ENTRIES))
    assert entries_of(exact) == FLOW_ENTRIES  # every document was read
    assert exact["warnings"] == []
    short = preview(env, limit=len(FLOW_ENTRIES) - 1)
    assert f"Result truncated at limit {len(FLOW_ENTRIES) - 1}" in short["warnings"]
    finish(env)


# ------------------------------------------------------------------------------ saved graph


def check_saved_graph(env: FlowEnv) -> None:
    """A saved Mongo graph stores the connection NAME, renders and exports like the preview."""
    prepare(env)
    api, world = env.api, env.world
    created = json_of(
        api.post("/api/v1/graphs", json={"name": "Mongo flows", **world.draft()}), 201
    )
    assert created["source"]["connection"] == MAIN
    assert created["source"]["database"] == world.database
    rendered = json_of(api.get(f"/api/v1/graphs/{created['id']}/render"))
    assert entries_of(rendered) == FLOW_ENTRIES
    export = api.get(f"/api/v1/graphs/{created['id']}/export", params={"format": "csv"})
    assert export.status_code == 200
    assert export.text.splitlines()[0] == "source,target,value,category"
    assert len(export.text.splitlines()) == 1 + len(FLOW_ENTRIES)
    bundle = json_of(api.get("/api/v1/graphs/export", params={"ids": created["id"]}))
    assert bundle["graphs"][0]["source"]["connection"] == MAIN
    on_disk = "".join(path.read_text() for path in env.server.graphs_dir.glob("*.json"))
    assert on_disk
    assert not [s for s in world.secrets if s in on_disk or s in str(bundle)]
    finish(env)


# ------------------------------------------------------------------------------ dead server


def check_dead_connection(env: FlowEnv) -> None:
    """A server that does not answer: 422 / 503 envelopes naming the connection, no host or URI."""
    prepare(env)
    api = env.api
    probe = api.post(f"/api/v1/settings/mongo/{DEAD}/test")
    listing = api.get(f"{BASE}/{DEAD}/databases")
    drawn = api.post(PREVIEW, json=env.world.draft(connection=DEAD))
    assert (probe.status_code, listing.status_code, drawn.status_code) == (503, 422, 422)
    assert probe.json()["error"]["code"] == "storage_error"
    for response in (probe, listing, drawn):
        message = response.json()["error"]["message"]
        assert message == f"MongoDB connection '{DEAD}' {UNREACHABLE}"
        assert "invalid" not in response.text
    assert entries_of(preview(env)) == FLOW_ENTRIES  # the good connection is unaffected
    finish(env)


# ------------------------------------------------------------------------------ the list


def scenario_param(scenario: Scenario, label: str) -> ParameterSet:
    """A pytest parameter for ``scenario`` with a readable id."""
    return pytest.param(scenario, id=label)


#: Independent of each other and of the order: a suite may run them on one shared server.
MONGO_QUERIES: Final[list[ParameterSet]] = [
    scenario_param(partial(check_query_case, case=case), f"query-{case.label}")
    for case in QUERY_CASES
]
#: Each one needs a server of its own (they add collections, graphs or connections).
MONGO_FLOWS: Final[list[ParameterSet]] = [
    scenario_param(check_connection_chain, "connection-chain"),
    scenario_param(check_counting_mode, "counting-mode"),
    scenario_param(check_truncation, "truncation-warning"),
    scenario_param(check_truncation_boundary, "truncation-at-exactly-the-limit"),
    scenario_param(check_saved_graph, "saved-graph"),
    scenario_param(check_dead_connection, "dead-connection"),
]
