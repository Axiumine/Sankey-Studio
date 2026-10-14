"""``plan_edit`` for a MongoDB source: counts only, never a write."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import mongomock.collection
import pytest
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from sankey_studio.edits import plan_edit
from sankey_studio.edits.reasons import NOTICES
from sankey_studio.errors import BusyError, SourceWriteError
from sankey_studio.models import EditOutcome
from tests.test_edits_support import (
    EditEnv,
    consenting,
    make_edit_env,
    mongo_source,
    request,
    seed_events,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import SourceSpec

PAIR = {"op": "set_category", "source": "a", "target": "b", "category": "Fun"}
NEW = {"op": "add_entry", "source": "b", "target": "d", "value": 7}


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[EditEnv]:
    with make_edit_env(tmp_path, mongo_client) as made:
        seed_events(made)
        yield made


def plan(env: EditEnv, source: SourceSpec, edit: dict[str, Any], **transform: Any) -> EditOutcome:
    return plan_edit(env.services, request(source, edit, **transform), env.cache)


def stored(env: EditEnv) -> list[dict[str, Any]]:
    return list(env.mongo["flows"]["events"].find({}))


def reason_of(env: EditEnv, source: SourceSpec, edit: dict[str, Any]) -> str | None:
    outcome = plan(env, source, edit)
    assert outcome.where == "graph"
    assert outcome.notice == (NOTICES.get(outcome.reason) if outcome.reason else None)
    return outcome.reason


def test_a_category_counts_the_documents_of_the_pair(env: EditEnv) -> None:
    before = stored(env)
    outcome = plan(env, mongo_source(), PAIR)
    assert outcome.where == "mongo"
    assert (outcome.consent, outcome.changed, outcome.written) == ("ask", 3, False)
    assert outcome.target == "test / flows.events"
    assert (outcome.target_key or "").startswith("mongo:test/flows/events#")
    assert stored(env) == before


def test_a_saved_consent_answers_granted(env: EditEnv) -> None:
    outcome = plan(env, consenting(mongo_source(), env), PAIR)
    assert (outcome.where, outcome.consent) == ("mongo", "granted")


def test_a_new_entry_is_one_document(env: EditEnv) -> None:
    outcome = plan(env, mongo_source(), NEW)
    assert (outcome.where, outcome.changed, outcome.consent) == ("mongo", 1, "ask")
    assert len(stored(env)) == 4


def test_a_new_document_is_not_blocked_by_a_full_overlay(env: EditEnv) -> None:
    extra = [{"source": f"s{i}", "target": f"t{i}", "value": 1} for i in range(2000)]
    outcome = plan(env, mongo_source(), NEW, extra_links=extra)
    assert (outcome.where, outcome.changed) == ("mongo", 1)


def test_the_graph_preference_is_silent(env: EditEnv) -> None:
    outcome = plan(env, consenting(mongo_source(), env, "graph"), PAIR)
    assert outcome == EditOutcome(where="graph", reason="preference")


@pytest.mark.parametrize("mode", ["source", "graph"])
def test_a_drag_never_touches_mongo(env: EditEnv, mode: Literal["source", "graph"]) -> None:
    drag = {"op": "reorder", "order": ["a", "b", "c"]}
    source = consenting(mongo_source(), env, mode)
    assert plan(env, source, drag) == EditOutcome(where="graph", reason="order_in_graph")
    assert plan(env, mongo_source(), drag) == EditOutcome(where="graph", reason="order_in_graph")


@pytest.mark.parametrize(
    ("documents", "edge"),
    [(1000, "mongo"), (1001, "too_many_documents")],
)
def test_the_most_documents_one_edit_may_change(env: EditEnv, documents: int, edge: str) -> None:
    env.mongo["flows"]["events"].delete_many({})
    seed_events(env, documents - 1)  # plus the b -> c document: 'a -> b' gets documents - 1
    env.mongo["flows"]["events"].insert_one({"source": "a", "target": "b", "value": 1})
    outcome = plan(env, mongo_source(), PAIR)
    assert outcome.where == ("mongo" if edge == "mongo" else "graph")
    assert outcome.reason == (None if edge == "mongo" else edge)
    assert outcome.changed == (1000 if edge == "mongo" else 0)


def test_the_merge_map_widens_the_pair(env: EditEnv) -> None:
    env.mongo["flows"]["events"].insert_one({"source": "A", "target": "b", "value": 1})
    merged = plan(env, mongo_source(), PAIR, merge_nodes={"A": "a"})
    assert merged.changed == 4


def test_the_filter_of_the_source_narrows_the_pair(env: EditEnv) -> None:
    env.mongo["flows"]["events"].insert_one({"source": "a", "target": "b", "value": 1, "y": 1})
    outcome = plan(env, mongo_source(filter={"y": 1}), PAIR)
    assert outcome.changed == 1


@pytest.mark.parametrize(
    ("fields", "edit", "reason"),
    [
        ({}, {**PAIR, "target": "zzz"}, "no_match"),
        ({"category_field": None}, PAIR, "no_category_field"),
        ({"category_field": None}, {**NEW, "category": "Fun"}, "no_category_field"),
        ({"value_field": None}, NEW, "no_value_field"),
        ({"mode": "aggregate", "pipeline": [{"$limit": 5}]}, PAIR, "aggregate_mode"),
        ({"filter": {"value": {"$gt": 1}}}, NEW, "filter_not_equality"),
        ({"category_field": "source"}, PAIR, "field_conflict"),
        ({"limit": 4}, NEW, "limit_reached"),
        ({"connection": "nobody"}, PAIR, "source_incomplete"),
    ],
)
def test_a_definite_refusal_stays_in_the_graph(
    env: EditEnv, fields: dict[str, Any], edit: dict[str, Any], reason: str
) -> None:
    assert reason_of(env, mongo_source(**fields), edit) == reason


def test_a_source_without_any_database_is_incomplete(
    tmp_path: Path, mongo_client: MongoClient[Any]
) -> None:
    with make_edit_env(tmp_path, mongo_client, database=None) as bare:
        assert reason_of(bare, mongo_source(database=None), PAIR) == "source_incomplete"


def test_the_default_database_of_the_connection_is_used(env: EditEnv) -> None:
    assert plan(env, mongo_source(database=None), PAIR).changed == 3


def test_the_driver_refusing_access_is_permission_denied(
    env: EditEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*_args: Any, **_kwargs: Any) -> int:
        raise OperationFailure("not authorized", code=13)

    monkeypatch.setattr(mongomock.collection.Collection, "count_documents", denied)
    assert reason_of(env, mongo_source(), PAIR) == "permission_denied"


def test_a_driver_failure_is_an_error_and_nothing_falls_back(
    env: EditEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(*_args: Any, **_kwargs: Any) -> int:
        raise ServerSelectionTimeoutError("mongo.invalid:27017 timed out")

    monkeypatch.setattr(mongomock.collection.Collection, "count_documents", down)
    with pytest.raises((SourceWriteError, BusyError)) as failure:
        plan(env, mongo_source(), PAIR)
    assert "mongo.invalid" not in str(failure.value)
