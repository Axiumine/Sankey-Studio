"""``GraphDefinition.folder_id`` in both graph repositories: create, update, put, summaries."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from sankey_studio.models import GraphDefinition
from tests.storage.folder_builders import fid
from tests.storage.support import ID_A, ID_B, create_data, definition, update_data

if TYPE_CHECKING:
    from pathlib import Path

    from pymongo.collection import Collection

    from sankey_studio.storage import FileGraphRepository, MongoGraphRepository
    from tests.storage.conftest import RepoEnv

BOX = fid(1)
OTHER = fid(2)


def _raw(collection: Collection[Any], graph_id: str) -> dict[str, Any]:
    found: dict[str, Any] | None = collection.find_one({"_id": graph_id})
    assert found is not None
    return found


def _in(graph_id: str, folder_id: str | None) -> GraphDefinition:
    return GraphDefinition.model_validate(
        {**definition(graph_id).model_dump(), "folder_id": folder_id}
    )


# --------------------------------------------------------------------------- both backends


def test_a_new_graph_sits_at_the_top_level_by_default(env: RepoEnv) -> None:
    created = env.repo.create(create_data("g"))
    assert created.folder_id is None
    assert env.repo.get(created.id).folder_id is None
    assert env.repo.list_graphs()[0].folder_id is None


def test_a_graph_can_be_created_inside_a_folder(env: RepoEnv) -> None:
    created = env.repo.create(create_data("g"), folder_id=BOX)
    assert created.folder_id == BOX
    assert env.repo.get(created.id) == created
    assert [row.folder_id for row in env.repo.list_graphs()] == [BOX]
    assert next(iter(env.repo.iter_definitions())).folder_id == BOX


def test_create_with_a_malformed_folder_id_stores_nothing(env: RepoEnv) -> None:
    with pytest.raises(ValidationError):
        env.repo.create(create_data("g"), folder_id="../x")
    assert env.repo.count() == 0


def test_an_update_never_changes_the_folder_and_bumps_the_revision(env: RepoEnv) -> None:
    created = env.repo.create(create_data("g"), folder_id=BOX)
    updated = env.repo.update(created.id, update_data(1, "renamed"))
    assert (updated.folder_id, updated.revision, updated.name) == (BOX, 2, "renamed")
    stored = env.repo.get(created.id)
    assert stored == updated
    assert env.repo.list_graphs()[0].folder_id == BOX


def test_an_update_of_a_top_level_graph_stays_at_the_top(env: RepoEnv) -> None:
    created = env.repo.create(create_data("g"))
    assert env.repo.update(created.id, update_data(1, "renamed")).folder_id is None


def test_put_stores_the_folder_verbatim_and_overwrite_replaces_it(env: RepoEnv) -> None:
    env.repo.put(_in(ID_A, BOX))
    assert env.repo.get(ID_A).folder_id == BOX
    env.repo.put(_in(ID_A, OTHER), overwrite=True)
    assert env.repo.get(ID_A).folder_id == OTHER
    env.repo.put(_in(ID_A, None), overwrite=True)
    assert env.repo.get(ID_A).folder_id is None


def test_the_summary_of_every_row_names_its_folder(env: RepoEnv) -> None:
    env.repo.put(_in(ID_A, BOX))
    env.repo.put(_in(ID_B, None))
    rows = {row.id: row.folder_id for row in env.repo.list_graphs()}
    assert rows == {ID_A: BOX, ID_B: None}


def test_a_dangling_folder_id_is_kept_as_it_is(env: RepoEnv) -> None:
    env.repo.put(_in(ID_A, fid(0xDEAD)))
    assert env.repo.get(ID_A).folder_id == fid(0xDEAD)


# --------------------------------------------------------------------------- the file backend


def test_a_file_written_before_folders_existed_reads_as_top_level(
    file_repo: FileGraphRepository, tmp_path: Path
) -> None:
    dump = definition(ID_A, "old").model_dump(mode="json")
    del dump["folder_id"]
    (tmp_path / "graphs" / f"{ID_A}.json").write_text(json.dumps(dump))
    assert file_repo.get(ID_A).folder_id is None
    assert file_repo.list_graphs()[0].folder_id is None


def test_the_file_holds_the_folder_id(file_repo: FileGraphRepository, tmp_path: Path) -> None:
    file_repo.create(create_data("g"), folder_id=BOX)
    [stored] = list((tmp_path / "graphs").iterdir())
    assert json.loads(stored.read_text())["folder_id"] == BOX


# --------------------------------------------------------------------------- the Mongo backend


def test_the_document_holds_the_folder_id_and_none_for_the_top_level(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    inside = mongo_repo.create(create_data("in"), folder_id=BOX)
    loose = mongo_repo.create(create_data("loose"))
    assert _raw(mongo_collection, inside.id)["folder_id"] == BOX
    raw = _raw(mongo_collection, loose.id)
    assert "folder_id" in raw
    assert raw["folder_id"] is None


def test_a_document_without_a_folder_id_reads_as_top_level(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    created = mongo_repo.create(create_data("old"))
    mongo_collection.update_one({"_id": created.id}, {"$unset": {"folder_id": ""}})
    assert mongo_repo.get(created.id).folder_id is None
    assert mongo_repo.list_graphs()[0].folder_id is None


def test_a_summary_with_a_malformed_folder_id_is_skipped_with_a_warning(
    mongo_repo: MongoGraphRepository,
    mongo_collection: Collection[Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    good = mongo_repo.create(create_data("good"))
    bad = mongo_repo.create(create_data("bad"))
    mongo_collection.update_one({"_id": bad.id}, {"$set": {"folder_id": "../x"}})
    caplog.set_level(logging.WARNING)
    assert [row.id for row in mongo_repo.list_graphs()] == [good.id]
    assert f"Skipping unreadable stored graph '{bad.id}'" in [
        r.getMessage() for r in caplog.records
    ]
