# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``write_edit`` to a managed text file: consent, the atomic rewrite, the answers."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.edits import plan_edit, write_edit
from sankey_studio.edits.reasons import NOTICES
from sankey_studio.errors import ConflictError, GraphBuildError, SourceEditRefused, StorageError
from sankey_studio.models import EditOutcome, StylePins, TextSource
from sankey_studio.models.base import MAX_COLOR_OVERRIDES
from sankey_studio.sources.files.store import read_text
from tests.test_edits_support import (
    ADD,
    CATEGORISE,
    CSV,
    REORDER,
    EditEnv,
    consenting,
    file_source,
    inline,
    make_edit_env,
    manual,
    request,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import SourceSpec

LAYERS = {"style": {"color_mode": "layer"}}


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[EditEnv]:
    with make_edit_env(tmp_path, mongo_client) as made:
        made.write_source("flows.csv", CSV)
        yield made


def write(env: EditEnv, source: SourceSpec, edit: dict[str, Any], **transform: Any) -> EditOutcome:
    return write_edit(env.services, request(source, edit, **transform), env.cache)


def on_disk(env: EditEnv) -> str:
    return (env.sources_dir / "flows.csv").read_text(encoding="utf-8")


def test_an_entry_is_appended_to_the_file(env: EditEnv) -> None:
    outcome = write(env, consenting(file_source(), env), ADD)
    assert outcome == EditOutcome(
        where="file",
        written=True,
        consent="granted",
        target="flows.csv",
        target_key="file:flows.csv",
        changed=1,
    )
    assert on_disk(env) == CSV + "Budget,Gifts,50,Fun\n"
    assert env.cache.clears == 0


def test_a_category_is_written_and_the_override_dropped(env: EditEnv) -> None:
    outcome = write(env, consenting(file_source(), env), CATEGORISE)
    assert (outcome.written, outcome.changed, outcome.override) == (True, 1, "drop")
    assert "Budget,Food,640,Fun\n" in on_disk(env)


def test_a_full_overlay_does_not_stop_a_row_for_the_file(env: EditEnv) -> None:
    extra = [{"source": f"s{i}", "target": f"t{i}", "value": 1} for i in range(2000)]
    outcome = write(env, consenting(file_source(), env), ADD, extra_links=extra)
    assert (outcome.where, outcome.written) == ("file", True)


def test_the_file_mode_survives_the_rewrite(env: EditEnv) -> None:
    path = env.sources_dir / "flows.csv"
    path.chmod(0o640)
    write(env, consenting(file_source(), env), ADD)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_pins_the_rewriter_needed_travel_back_with_the_source(env: EditEnv) -> None:
    pinned = consenting(file_source(detect_category=False), env)
    assert isinstance(pinned, TextSource)
    outcome = write(env, pinned, CATEGORISE)
    assert isinstance(outcome.source, TextSource)
    assert outcome.source.category_column is not None
    assert outcome.source.write_back == pinned.write_back


def test_a_drag_writes_the_rows_in_the_new_order(env: EditEnv) -> None:
    outcome = write(env, consenting(file_source(), env), REORDER, **LAYERS)
    assert (outcome.where, outcome.written, outcome.changed) == ("file", True, 2)
    assert on_disk(env).splitlines()[2:] == ["Budget,Food,640,", "Budget,Rent,1200,Housing"]


def test_a_drag_that_would_repaint_the_chart_writes_the_rows_and_returns_the_pins(
    env: EditEnv,
) -> None:
    outcome = write(env, consenting(file_source(), env), REORDER)
    assert (outcome.where, outcome.written, outcome.changed) == ("file", True, 2)
    assert outcome.pins == StylePins(node_colors={"Rent": "#1baf7a", "Food": "#eda100"})
    assert on_disk(env).splitlines()[2:] == ["Budget,Food,640,", "Budget,Rent,1200,Housing"]


def test_a_drag_without_a_recolour_returns_no_pins(env: EditEnv) -> None:
    assert write(env, consenting(file_source(), env), REORDER, **LAYERS).pins is None


def test_a_drag_whose_pins_would_not_fit_in_the_style_writes_nothing(env: EditEnv) -> None:
    full = {f"n{i}": "#112233" for i in range(MAX_COLOR_OVERRIDES)}
    outcome = write(env, consenting(file_source(), env), REORDER, style={"node_colors": full})
    assert (outcome.where, outcome.reason) == ("graph", "would_recolour")
    assert on_disk(env) == CSV


def test_a_drag_that_changes_no_row_writes_nothing(env: EditEnv) -> None:
    done = {"op": "reorder", "order": ["Salary", "Budget", "Rent", "Food"]}
    outcome = write(env, consenting(file_source(), env), done, **LAYERS)
    assert outcome == EditOutcome(where="graph", reason="order_in_graph")


@pytest.mark.parametrize("mode", ["ask", "graph", "other-file"])
def test_without_the_consent_of_this_target_the_write_is_refused(env: EditEnv, mode: str) -> None:
    source: SourceSpec = file_source()
    if mode == "graph":
        source = consenting(source, env, "graph")
    if mode == "other-file":
        other = consenting(file_source("other.csv"), env)
        assert isinstance(other, TextSource)
        source = file_source(write_back=other.write_back)
    with pytest.raises(SourceEditRefused) as refused:
        write(env, source, ADD)
    assert refused.value.reason == "no_consent"
    assert on_disk(env) == CSV


def test_a_refusal_of_the_rewriter_is_an_expected_answer(env: EditEnv) -> None:
    gone = {**CATEGORISE, "target": "Nothing"}
    outcome = write(env, consenting(file_source(), env), gone)
    assert outcome == EditOutcome(where="graph", reason="no_match", notice=NOTICES["no_match"])
    assert on_disk(env) == CSV


def test_an_entry_that_closes_a_cycle_is_a_422_and_nothing_is_written(env: EditEnv) -> None:
    cycle = {"op": "add_entry", "source": "Rent", "target": "Salary", "value": 5}
    with pytest.raises(GraphBuildError):
        write(env, consenting(file_source(), env), cycle)
    assert on_disk(env) == CSV


def test_a_file_that_changes_between_the_dry_run_and_the_write_is_a_conflict(
    env: EditEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dry run read ``CSV``; by the time the lock is held the file has one more row."""
    path = env.sources_dir / "flows.csv"
    changed = CSV + "Budget,Gym,30,\n"
    real = read_text

    def stale(request_: Any) -> str:
        text = real(request_)
        path.write_text(changed, encoding="utf-8")
        return text

    monkeypatch.setattr("sankey_studio.edits.files.read_text", stale)
    with pytest.raises(ConflictError):
        write(env, consenting(file_source(), env), ADD)
    assert path.read_text(encoding="utf-8") == changed


def test_an_os_failure_is_an_error_and_nothing_falls_back(
    env: EditEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: Any) -> int:
        raise StorageError("the file could not be written")

    monkeypatch.setattr("sankey_studio.edits.files.edit_file", broken)
    with pytest.raises(StorageError):
        write(env, consenting(file_source(), env), ADD)
    assert on_disk(env) == CSV


@pytest.mark.parametrize("source", [inline(), manual(("a", "b", 1, None))])
def test_data_in_the_draft_has_nothing_to_write_and_answers_like_plan(
    env: EditEnv, source: SourceSpec
) -> None:
    edit = {**ADD, "source": "b", "target": "c"}
    written = write(env, source, edit)
    assert written == plan_edit(env.services, request(source, edit), env.cache)
    assert (written.where, written.written) == ("draft", False)
