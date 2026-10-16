# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The MongoDB write-back flows of ``/edits/plan`` and ``/edits/write``, written once for
mongomock (``tests/e2e/http``) and a real server (``tests/e2e/mongo``).

Each ``check_*`` function is one scenario over a ``FlowEnv`` (``http_b_world``): it seeds the
``transfers`` collection (five documents), drives the live API like the editor does (``plan`` first,
the saved consent in ``source.write_back.target``, then ``write``) and asserts what the API says
and what the collection holds. ``EDIT_SCENARIOS`` is the pytest parameter list both suites run;
``check_a_read_only_user_keeps_the_edit_in_the_graph`` needs the in-memory server (it switches the
database user to read-only) and is run by the mongomock suite only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, cast

from sankey_studio.edits.target import write_target
from sankey_studio.models import MongoSource
from tests.e2e.support.clients import json_of
from tests.e2e.support.http_b_mongo_flows import (
    FLOW_ENTRIES,
    entries_of,
    finish,
    prepare,
    preview,
)
from tests.e2e.support.http_b_world import DATA_COLLECTION, MAIN, FlowEnv

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import MongoWorld

PLAN: Final = "/api/v1/edits/plan"
WRITE: Final = "/api/v1/edits/write"
RENT: Final = {"op": "set_category", "source": "Account", "target": "Rent", "category": "Fixed"}
GIFTS: Final = {
    "op": "add_entry",
    "source": "Account",
    "target": "Gifts",
    "value": 50,
    "category": "Fun",
}


def body(env: FlowEnv, edit: dict[str, Any], **source: Any) -> dict[str, Any]:
    return {"draft": env.world.draft(**source), "edit": edit}


def plan(env: FlowEnv, edit: dict[str, Any], **source: Any) -> dict[str, Any]:
    return dict(json_of(env.api.post(PLAN, json=body(env, edit, **source))))


def write(env: FlowEnv, edit: dict[str, Any], **source: Any) -> httpx.Response:
    return env.api.post(WRITE, json=body(env, edit, **source))


def agreed(env: FlowEnv, edit: dict[str, Any], **source: Any) -> dict[str, Any]:
    """The source fields of a graph whose owner said yes in the dialog (key from ``plan``)."""
    key = plan(env, edit, **source)["target_key"]
    return {**source, "write_back": {"mode": "source", "target": key}}


def documents(world: MongoWorld, collection: str = DATA_COLLECTION) -> list[dict[str, Any]]:
    cursor = world.client[world.database][collection].find({}, {"_id": 0})
    return sorted(cursor, key=lambda doc: str(sorted(doc.items())))


def category_of(world: MongoWorld, target: str) -> Any:
    doc = world.client[world.database][DATA_COLLECTION].find_one({"to": target})
    return None if doc is None else doc.get("kind")


# ------------------------------------------------------------------------------ scenarios


def check_plan_counts_and_writes_nothing(env: FlowEnv) -> None:
    prepare(env)
    before = documents(env.world)
    outcome = plan(env, RENT)
    assert (outcome["where"], outcome["consent"], outcome["changed"]) == ("mongo", "ask", 1)
    assert outcome["target"] == f"{MAIN} / {env.world.database}.{DATA_COLLECTION}"
    assert outcome["target_key"].startswith(f"mongo:{MAIN}/{env.world.database}/{DATA_COLLECTION}#")
    assert env.world.secrets == () or not any(s in outcome["target_key"] for s in env.world.secrets)
    assert documents(env.world) == before
    finish(env)


def check_the_consent_then_the_write_changes_the_collection(env: FlowEnv) -> None:
    prepare(env)
    assert entries_of(preview(env)) == FLOW_ENTRIES
    source = agreed(env, RENT)
    response = write(env, RENT, **source)
    outcome = json_of(response)
    assert (outcome["where"], outcome["written"], outcome["changed"]) == ("mongo", True, 1)
    assert (outcome["consent"], outcome["override"]) == ("granted", "drop")
    assert category_of(env.world, "Rent") == "Fixed"
    assert category_of(env.world, "Food") == "Food"
    bundle = preview(env)
    assert "Fixed" in bundle["category_names"], "the graph cache was cleared by the write"
    assert "Housing" not in bundle["category_names"]
    finish(env)


def check_a_cleared_category_removes_the_field(env: FlowEnv) -> None:
    prepare(env)
    clear = {**RENT, "category": None}
    outcome = json_of(write(env, clear, **agreed(env, clear)))
    assert (outcome["written"], outcome["changed"]) == (True, 1)
    found = env.world.client[env.world.database][DATA_COLLECTION].find_one({"to": "Rent"})
    assert found is not None
    assert "kind" not in found
    finish(env)


def check_a_new_entry_is_a_document(env: FlowEnv) -> None:
    prepare(env)
    source = agreed(env, GIFTS)
    outcome = json_of(write(env, GIFTS, **source))
    assert (outcome["where"], outcome["written"], outcome["changed"]) == ("mongo", True, 1)
    added = [doc for doc in documents(env.world) if doc["to"] == "Gifts"]
    assert added == [{"from": "Account", "to": "Gifts", "amount": 50, "kind": "Fun"}]
    assert entries_of(preview(env))[("Account", "Gifts")] == 50
    finish(env)


def check_no_consent_is_a_422_and_nothing_changes(env: FlowEnv) -> None:
    prepare(env)
    before = documents(env.world)
    refused = write(env, RENT)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "source_edit_refused"
    graph_pref = {"mode": "graph", "target": plan(env, RENT)["target_key"]}
    assert write(env, RENT, write_back=graph_pref).status_code == 422
    assert documents(env.world) == before
    finish(env)


def check_a_consent_for_another_collection_is_not_enough(env: FlowEnv) -> None:
    prepare(env)
    env.world.insert("other_flows", [{"from": "Account", "to": "Rent", "amount": 1, "kind": "X"}])
    elsewhere = agreed(env, RENT, collection="other_flows")
    before = documents(env.world)
    refused = write(env, RENT, write_back=elsewhere["write_back"])
    assert refused.status_code == 422
    assert documents(env.world) == before
    finish(env)


def check_the_applications_own_collections_are_never_written(env: FlowEnv) -> None:
    prepare(env)
    env.world.insert("sankey_studio_graphs", [{"from": "Account", "to": "Rent", "amount": 1}])
    before = documents(env.world, "sankey_studio_graphs")
    fields = {"collection": "sankey_studio_graphs"}
    outcome = plan(env, RENT, **fields)
    assert (outcome["where"], outcome["reason"]) == ("graph", "reserved_collection")
    assert outcome["target_key"] is None, "no dialog is ever offered for such a target"
    # a hand-made request with the right key (what the dialog would have stored) is refused too
    spec = MongoSource.model_validate(env.world.source(**fields))
    pref = {"mode": "source", "target": write_target(spec, env.server.services.settings())}
    answer = json_of(write(env, RENT, write_back=pref, **fields))
    assert (answer["where"], answer["reason"], answer["written"]) == (
        "graph",
        "reserved_collection",
        False,
    )
    assert documents(env.world, "sankey_studio_graphs") == before
    finish(env)


def check_text_a_spreadsheet_could_run_stays_in_the_graph(env: FlowEnv) -> None:
    prepare(env)
    before = documents(env.world)
    formula = {**RENT, "category": "=HYPERLINK(1)"}
    outcome = plan(env, formula)
    assert (outcome["where"], outcome["reason"]) == ("graph", "unsafe_value")
    assert documents(env.world) == before
    finish(env)


def check_a_drag_never_touches_the_collection(env: FlowEnv) -> None:
    prepare(env)
    before = documents(env.world)
    drag = {"op": "reorder", "order": ["Salary", "Account", "Savings", "Rent"]}
    source = agreed(env, RENT)
    outcome = json_of(write(env, drag, **source))
    assert (outcome["where"], outcome["reason"], outcome["written"]) == (
        "graph",
        "order_in_graph",
        False,
    )
    assert documents(env.world) == before
    finish(env)


def check_a_missing_category_field_is_explained(env: FlowEnv) -> None:
    prepare(env)
    outcome = plan(env, RENT, category_field=None)
    assert (outcome["where"], outcome["reason"]) == ("graph", "no_category_field")
    assert "category field" in outcome["notice"]
    finish(env)


EDIT_SCENARIOS: Final[list[Scenario]] = [
    check_plan_counts_and_writes_nothing,
    check_the_consent_then_the_write_changes_the_collection,
    check_a_cleared_category_removes_the_field,
    check_a_new_entry_is_a_document,
    check_no_consent_is_a_422_and_nothing_changes,
    check_a_consent_for_another_collection_is_not_enough,
    check_the_applications_own_collections_are_never_written,
    check_text_a_spreadsheet_could_run_stays_in_the_graph,
    check_a_drag_never_touches_the_collection,
    check_a_missing_category_field_is_explained,
]


def check_a_read_only_user_keeps_the_edit_in_the_graph(env: FlowEnv) -> None:
    """The database user may not write: an expected answer, nothing changes, nothing is cleared."""
    prepare(env)
    source = agreed(env, RENT)
    before = documents(env.world)
    client = cast("Any", env.world.client)
    client.read_only = True
    try:
        outcome = json_of(write(env, RENT, **source))
    finally:
        client.read_only = False
    assert (outcome["where"], outcome["reason"], outcome["written"]) == (
        "graph",
        "permission_denied",
        False,
    )
    assert documents(env.world) == before
    finish(env)
