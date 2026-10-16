# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``copy_graphs``: backend migration."""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import ConflictError, StorageError
from sankey_studio.storage import CopyReport, FileGraphRepository, MongoGraphRepository, copy_graphs
from sankey_studio.storage import migrate as migrate_module
from sankey_studio.storage.files.codec import graph_filename
from sankey_studio.storage.migrate import MAX_UNREADABLE_IDS
from sankey_studio.storage.mongo_store import _encode
from tests.storage.support import ID_A, ID_B, ID_C, NOW, Spec, definition

if TYPE_CHECKING:
    from pathlib import Path

    from pymongo.collection import Collection

    from sankey_studio.models import GraphDefinition
    from sankey_studio.storage.base import GraphRepository


def _seed(repo: GraphRepository) -> list[GraphDefinition]:
    graphs = [
        definition(ID_A, "a", Spec(tags=("x",), revision=5, updated_at=NOW + timedelta(days=2))),
        definition(ID_B, "b", Spec(updated_at=NOW + timedelta(days=1))),
        definition(ID_C, "c", spec=Spec("about c", ("y", "z"), links=3)),
    ]
    for graph in graphs:
        repo.put(graph)
    return graphs


def test_everything_is_copied_verbatim(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    graphs = _seed(file_repo)
    report = copy_graphs(file_repo, mongo_repo)
    assert report == CopyReport(copied=3, skipped=0)
    assert list(mongo_repo.iter_definitions()) == graphs  # ids, revisions, timestamps, content
    assert mongo_repo.get(ID_A).revision == 5
    assert list(file_repo.iter_definitions()) == graphs  # the source is untouched


def test_copying_back_to_files_works_too(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    graphs = _seed(mongo_repo)
    assert copy_graphs(mongo_repo, file_repo) == CopyReport(3, 0)
    assert list(file_repo.iter_definitions()) == graphs


def test_an_empty_source_copies_nothing(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    assert copy_graphs(file_repo, mongo_repo) == CopyReport(0, 0)
    assert mongo_repo.count() == 0


def test_existing_graphs_are_skipped_by_default(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    graphs = _seed(file_repo)
    mine = definition(ID_B, "destination wins", Spec(revision=9))
    mongo_repo.put(mine)
    report = copy_graphs(file_repo, mongo_repo)
    assert report == CopyReport(copied=2, skipped=1)
    assert mongo_repo.get(ID_B) == mine
    assert mongo_repo.get(ID_A) == graphs[0]
    assert mongo_repo.count() == 3


def test_on_conflict_overwrite_replaces_them(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    graphs = _seed(file_repo)
    mongo_repo.put(definition(ID_B, "old", Spec(revision=9)))
    report = copy_graphs(file_repo, mongo_repo, on_conflict="overwrite")
    assert report == CopyReport(copied=3, skipped=0)
    assert mongo_repo.get(ID_B) == graphs[1]


def test_a_copy_is_idempotent(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    _seed(file_repo)
    assert copy_graphs(file_repo, mongo_repo) == CopyReport(3, 0)
    assert copy_graphs(file_repo, mongo_repo) == CopyReport(0, 3)
    assert copy_graphs(file_repo, mongo_repo, on_conflict="skip") == CopyReport(0, 3)
    assert copy_graphs(file_repo, mongo_repo, on_conflict="overwrite") == CopyReport(3, 0)
    assert mongo_repo.count() == 3


class RecordingRepo(FileGraphRepository):
    """A real file repository that records every ``put`` and can fail or conflict on the n-th."""

    def __init__(self, directory: Path, plan: Plan | None = None) -> None:
        super().__init__(directory)
        self.puts: list[tuple[str, bool]] = []
        self.plan = plan or Plan()

    def put(self, graph: GraphDefinition, *, overwrite: bool = False) -> GraphDefinition:
        self.puts.append((graph.id, overwrite))
        if self.plan.conflict_on == len(self.puts):
            raise ConflictError("exists")
        return super().put(graph, overwrite=overwrite)


@dataclasses.dataclass(slots=True)
class Plan:
    conflict_on: int | None = None


def test_graphs_are_put_in_listing_order_with_the_requested_overwrite_flag(
    file_repo: FileGraphRepository, tmp_path: Path
) -> None:
    _seed(file_repo)  # listing order: a (newest), b, c
    skip, over = RecordingRepo(tmp_path / "skip"), RecordingRepo(tmp_path / "over")
    copy_graphs(file_repo, skip)
    copy_graphs(file_repo, over, on_conflict="overwrite")
    assert skip.puts == [(ID_A, False), (ID_B, False), (ID_C, False)]
    assert over.puts == [(ID_A, True), (ID_B, True), (ID_C, True)]


def test_a_conflict_is_counted_wherever_it_happens(
    file_repo: FileGraphRepository, tmp_path: Path
) -> None:
    _seed(file_repo)
    sink = RecordingRepo(tmp_path / "sink", Plan(conflict_on=2))
    assert copy_graphs(file_repo, sink) == CopyReport(copied=2, skipped=1)
    assert len(sink.puts) == 3
    assert sink.count() == 2


def test_a_backend_failure_aborts_the_copy_and_a_retry_finishes_it(
    file_repo: FileGraphRepository,
    mongo_repo: MongoGraphRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graphs = _seed(file_repo)
    real_put = mongo_repo.put
    calls: list[str] = []

    def flaky(graph: GraphDefinition, *, overwrite: bool = False) -> GraphDefinition:
        calls.append(graph.id)
        if len(calls) == 2:
            raise StorageError("connection lost")
        return real_put(graph, overwrite=overwrite)

    monkeypatch.setattr(mongo_repo, "put", flaky)
    with pytest.raises(StorageError, match="connection lost"):
        copy_graphs(file_repo, mongo_repo)
    assert calls == [ID_A, ID_B]  # nothing is attempted after the failure
    assert [g.id for g in mongo_repo.iter_definitions()] == [ID_A]  # what was copied stays
    assert list(file_repo.iter_definitions()) == graphs  # the source is never touched
    monkeypatch.undo()
    assert copy_graphs(file_repo, mongo_repo) == CopyReport(copied=2, skipped=1)
    assert mongo_repo.count() == 3


def test_the_report_is_a_frozen_value() -> None:
    report = CopyReport(copied=2, skipped=1)
    assert dataclasses.asdict(report) == {
        "copied": 2,
        "skipped": 1,
        "unreadable": 0,
        "unreadable_ids": (),
        "folders": 0,
        "folders_skipped": 0,
    }
    assert report == CopyReport(2, 1)
    assert report != CopyReport(1, 2)
    assert report != CopyReport(2, 1, 1, ("x",))
    assert report != CopyReport(2, 1, folders=1)
    assert report != CopyReport(2, 1, folders_skipped=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.copied = 5  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.unreadable = 5  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.folders = 5  # type: ignore[misc]


def test_an_unknown_conflict_policy_is_refused_before_anything_is_copied(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    _seed(file_repo)
    with pytest.raises(KeyError):
        copy_graphs(file_repo, mongo_repo, on_conflict="merge")  # type: ignore[arg-type]
    assert mongo_repo.count() == 0


# --------------------------------------------------------------------------- unreadable graphs


@dataclasses.dataclass(slots=True)
class Rig:
    """A file repository (and its directory) to copy from, a Mongo repository to copy to."""

    files: FileGraphRepository
    mongo: MongoGraphRepository
    directory: Path


@pytest.fixture
def rig(file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository, tmp_path: Path) -> Rig:
    return Rig(file_repo, mongo_repo, tmp_path / "graphs")


def _damage_files(directory: Path, *, corrupt: tuple[str, ...], newer: tuple[str, ...]) -> None:
    for graph_id in corrupt:
        (directory / graph_filename(graph_id)).write_bytes(b"{broken")
    for graph_id in newer:
        doc = json.loads(definition(graph_id, "future").model_dump_json())
        doc["schema_version"] = 99
        (directory / graph_filename(graph_id)).write_text(json.dumps(doc))


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == migrate_module.__name__
    ]


def test_unreadable_source_graphs_are_counted_named_and_logged(
    file_repo: FileGraphRepository,
    mongo_repo: MongoGraphRepository,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    file_repo.put(definition(ID_A, "good"))
    _damage_files(tmp_path / "graphs", corrupt=(ID_C,), newer=(ID_B,))
    with caplog.at_level(logging.WARNING):
        report = copy_graphs(file_repo, mongo_repo)
    assert report == CopyReport(copied=1, skipped=0, unreadable=2, unreadable_ids=(ID_B, ID_C))
    assert [g.id for g in mongo_repo.iter_definitions()] == [ID_A]
    assert _warnings(caplog) == ["2 stored graph(s) are unreadable and were not copied"]
    assert (tmp_path / "graphs" / graph_filename(ID_C)).read_bytes() == b"{broken"  # untouched


def test_unreadable_graphs_of_a_mongo_source_are_reported_too(
    file_repo: FileGraphRepository,
    mongo_repo: MongoGraphRepository,
    mongo_collection: Collection[Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    mongo_repo.put(definition(ID_A, "good"))
    raw = _encode(definition(ID_B, "future"))
    mongo_collection.insert_one({**raw, "schema_version": 99})
    mongo_collection.insert_one({**_encode(definition(ID_C, "bad")), "name": None})
    with caplog.at_level(logging.WARNING):
        report = copy_graphs(mongo_repo, file_repo, on_conflict="overwrite")
    assert report == CopyReport(1, 0, 2, (ID_B, ID_C))
    assert [g.id for g in file_repo.iter_definitions()] == [ID_A]
    assert len(_warnings(caplog)) == 1


def test_a_clean_copy_reports_no_unreadable_graph_and_logs_nothing(
    file_repo: FileGraphRepository,
    mongo_repo: MongoGraphRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed(file_repo)
    with caplog.at_level(logging.DEBUG):
        report = copy_graphs(file_repo, mongo_repo)
    assert (report.unreadable, report.unreadable_ids) == (0, ())
    assert _warnings(caplog) == []


class Capped(NamedTuple):
    total: int
    named: int


@pytest.mark.parametrize(
    "case",
    [
        Capped(1, 1),
        Capped(MAX_UNREADABLE_IDS - 1, MAX_UNREADABLE_IDS - 1),
        Capped(MAX_UNREADABLE_IDS, MAX_UNREADABLE_IDS),
        Capped(MAX_UNREADABLE_IDS + 1, MAX_UNREADABLE_IDS),
        Capped(MAX_UNREADABLE_IDS + 7, MAX_UNREADABLE_IDS),
    ],
)
def test_the_unreadable_ids_are_capped_but_the_count_is_not(
    rig: Rig, caplog: pytest.LogCaptureFixture, case: Capped
) -> None:
    ids = tuple(f"{number:032x}" for number in range(1, case.total + 1))
    _damage_files(rig.directory, corrupt=ids, newer=())
    with caplog.at_level(logging.WARNING):
        report = copy_graphs(rig.files, rig.mongo)
    assert report.unreadable == case.total
    assert report.unreadable_ids == ids[: case.named]
    assert len(report.unreadable_ids) == case.named
    assert _warnings(caplog) == [f"{case.total} stored graph(s) are unreadable and were not copied"]


def test_the_cap_is_fifty() -> None:
    assert MAX_UNREADABLE_IDS == 50


def test_unreadable_graphs_do_not_change_the_other_counts(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository, tmp_path: Path
) -> None:
    _seed(file_repo)
    mongo_repo.put(definition(ID_B, "mine"))
    _damage_files(tmp_path / "graphs", corrupt=("d" * 32,), newer=())
    assert copy_graphs(file_repo, mongo_repo) == CopyReport(2, 1, 1, ("d" * 32,))
    assert copy_graphs(file_repo, mongo_repo, on_conflict="overwrite") == CopyReport(
        3, 0, 1, ("d" * 32,)
    )


def test_a_backend_failure_still_aborts_before_unreadable_graphs_are_looked_up(
    file_repo: FileGraphRepository,
    mongo_repo: MongoGraphRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(file_repo)
    _damage_files(tmp_path / "graphs", corrupt=("d" * 32,), newer=())

    def lost(*_args: object, **_kwargs: object) -> None:
        raise StorageError("connection lost")

    def not_reached() -> list[str]:
        raise AssertionError("unreadable_ids must not run after a failed copy")

    monkeypatch.setattr(mongo_repo, "put", lost)
    monkeypatch.setattr(file_repo, "unreadable_ids", not_reached)
    with pytest.raises(StorageError, match="connection lost"):
        copy_graphs(file_repo, mongo_repo)
