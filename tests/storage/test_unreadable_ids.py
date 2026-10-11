"""``GraphRepository.unreadable_ids``: stored records that ``iter_definitions`` cannot yield."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from bson import ObjectId

from sankey_studio.storage.files.codec import graph_filename
from sankey_studio.storage.mongo_store import ITER_PAGE, _encode
from tests.storage.support import ID_A, ID_B, ID_C, ID_D, NOW, definition

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from pymongo.collection import Collection

    from sankey_studio.storage import FileGraphRepository, MongoGraphRepository
    from sankey_studio.storage.base import GraphRepository

KINDS = ["corrupt", "newer"]


@dataclass(slots=True)
class Store:
    """One backend plus a way to leave an unreadable record behind in it."""

    kind: str
    repo: GraphRepository
    damage: Callable[..., None]  # (graph_id, kind, updated_at=NOW)


def _file_damage(directory: Path) -> Callable[..., None]:
    def damage(graph_id: str, kind: str, updated_at: datetime = NOW) -> None:
        doc = json.loads(definition(graph_id, "damaged").model_dump_json())
        doc["updated_at"] = updated_at.isoformat()
        doc["schema_version"] = 99
        body = json.dumps(doc).encode() if kind == "newer" else b"{broken"
        (directory / graph_filename(graph_id)).write_bytes(body)

    return damage


def _mongo_damage(collection: Collection[Any]) -> Callable[..., None]:
    def damage(graph_id: str, kind: str, updated_at: datetime = NOW) -> None:
        raw = _encode(definition(graph_id, "damaged"))
        raw["updated_at"] = updated_at
        changes = {"schema_version": 99} if kind == "newer" else {"name": None}
        collection.insert_one({**raw, **changes})

    return damage


@pytest.fixture(params=["file", "mongo"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Store:
    if request.param == "file":
        return Store(
            "file", request.getfixturevalue("file_repo"), _file_damage(tmp_path / "graphs")
        )
    mongo_collection = request.getfixturevalue("mongo_collection")
    return Store("mongo", request.getfixturevalue("mongo_repo"), _mongo_damage(mongo_collection))


def test_an_empty_store_has_nothing_unreadable(store: Store) -> None:
    assert store.repo.unreadable_ids() == []


def test_a_store_of_healthy_graphs_has_nothing_unreadable(store: Store) -> None:
    for graph_id in (ID_A, ID_B):
        store.repo.put(definition(graph_id, "ok"))
    assert store.repo.unreadable_ids() == []


@pytest.mark.parametrize("kind", KINDS)
def test_a_damaged_record_is_named_and_the_healthy_ones_are_not(store: Store, kind: str) -> None:
    store.repo.put(definition(ID_B, "ok"))
    store.damage(ID_A, kind)
    assert store.repo.unreadable_ids() == [ID_A]
    assert [g.id for g in store.repo.iter_definitions()] == [ID_B]  # the two views agree


def test_every_damaged_record_is_named_in_a_stable_order(store: Store) -> None:
    store.damage(ID_C, "corrupt")
    store.repo.put(definition(ID_B, "ok"))
    store.damage(ID_D, "newer")
    store.damage(ID_A, "corrupt")
    assert store.repo.unreadable_ids() == [ID_A, ID_C, ID_D]
    assert store.repo.unreadable_ids() == [ID_A, ID_C, ID_D]


def test_a_record_leaves_the_list_when_it_is_repaired_or_deleted(store: Store) -> None:
    store.damage(ID_A, "corrupt")
    store.damage(ID_B, "newer")
    store.repo.put(definition(ID_A, "repaired"), overwrite=True)
    assert store.repo.unreadable_ids() == [ID_B]
    store.repo.delete(ID_B)
    assert store.repo.unreadable_ids() == []


def test_a_graph_that_turns_unreadable_joins_the_list(store: Store) -> None:
    store.repo.put(definition(ID_A, "ok"))
    assert store.repo.unreadable_ids() == []
    if store.kind == "mongo":
        store.repo.delete(ID_A)
    store.damage(ID_A, "corrupt")
    assert store.repo.unreadable_ids() == [ID_A]


@pytest.mark.parametrize("total", [ITER_PAGE, ITER_PAGE + 1, 2 * ITER_PAGE + 1])
def test_a_damaged_record_is_found_after_the_first_page(store: Store, total: int) -> None:
    """The newest graphs come first, so the damaged (oldest) record sits on the last page."""
    for number in range(total - 1):
        store.repo.put(definition(f"{number + 16:032x}", "ok"))
    store.damage(ID_A, "newer", NOW.replace(year=2000))
    assert store.repo.unreadable_ids() == [ID_A]
    assert len(list(store.repo.iter_definitions())) == total - 1


# --------------------------------------------------------------------------- per backend


def test_files_that_are_not_graphs_are_not_reported(
    file_repo: FileGraphRepository, tmp_path: Path
) -> None:
    directory = tmp_path / "graphs"
    (directory / "notes.json").write_text("{broken")
    (directory / f"{ID_A}.json.tmp").write_text("{broken")
    (directory / f"{ID_B[:-1]}.json").write_text("{broken")  # 31 characters
    (directory / graph_filename(ID_C)).mkdir()  # a directory is not a graph file
    (directory / graph_filename(ID_D)).symlink_to(directory / "notes.json")
    assert file_repo.unreadable_ids() == []


def test_a_mongo_id_is_reported_as_text(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    foreign = ObjectId()
    raw = _encode(definition(ID_A, "x"))
    mongo_collection.insert_one({**raw, "_id": foreign})
    assert mongo_repo.unreadable_ids() == [str(foreign)]


def test_a_mongo_record_with_an_unreadable_encoded_field_is_named(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    raw = _encode(definition(ID_A, "x"))
    mongo_collection.insert_one({**raw, "style": {"node_colors": [["only-a-key"]]}})
    assert mongo_repo.unreadable_ids() == [ID_A]
