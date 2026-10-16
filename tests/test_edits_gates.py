# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The operator gates of ``plan`` and ``write``: read-only server, source writes, namespaces,
formula-like text. First match wins; ``write`` raises 403 where ``plan`` answers ``graph``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.edits import plan_edit, write_edit
from sankey_studio.edits.gates import MSG_READ_ONLY
from sankey_studio.edits.reasons import NOTICES
from sankey_studio.errors import ReadOnlyModeError
from tests.test_edits_support import (
    ADD,
    CATEGORISE,
    CSV,
    EditEnv,
    consenting,
    file_source,
    inline,
    make_edit_env,
    manual,
    mongo_source,
    request,
    seed_events,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import EditOutcome, SourceSpec
    from tests.test_edits_support import Access

PAIR = {"op": "set_category", "source": "a", "target": "b", "category": "Fun"}
NEW = {"op": "add_entry", "source": "b", "target": "d", "value": 7}
FORMULAS = ["=1+1", "+x", "-x", "@x", " =x", "\n+x"]
PLAIN = ["plain", "a-b", "x=y", "x+y", "1-2", "mail@x"]


def open_env(tmp_path: Path, client: MongoClient[Any], access: Access = "local") -> EditEnv:
    manager = make_edit_env(tmp_path, client, access)
    env = manager.__enter__()
    env.write_source("flows.csv", CSV)
    seed_events(env)
    return env


def both(env: EditEnv, source: SourceSpec, edit: dict[str, Any]) -> tuple[EditOutcome, str]:
    """``plan`` answer and the ``write`` answer (or the name of the exception it raised)."""
    body = request(source, edit)
    planned = plan_edit(env.services, body, env.cache)
    try:
        return planned, write_edit(env.services, body, env.cache).reason or "written"
    except ReadOnlyModeError:
        return planned, "403"


@pytest.mark.parametrize("text", FORMULAS)
@pytest.mark.parametrize("field", ["source", "target", "category"])
def test_formula_like_text_stays_in_the_graph_for_a_file(
    tmp_path: Path, mongo_client: MongoClient[Any], text: str, field: str
) -> None:
    env = open_env(tmp_path, mongo_client)
    source = consenting(file_source(), env)
    planned, written = both(env, source, {**ADD, field: text})
    assert (planned.where, planned.reason) == ("graph", "unsafe_value")
    assert planned.notice == NOTICES["unsafe_value"]
    assert written == "unsafe_value"
    assert (env.sources_dir / "flows.csv").read_text() == CSV


@pytest.mark.parametrize("text", FORMULAS)
@pytest.mark.parametrize("edit", [PAIR, NEW])
def test_formula_like_text_stays_in_the_graph_for_mongo(
    tmp_path: Path, mongo_client: MongoClient[Any], text: str, edit: dict[str, Any]
) -> None:
    env = open_env(tmp_path, mongo_client)
    key = "category" if edit is PAIR else "target"
    planned, written = both(env, consenting(mongo_source(), env), {**edit, key: text})
    assert (planned.where, planned.reason, written) == ("graph", "unsafe_value", "unsafe_value")
    assert env.mongo["flows"]["events"].count_documents({}) == 4
    assert env.cache.clears == 0


@pytest.mark.parametrize("text", PLAIN)
def test_ordinary_text_passes_the_formula_gate(
    tmp_path: Path, mongo_client: MongoClient[Any], text: str
) -> None:
    env = open_env(tmp_path, mongo_client)
    planned, _ = both(env, consenting(file_source(), env), {**ADD, "target": text})
    assert (planned.where, planned.reason) == ("file", None)


def test_a_number_is_never_a_formula(tmp_path: Path, mongo_client: MongoClient[Any]) -> None:
    env = open_env(tmp_path, mongo_client)
    planned, written = both(env, consenting(file_source(), env), {**ADD, "value": 0.5})
    assert (planned.where, written) == ("file", "written")


@pytest.mark.parametrize("source", [inline(), manual(("a", "b", 1, None))])
def test_text_in_the_draft_is_the_persons_own_data_and_is_not_gated(
    tmp_path: Path, mongo_client: MongoClient[Any], source: SourceSpec
) -> None:
    env = open_env(tmp_path, mongo_client)
    outcome = plan_edit(env.services, request(source, {**ADD, "source": "=x"}), env.cache)
    assert outcome.where == "draft"


#: ``(access, file plan reason, mongo plan reason, mongo write answer)``
TRUTH = [
    ("local", None, None, "written"),
    ("remote_ro", "read_only_mode", "read_only_mode", "403"),
    ("remote_writes", None, "read_only_mode", "403"),
    ("remote_all", None, None, "written"),
]


@pytest.mark.parametrize("row", TRUTH, ids=[row[0] for row in TRUTH])
def test_the_truth_table_of_the_operator_flags(
    tmp_path: Path, mongo_client: MongoClient[Any], row: tuple[Access, str | None, str | None, str]
) -> None:
    access, file_reason, mongo_reason, mongo_write = row
    env = open_env(tmp_path, mongo_client, access)
    file_plan, _ = both(env, consenting(file_source(), env), CATEGORISE)
    assert file_plan.reason == file_reason
    mongo_plan, written = both(env, consenting(mongo_source(), env), PAIR)
    assert mongo_plan.reason == mongo_reason
    assert written == mongo_write


def test_write_raises_403_for_a_file_on_a_read_only_server(
    tmp_path: Path, mongo_client: MongoClient[Any]
) -> None:
    env = open_env(tmp_path, mongo_client, "remote_ro")
    with pytest.raises(ReadOnlyModeError) as refused:
        write_edit(env.services, request(consenting(file_source(), env), ADD), env.cache)
    assert str(refused.value) == MSG_READ_ONLY
    assert (env.sources_dir / "flows.csv").read_text() == CSV


@pytest.mark.parametrize(
    "collection",
    ["sankey_studio_graphs", "sankey_studio_collections", "Sankey_Studio_x", "sankey_studio_"],
)
def test_the_collections_of_the_application_are_never_written(
    tmp_path: Path, mongo_client: MongoClient[Any], collection: str
) -> None:
    env = open_env(tmp_path, mongo_client)
    source = consenting(mongo_source(collection=collection), env)
    planned, written = both(env, source, PAIR)
    assert (planned.where, planned.reason, written) == (
        "graph",
        "reserved_collection",
        "reserved_collection",
    )
    assert planned.notice == NOTICES["reserved_collection"]


@pytest.mark.parametrize("collection", ["sankey_studio", "my_sankey_studio_x", "events"])
def test_a_name_that_only_looks_like_the_prefix_is_allowed(
    tmp_path: Path, mongo_client: MongoClient[Any], collection: str
) -> None:
    env = open_env(tmp_path, mongo_client)
    planned, _ = both(env, consenting(mongo_source(collection=collection), env), PAIR)
    assert planned.reason != "reserved_collection"


def test_the_first_matching_gate_wins(tmp_path: Path, mongo_client: MongoClient[Any]) -> None:
    ro = open_env(tmp_path / "ro", mongo_client, "remote_ro")
    source = consenting(mongo_source(collection="sankey_studio_graphs"), ro)
    assert both(ro, source, {**PAIR, "category": "=x"})[0].reason == "read_only_mode"
    local = open_env(tmp_path / "local", mongo_client)
    again = consenting(mongo_source(collection="sankey_studio_graphs"), local)
    assert both(local, again, {**PAIR, "category": "=x"})[0].reason == "reserved_collection"


def test_an_unknown_connection_is_incomplete_not_a_crash(
    tmp_path: Path, mongo_client: MongoClient[Any]
) -> None:
    env = open_env(tmp_path, mongo_client)
    planned, written = both(env, consenting(mongo_source(connection="nobody"), env), PAIR)
    assert (planned.reason, written) == ("source_incomplete", "source_incomplete")
