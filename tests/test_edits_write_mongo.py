"""``write_edit`` to a MongoDB source: scoped updates, inserts, refusals and the cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import mongomock.collection
import pytest
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from sankey_studio.edits import mongo as edit_mongo
from sankey_studio.edits import write_edit
from sankey_studio.edits.job import make_job
from sankey_studio.edits.reasons import NOTICES
from sankey_studio.errors import (
    BusyError,
    GraphBuildError,
    SourceEditRefused,
    SourceWriteError,
)
from sankey_studio.models import EditOutcome, MongoSource
from sankey_studio.pipeline import ResultCache, build_graph_from_draft
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
NEW = {"op": "add_entry", "source": "b", "target": "d", "value": 7, "category": "Fun"}


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[EditEnv]:
    with make_edit_env(tmp_path, mongo_client) as made:
        seed_events(made)
        yield made


def write(env: EditEnv, source: SourceSpec, edit: dict[str, Any], **transform: Any) -> EditOutcome:
    return write_edit(env.services, request(source, edit, **transform), env.cache)


def docs(env: EditEnv) -> list[dict[str, Any]]:
    return sorted(env.mongo["flows"]["events"].find({}, {"_id": 0}), key=str)


def test_the_documents_of_the_pair_get_the_category(env: EditEnv) -> None:
    outcome = write(env, consenting(mongo_source(), env), PAIR)
    assert outcome.where == "mongo"
    assert (outcome.written, outcome.consent, outcome.changed, outcome.override) == (
        True,
        "granted",
        3,
        "drop",
    )
    assert outcome.target == "test / flows.events"
    assert (outcome.target_key or "").startswith("mongo:test/flows/events#")
    assert [d.get("cat") for d in docs(env) if d["source"] == "a"] == ["Fun"] * 3
    assert env.cache.clears == 1


def test_changed_counts_only_the_documents_that_really_changed(env: EditEnv) -> None:
    env.mongo["flows"]["events"].update_one({"source": "a", "value": 10}, {"$set": {"cat": "Fun"}})
    outcome = write(env, consenting(mongo_source(), env), PAIR)
    assert outcome.changed == 2


def test_a_cleared_category_removes_the_field(env: EditEnv) -> None:
    clear = {"op": "set_category", "source": "b", "target": "c", "category": None}
    outcome = write(env, consenting(mongo_source(), env), clear)
    assert outcome.changed == 1
    assert all("cat" not in doc for doc in docs(env))


def test_an_entry_becomes_a_document_with_the_equality_fields_of_the_filter(env: EditEnv) -> None:
    source = consenting(mongo_source(filter={"year": 2025}), env)
    outcome = write(env, source, NEW)
    assert (outcome.where, outcome.written, outcome.changed) == ("mongo", True, 1)
    added = [d for d in docs(env) if d["target"] == "d"]
    assert added == [{"source": "b", "target": "d", "value": 7, "cat": "Fun", "year": 2025}]
    assert env.cache.clears == 1


def test_a_drag_never_touches_mongo_even_without_consent(env: EditEnv) -> None:
    drag = {"op": "reorder", "order": ["a", "b"]}
    assert write(env, mongo_source(), drag) == EditOutcome(where="graph", reason="order_in_graph")
    assert env.cache.clears == 0


@pytest.mark.parametrize("mode", ["ask", "graph"])
def test_without_the_consent_of_this_target_nothing_is_written(env: EditEnv, mode: str) -> None:
    source = mongo_source() if mode == "ask" else consenting(mongo_source(), env, "graph")
    before = docs(env)
    with pytest.raises(SourceEditRefused) as refused:
        write(env, source, PAIR)
    assert refused.value.reason == "no_consent"
    assert docs(env) == before
    assert env.cache.clears == 0


def test_a_consent_for_another_collection_does_not_carry_over(env: EditEnv) -> None:
    other = consenting(mongo_source(collection="other"), env)
    assert isinstance(other, MongoSource)
    moved = mongo_source(write_back=other.write_back)
    with pytest.raises(SourceEditRefused):
        write(env, moved, PAIR)


@pytest.mark.parametrize(
    ("fields", "edit", "reason"),
    [
        ({}, {**PAIR, "target": "zzz"}, "no_match"),
        ({"category_field": None}, PAIR, "no_category_field"),
        ({"limit": 4}, NEW, "limit_reached"),
        ({"value_field": None}, NEW, "no_value_field"),
        ({"mode": "aggregate", "pipeline": [{"$limit": 5}]}, PAIR, "aggregate_mode"),
    ],
)
def test_a_definite_refusal_is_an_expected_answer_and_clears_nothing(
    env: EditEnv, fields: dict[str, Any], edit: dict[str, Any], reason: str
) -> None:
    before = docs(env)
    outcome = write(env, consenting(mongo_source(**fields), env), edit)
    expected = {"where": "graph", "reason": reason, "notice": NOTICES[reason]}
    assert outcome == EditOutcome.model_validate(expected)
    assert docs(env) == before
    assert env.cache.clears == 0


def test_documents_that_appeared_since_the_plan_can_exceed_the_limit(env: EditEnv) -> None:
    env.mongo["flows"]["events"].insert_many(
        [{"source": "a", "target": "b", "value": 1} for _ in range(1000)]
    )
    before = docs(env)
    outcome = write(env, consenting(mongo_source(), env), PAIR)
    assert (outcome.where, outcome.reason) == ("graph", "too_many_documents")
    assert docs(env) == before
    assert env.cache.clears == 0


def test_an_entry_that_closes_a_cycle_is_a_422_and_nothing_is_inserted(env: EditEnv) -> None:
    cycle = {"op": "add_entry", "source": "c", "target": "a", "value": 1}
    with pytest.raises(GraphBuildError):
        write(env, consenting(mongo_source(), env), cycle)
    assert len(docs(env)) == 4


def test_the_user_without_write_rights_gets_an_expected_answer(
    env: EditEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        raise OperationFailure("not authorized", code=13)

    monkeypatch.setattr(mongomock.collection.Collection, "update_many", denied)
    outcome = write(env, consenting(mongo_source(), env), PAIR)
    assert (outcome.where, outcome.reason) == ("graph", "permission_denied")
    assert env.cache.clears == 0


def test_a_driver_failure_is_an_error_and_nothing_falls_back(
    env: EditEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(*_args: Any, **_kwargs: Any) -> Any:
        raise ServerSelectionTimeoutError("mongo.invalid:27017 timed out")

    monkeypatch.setattr(mongomock.collection.Collection, "update_many", down)
    with pytest.raises((SourceWriteError, BusyError)) as failure:
        write(env, consenting(mongo_source(), env), PAIR)
    assert "mongo.invalid" not in str(failure.value)
    assert env.cache.clears == 0


def test_the_graph_cache_is_cleared_so_the_next_preview_sees_the_new_data(env: EditEnv) -> None:
    cache = ResultCache()
    source = consenting(mongo_source(), env)
    body = request(source, PAIR)
    before = build_graph_from_draft(env.services, body.draft, cache)
    assert before.categories == ("Old",)
    write_edit(env.services, body, cache)
    assert cache.size == 0
    assert set(build_graph_from_draft(env.services, body.draft, cache).categories) == {"Fun", "Old"}


def test_the_mongo_branch_has_no_reorder(env: EditEnv) -> None:
    job_request = request(mongo_source(), {"op": "reorder", "order": ["a"]})
    job = make_job(env.services, job_request, env.cache)
    with pytest.raises(SourceEditRefused) as counted:
        edit_mongo.count_documents(job)
    with pytest.raises(SourceEditRefused) as applied:
        edit_mongo.apply_edit(job)
    assert (counted.value.reason, applied.value.reason) == ("order_in_graph", "order_in_graph")
