"""``plan_edit`` for a managed text file: the decision table, row by row (nothing is written)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.edits import plan_edit
from sankey_studio.edits.reasons import NOTICES
from sankey_studio.errors import GraphBuildError, SourceEditRefused, SourceNotFoundError
from sankey_studio.models import EditOutcome, TextSource
from sankey_studio.models.base import MAX_COLOR_OVERRIDES
from tests.test_edits_support import (
    ADD,
    CATEGORISE,
    CSV,
    REORDER,
    EditEnv,
    consenting,
    file_source,
    make_edit_env,
    request,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import SourceSpec
    from tests.test_edits_support import Access

LAYERS = {"style": {"color_mode": "layer"}}


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[EditEnv]:
    with make_edit_env(tmp_path, mongo_client) as made:
        env_file = made.write_source("flows.csv", CSV)
        assert env_file.read_text() == CSV
        yield made


def plan(env: EditEnv, source: SourceSpec, edit: dict[str, Any], **transform: Any) -> EditOutcome:
    return plan_edit(env.services, request(source, edit, **transform), env.cache)


def on_disk(env: EditEnv) -> str:
    return (env.sources_dir / "flows.csv").read_text(encoding="utf-8")


def test_the_first_edit_asks_and_writes_nothing(env: EditEnv) -> None:
    outcome = plan(env, file_source(), ADD)
    assert outcome == EditOutcome(
        where="file",
        consent="ask",
        target="flows.csv",
        target_key="file:flows.csv",
        changed=1,
    )
    assert on_disk(env) == CSV


def test_a_saved_consent_for_this_file_answers_granted(env: EditEnv) -> None:
    outcome = plan(env, consenting(file_source(), env), CATEGORISE)
    assert (outcome.where, outcome.consent, outcome.changed) == ("file", "granted", 1)
    assert outcome.target_key == "file:flows.csv"
    assert on_disk(env) == CSV


def test_a_consent_given_for_another_file_asks_again(env: EditEnv) -> None:
    other = consenting(file_source("other.csv"), env)
    assert isinstance(other, TextSource)
    moved = file_source("flows.csv", write_back=other.write_back)
    outcome = plan(env, moved, ADD)
    assert (outcome.where, outcome.consent) == ("file", "ask")


def test_keeping_edits_in_the_graph_is_a_silent_answer(env: EditEnv) -> None:
    kept = consenting(file_source(), env, "graph")
    outcome = plan(env, kept, ADD)
    assert outcome == EditOutcome(where="graph", reason="preference")


def test_a_drag_never_asks(env: EditEnv) -> None:
    outcome = plan(env, file_source(), REORDER)
    assert outcome == EditOutcome(where="graph", reason="order_in_graph")


def test_a_drag_reorders_rows_only_with_consent_and_without_repainting(env: EditEnv) -> None:
    granted = consenting(file_source(), env)
    outcome = plan(env, granted, REORDER, **LAYERS)
    assert (outcome.where, outcome.consent, outcome.changed) == ("file", "granted", 2)
    assert on_disk(env) == CSV


def test_a_drag_that_would_repaint_the_chart_is_planned_with_the_pins_later(env: EditEnv) -> None:
    outcome = plan(env, consenting(file_source(), env), REORDER)
    assert (outcome.where, outcome.consent, outcome.changed) == ("file", "granted", 2)
    assert on_disk(env) == CSV


def test_a_drag_whose_pins_would_not_fit_in_the_style_keeps_the_rows(env: EditEnv) -> None:
    full = {f"n{i}": "#112233" for i in range(MAX_COLOR_OVERRIDES)}
    outcome = plan(env, consenting(file_source(), env), REORDER, style={"node_colors": full})
    assert outcome == EditOutcome(
        where="graph", reason="would_recolour", notice=NOTICES["would_recolour"]
    )


def test_a_drag_that_changes_no_row_is_silent(env: EditEnv) -> None:
    done = {"op": "reorder", "order": ["Salary", "Budget", "Rent", "Food"]}
    outcome = plan(env, consenting(file_source(), env), done, **LAYERS)
    assert outcome == EditOutcome(where="graph", reason="order_in_graph")


def test_a_refusal_of_the_rewriter_stays_in_the_graph(env: EditEnv) -> None:
    gone = {**CATEGORISE, "target": "Nothing"}
    outcome = plan(env, file_source(), gone)
    assert outcome == EditOutcome(where="graph", reason="no_match", notice=NOTICES["no_match"])
    assert on_disk(env) == CSV


def test_bytes_that_do_not_decode_are_unreadable(env: EditEnv) -> None:
    (env.sources_dir / "flows.csv").write_bytes(b"source,target,value\n\xff\xfe,b,1\n")
    outcome = plan(env, file_source(), CATEGORISE)
    assert (outcome.where, outcome.reason) == ("graph", "unreadable")


def test_a_missing_file_is_a_not_found_error(env: EditEnv) -> None:
    with pytest.raises(SourceNotFoundError):
        plan(env, file_source("missing.csv"), ADD)


def test_an_entry_that_closes_a_cycle_is_a_422_before_any_dialog(env: EditEnv) -> None:
    cycle = {"op": "add_entry", "source": "Rent", "target": "Salary", "value": 5}
    with pytest.raises(GraphBuildError):
        plan(env, file_source(), cycle)


def test_the_entry_is_validated_even_when_it_stays_in_the_graph(env: EditEnv) -> None:
    kept = consenting(file_source(), env, "graph")
    cycle = {"op": "add_entry", "source": "Rent", "target": "Salary", "value": 5}
    with pytest.raises(GraphBuildError):
        plan(env, kept, cycle)


def full_overlay() -> list[dict[str, Any]]:
    return [{"source": f"s{i}", "target": f"t{i}", "value": 1} for i in range(2000)]


def test_the_graph_only_entries_have_a_cap(env: EditEnv) -> None:
    source = consenting(file_source(), env, "graph")
    with pytest.raises(SourceEditRefused) as refused:
        plan(env, source, ADD, extra_links=full_overlay())
    assert refused.value.reason == "too_many"


@pytest.mark.parametrize("mode", ["source", None])
def test_an_entry_for_the_file_is_not_blocked_by_a_full_overlay(
    env: EditEnv, mode: str | None
) -> None:
    source = file_source() if mode is None else consenting(file_source(), env, "source")
    outcome = plan(env, source, ADD, extra_links=full_overlay())
    assert outcome.where == "file"
    assert outcome.consent == ("ask" if mode is None else "granted")


@pytest.mark.parametrize(
    ("access", "reason"),
    [
        ("local", None),
        ("remote_ro", "read_only_mode"),
        ("remote_writes", None),
        ("remote_all", None),
    ],
)
def test_the_operator_may_forbid_file_writes(
    tmp_path: Path, mongo_client: MongoClient[Any], access: Access, reason: str | None
) -> None:
    with make_edit_env(tmp_path, mongo_client, access) as env:
        env.write_source("flows.csv", CSV)
        outcome = plan(env, file_source(), ADD)
    assert outcome.reason == reason
    assert outcome.where == ("file" if reason is None else "graph")
    assert outcome.notice == (None if reason is None else NOTICES[reason])
