# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""A bundle never brings a saved write-back consent with it, in either import mode.

A consent names a file of the exporting machine or a connection by name: a stranger's bundle must
not arrive pre-approved for MY connection of the same name. Export keeps the preference (it is the
owner's own data); copying between stores and ``put`` keep it too (same owner).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.models import GraphDefinition
from sankey_studio.storage.bundle import ImportMode, export_bundle, import_bundle
from sankey_studio.storage.migrate import copy_graphs
from tests.storage.bundle_builders import bundle_of, graph_dump
from tests.storage.support import ID_A, ID_B, ID_C

if TYPE_CHECKING:
    from sankey_studio.storage import FileGraphRepository, MongoGraphRepository
    from tests.storage.conftest import RepoEnv

PREF = {"mode": "source", "target": "file:budget.csv"}
FILE_SOURCE = {"type": "text", "origin": "file", "path": "budget.csv", "write_back": PREF}
INLINE_SOURCE = {
    "type": "text",
    "origin": "inline",
    "content": "a,b,1",
    "write_back": {"mode": "graph", "target": "x"},
}
MONGO_SOURCE = {
    "type": "mongo",
    "connection": "main",
    "database": "flows",
    "collection": "moves",
    "write_back": {"mode": "source", "target": "mongo:main/flows/moves#0123456789ab"},
}
MODES: list[ImportMode] = ["new_ids", "keep_ids"]


class Case(NamedTuple):
    label: str
    source: dict[str, Any]


CASES = [
    Case("file", FILE_SOURCE),
    Case("mongo", MONGO_SOURCE),
    Case("inline", INLINE_SOURCE),
]


def with_source(source: dict[str, Any], graph_id: str = ID_A) -> dict[str, Any]:
    return {**graph_dump(graph_id, "g"), "source": source}


def consent_of(graph: GraphDefinition) -> object:
    """The saved write-back preference of a graph's source (``None`` for a source without one)."""
    return getattr(graph.source, "write_back", None)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("case", CASES, ids=[c.label for c in CASES])
def test_the_saved_consent_is_dropped_on_import(env: RepoEnv, case: Case, mode: ImportMode) -> None:
    report = import_bundle(env.repo, bundle_of([with_source(case.source)]), mode)
    assert (report.imported, report.failed, report.errors) == (1, 0, [])
    (stored,) = env.repo.iter_definitions()
    assert consent_of(stored) is None


@pytest.mark.parametrize("mode", MODES)
def test_the_rest_of_the_source_is_kept(env: RepoEnv, mode: ImportMode) -> None:
    import_bundle(env.repo, bundle_of([with_source(FILE_SOURCE)]), mode)
    (stored,) = env.repo.iter_definitions()
    dumped = stored.source.model_dump(mode="json")
    assert {k: v for k, v in dumped.items() if k in {"type", "origin", "path"}} == {
        "type": "text",
        "origin": "file",
        "path": "budget.csv",
    }


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("bad", ["yes", 5, ["source"], {"mode": "nope"}, {"mode": "source"}])
def test_an_unusable_consent_is_dropped_instead_of_failing_the_graph(
    env: RepoEnv, mode: ImportMode, bad: Any
) -> None:
    item = with_source({**FILE_SOURCE, "write_back": bad})
    report = import_bundle(env.repo, bundle_of([item]), mode)
    assert (report.imported, report.failed) == (1, 0)
    (stored,) = env.repo.iter_definitions()
    assert consent_of(stored) is None


@pytest.mark.parametrize("mode", MODES)
def test_a_graph_without_a_consent_is_imported_as_it_is(env: RepoEnv, mode: ImportMode) -> None:
    item = with_source({"type": "text", "origin": "file", "path": "budget.csv"})
    assert "write_back" not in item["source"]
    assert import_bundle(env.repo, bundle_of([item]), mode).imported == 1


@pytest.mark.parametrize("mode", MODES)
def test_a_manual_source_with_a_consent_is_still_refused(env: RepoEnv, mode: ImportMode) -> None:
    source = {"type": "manual", "links": [], "write_back": PREF}
    report = import_bundle(env.repo, bundle_of([with_source(source)]), mode)
    assert (report.imported, report.failed) == (0, 1)
    assert "write_back" in report.errors[0]


def test_every_graph_of_a_bundle_is_cleaned_not_only_the_first(env: RepoEnv) -> None:
    items = [
        with_source(FILE_SOURCE, ID_A),
        with_source(MONGO_SOURCE, ID_B),
        with_source(FILE_SOURCE, ID_C),
    ]
    assert import_bundle(env.repo, bundle_of(items), "keep_ids").imported == 3
    assert [consent_of(g) for g in env.repo.iter_definitions()] == [None] * 3


def test_an_export_keeps_the_consent_of_its_owner(env: RepoEnv) -> None:
    env.repo.put(GraphDefinition.model_validate(with_source(FILE_SOURCE)))
    assert export_bundle(env.repo)["graphs"][0]["source"]["write_back"] == PREF
    assert consent_of(env.repo.get(ID_A)) is not None


def test_a_copy_between_stores_keeps_the_consent(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    file_repo.put(GraphDefinition.model_validate(with_source(FILE_SOURCE)))
    assert copy_graphs(file_repo, mongo_repo).copied == 1
    assert consent_of(mongo_repo.get(ID_A)) is not None


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "source", ["text", 5, None, ["type"]], ids=["text", "number", "none", "list"]
)
def test_a_source_that_is_not_an_object_is_a_bad_graph_not_a_crash(
    env: RepoEnv, mode: ImportMode, source: Any
) -> None:
    report = import_bundle(env.repo, bundle_of([with_source(source)]), mode)
    assert (report.imported, report.failed) == (0, 1)
    assert report.errors[0].startswith("graph 1: source")
