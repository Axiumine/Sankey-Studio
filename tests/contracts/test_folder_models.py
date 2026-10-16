# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Folder models: labels, ids, revision, strictness, persisted shape and the shared limits."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from sankey_studio.models import (
    FOLDER_DEPTH_MAX,
    FOLDER_LABEL_MAX,
    FOLDERS_MAX,
    MAX_EXTRA_LINKS,
    MAX_NODE_ORDER,
    SCHEMA_VERSION,
    WRITE_TARGET_MAX,
    FolderCreate,
    FolderDefinition,
    FolderSummary,
    FolderUpdate,
    MoveReport,
)

NOW = "2026-01-02T03:04:05+00:00"
ID = "0" * 32
DEFINITION: dict[str, Any] = {"name": "Home", "id": ID, "created_at": NOW, "updated_at": NOW}
SUMMARY: dict[str, Any] = {
    "id": ID,
    "name": "Home",
    "parent_id": None,
    "revision": 1,
    "updated_at": NOW,
    "graph_count": 0,
    "child_count": 0,
}


def test_the_shared_limits_are_pinned() -> None:
    assert (FOLDER_LABEL_MAX, FOLDER_DEPTH_MAX, FOLDERS_MAX) == (100, 8, 1_000)
    assert (MAX_EXTRA_LINKS, MAX_NODE_ORDER, WRITE_TARGET_MAX) == (2_000, 5_000, 400)


@pytest.mark.parametrize("name", ["a", "x" * 100, "two words", "café", "中文"])
def test_a_label_inside_the_limits_is_accepted(name: str) -> None:
    assert FolderCreate(name=name).name == name


@pytest.mark.parametrize("name", ["", " ", "\t \n", "x" * 101, "a\0b", "\0"])
def test_a_label_outside_the_limits_is_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        FolderCreate(name=name)


def test_a_label_is_trimmed() -> None:
    assert FolderCreate(name="  Home  ").name == "Home"


def test_a_label_is_required_and_the_parent_defaults_to_the_top_level() -> None:
    with pytest.raises(ValidationError):
        FolderCreate.model_validate({})
    assert FolderCreate(name="a").parent_id is None


@pytest.mark.parametrize(
    "parent", [ID, "a" * 32, "0123456789abcdef" * 2], ids=["zeros", "a", "hex-range"]
)
def test_a_parent_id_of_the_graph_id_shape_is_accepted(parent: str) -> None:
    assert FolderCreate(name="a", parent_id=parent).parent_id == parent


@pytest.mark.parametrize(
    "parent", ["", "0" * 31, "0" * 33, "G" * 32, "A" * 32, "../" + "0" * 29, "root"]
)
def test_a_parent_id_of_another_shape_is_refused(parent: str) -> None:
    with pytest.raises(ValidationError):
        FolderCreate(name="a", parent_id=parent)


@pytest.mark.parametrize("model", [FolderCreate, FolderUpdate])
def test_request_models_forbid_unknown_fields(model: Any) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"name": "a", "revision": 1, "extra": 1})


@pytest.mark.parametrize(("revision", "ok"), [(0, False), (1, True), (2, True), (-1, False)])
def test_an_update_needs_a_revision_of_at_least_one(revision: int, *, ok: bool) -> None:
    body = {"name": "a", "revision": revision}
    if ok:
        assert FolderUpdate.model_validate(body).revision == revision
    else:
        with pytest.raises(ValidationError):
            FolderUpdate.model_validate(body)


def test_an_update_without_a_revision_is_refused() -> None:
    with pytest.raises(ValidationError):
        FolderUpdate.model_validate({"name": "a"})


def test_the_definition_defaults() -> None:
    folder = FolderDefinition.model_validate(DEFINITION)
    assert (folder.revision, folder.schema_version, folder.parent_id) == (1, SCHEMA_VERSION, None)


@pytest.mark.parametrize(("field", "bad", "good"), [("revision", 0, 1), ("schema_version", 0, 1)])
def test_definition_counters_start_at_one(field: str, bad: int, good: int) -> None:
    assert getattr(FolderDefinition.model_validate({**DEFINITION, field: good}), field) == good
    with pytest.raises(ValidationError):
        FolderDefinition.model_validate({**DEFINITION, field: bad})


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
@pytest.mark.parametrize("value", ["2026-01-02T03:04:05", "yesterday", ""])
def test_definition_times_must_carry_a_zone(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        FolderDefinition.model_validate({**DEFINITION, field: value})
    zoned = FolderDefinition.model_validate({**DEFINITION, field: "2026-01-02T03:04:05Z"})
    assert getattr(zoned, field).tzinfo is not None


def test_the_definition_ignores_unknown_stored_fields() -> None:
    folder = FolderDefinition.model_validate({**DEFINITION, "future": 1})
    assert not hasattr(folder, "future")
    assert "future" not in folder.model_dump()


def test_the_definition_dump_has_exactly_the_documented_fields() -> None:
    dumped = FolderDefinition.model_validate(DEFINITION).model_dump()
    assert set(dumped) == {
        "name",
        "parent_id",
        "id",
        "schema_version",
        "revision",
        "created_at",
        "updated_at",
    }


def test_a_summary_has_counts_and_forbids_unknown_fields() -> None:
    summary = FolderSummary.model_validate(SUMMARY)
    assert (summary.graph_count, summary.child_count, summary.parent_id) == (0, 0, None)
    with pytest.raises(ValidationError):
        FolderSummary.model_validate({**SUMMARY, "extra": 1})
    for field in ("graph_count", "child_count"):
        with pytest.raises(ValidationError):
            FolderSummary.model_validate({**SUMMARY, field: -1})
    for field in SUMMARY:
        with pytest.raises(ValidationError):
            FolderSummary.model_validate({k: v for k, v in SUMMARY.items() if k != field})


def test_a_move_report_counts_and_names_missing_ids() -> None:
    report = MoveReport(moved=2, missing=[ID])
    assert (report.moved, report.missing) == (2, [ID])
    assert MoveReport(moved=0, missing=[]).moved == 0
    with pytest.raises(ValidationError):
        MoveReport(moved=-1, missing=[])
    with pytest.raises(ValidationError):
        MoveReport(moved=0, missing=["nope"])
