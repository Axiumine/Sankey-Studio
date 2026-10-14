"""The exact driver calls the Mongo folder store makes (filters, projections, CAS, indexes)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import mongomock.collection
import pytest
from pymongo import ReturnDocument

from sankey_studio.errors import FolderNameTakenError, NotFoundError
from sankey_studio.models import FolderUpdate
from sankey_studio.storage import mongo_store
from sankey_studio.storage.base import MONGO_FOLDERS_COLLECTION, MONGO_GRAPHS_COLLECTION
from tests.storage.folder_builders import body, fid, folder
from tests.storage.support import ID_A, ID_B, ID_C, NOW, definition

if TYPE_CHECKING:
    from sankey_studio.storage import MongoFolderRepository, MongoGraphRepository
    from tests.storage.support import Ticker

METHODS = (
    "find",
    "find_one",
    "insert_one",
    "replace_one",
    "find_one_and_update",
    "delete_one",
    "update_many",
    "create_index",
    "count_documents",
    "distinct",
    "aggregate",
)
FOLDERS = MONGO_FOLDERS_COLLECTION
GRAPHS = MONGO_GRAPHS_COLLECTION
SUMMARY = mongo_store._SUMMARY_FIELDS
Call = tuple[str, str, tuple[Any, ...], dict[str, Any]]


class CallLog:
    """``(collection, method, args, kwargs)`` of the public driver calls (mongomock's own nested
    calls, such as ``find_one`` calling ``find``, are left out)."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._depth = 0

    def install(self, patch: pytest.MonkeyPatch) -> None:
        for name in METHODS:
            original = getattr(mongomock.collection.Collection, name)
            patch.setattr(mongomock.collection.Collection, name, self._wrap(name, original))

    def _wrap(self, name: str, original: Any) -> Any:
        def recorded(coll: Any, *args: Any, **kwargs: Any) -> Any:
            if self._depth == 0:
                self.calls.append((coll.name, name, args, kwargs))
            self._depth += 1
            try:
                return original(coll, *args, **kwargs)
            finally:
                self._depth -= 1

        return recorded

    def take(self) -> list[Call]:
        taken, self.calls = self.calls, []
        return taken

    def named(self, method: str) -> list[Call]:
        return [call for call in self.calls if call[1] == method]


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> CallLog:
    recorder = CallLog()
    recorder.install(monkeypatch)
    return recorder


def _put_graph(graphs: MongoGraphRepository, graph_id: str, folder_id: str | None) -> None:
    graphs.put(definition(graph_id, graph_id[:1]).model_copy(update={"folder_id": folder_id}))


# --------------------------------------------------------------------------- indexes


def test_the_first_write_creates_the_unique_sibling_index_once(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    mongo_folders.create_folder(body("a"))
    mongo_folders.create_folder(body("b"))
    [(name, _, args, kwargs)] = log.named("create_index")
    assert name == FOLDERS
    assert args == ([("parent_id", 1), ("name_key", 1)],)
    assert kwargs == {"unique": True}


def test_every_kind_of_write_prepares_the_index_and_reads_never_do(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    mongo_folders.list_folders()
    mongo_folders.list_definitions()
    mongo_folders.list_in("root")
    mongo_folders.count_in("root")
    mongo_folders.move_graphs([ID_A], None)
    assert log.named("create_index") == []


@pytest.mark.parametrize("write", ["create", "update", "delete", "put"])
def test_each_folder_write_creates_the_index_before_its_first_write(
    mongo_folders: MongoFolderRepository, log: CallLog, write: str
) -> None:
    seed = mongo_folders.put_folder(folder(1, "seed"))
    mongo_folders._indexed = False  # a fresh repository on an existing store
    log.take()
    if write == "create":
        mongo_folders.create_folder(body("new"))
    elif write == "update":
        mongo_folders.update_folder(seed.id, FolderUpdate(name="x", parent_id=None, revision=1))
    elif write == "delete":
        mongo_folders.delete_folder(seed.id)
    else:
        mongo_folders.put_folder(folder(2, "other"))
    methods = [call[1] for call in log.calls]
    assert methods[0] == "create_index"
    assert methods.count("create_index") == 1


def test_ping_creates_the_index_and_later_writes_do_not_repeat_it(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    mongo_folders.ping()
    assert [call[:2] for call in log.named("create_index")] == [(FOLDERS, "create_index")]
    mongo_folders.create_folder(body("a"))
    assert len(log.named("create_index")) == 1


# --------------------------------------------------------------------------- reads


def test_list_folders_reads_the_records_and_counts_graphs_with_one_pipeline(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    a = mongo_folders.create_folder(body("a"))
    b = mongo_folders.create_folder(body("b", a.id))
    log.take()
    mongo_folders.list_folders()
    [read, count] = log.calls
    assert read == (FOLDERS, "find", ({},), {})
    assert count[:2] == (GRAPHS, "aggregate")
    [pipeline] = count[2]
    [match, group] = pipeline
    assert sorted(match["$match"]["folder_id"]["$in"]) == sorted([a.id, b.id])
    assert list(match["$match"]) == ["folder_id"]
    assert list(match["$match"]["folder_id"]) == ["$in"]
    assert group == {"$group": {"_id": "$folder_id", "n": {"$sum": 1}}}
    assert count[3] == {}


def test_without_folders_there_is_nothing_to_count(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    assert mongo_folders.list_folders() == []
    assert [call[:2] for call in log.calls] == [(FOLDERS, "find")]


def test_list_definitions_and_get_read_the_folder_collection_only(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    box = mongo_folders.create_folder(body("box"))
    log.take()
    mongo_folders.list_definitions()
    mongo_folders.get_folder(box.id)
    assert log.calls == [
        (FOLDERS, "find", ({},), {}),
        (FOLDERS, "find_one", ({"_id": box.id},), {}),
    ]


def test_a_folder_scope_checks_the_folder_then_filters_the_graphs_by_it(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    box = mongo_folders.create_folder(body("box"))
    log.take()
    mongo_folders.list_in(box.id, limit=7, offset=3)
    assert log.calls == [
        (FOLDERS, "find_one", ({"_id": box.id}, {"_id": 1}), {}),
        (GRAPHS, "find", ({"folder_id": box.id}, SUMMARY), {}),
    ]


def test_the_top_level_scope_means_no_folder_or_a_folder_that_does_not_exist(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    box = mongo_folders.create_folder(body("box"))
    log.take()
    mongo_folders.list_in("root")
    flt = {"$or": [{"folder_id": None}, {"folder_id": {"$nin": [box.id]}}]}
    assert log.calls == [
        (FOLDERS, "distinct", ("_id",), {}),
        (GRAPHS, "find", (flt, SUMMARY), {}),
    ]


def test_the_listing_projection_is_a_copy_of_the_summary_fields(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    mongo_folders.list_in("root")
    [(_, _, args, _)] = log.named("find")
    assert args[1] is not SUMMARY
    assert args[1] == SUMMARY
    assert SUMMARY["folder_id"] == 1


def test_counting_uses_the_same_filters_as_listing(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    box = mongo_folders.create_folder(body("box"))
    log.take()
    mongo_folders.count_in(box.id)
    mongo_folders.count_in("root")
    flt = {"$or": [{"folder_id": None}, {"folder_id": {"$nin": [box.id]}}]}
    assert log.calls == [
        (FOLDERS, "find_one", ({"_id": box.id}, {"_id": 1}), {}),
        (GRAPHS, "count_documents", ({"folder_id": box.id},), {}),
        (FOLDERS, "distinct", ("_id",), {}),
        (GRAPHS, "count_documents", (flt,), {}),
    ]


def test_an_unknown_folder_costs_one_lookup_and_no_graph_query(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    assert mongo_folders.list_in(fid(9)) == []
    assert mongo_folders.count_in(fid(9)) == 0
    assert [call[:2] for call in log.calls] == [(FOLDERS, "find_one")] * 2


@pytest.mark.parametrize("limit", [0, -1])
def test_a_page_of_zero_never_reaches_the_server(
    mongo_folders: MongoFolderRepository, log: CallLog, limit: int
) -> None:
    """Mongo reads ``limit(0)`` as "no limit": the store answers before asking."""
    assert mongo_folders.list_in("root", limit=limit) == []
    assert log.calls == []


def test_a_malformed_scope_or_id_never_reaches_the_server(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    for scope in ("", "../x", "ROOT"):
        with pytest.raises(NotFoundError):
            mongo_folders.list_in(scope)
        with pytest.raises(NotFoundError):
            mongo_folders.count_in(scope)
        with pytest.raises(NotFoundError):
            mongo_folders.get_folder(scope)
        with pytest.raises(NotFoundError):
            mongo_folders.delete_folder(scope)
    assert log.calls == []


# --------------------------------------------------------------------------- writes


def test_create_inserts_one_document_after_reading_the_siblings(
    mongo_folders: MongoFolderRepository, log: CallLog, clock: Ticker
) -> None:
    mongo_folders.ping()
    log.take()
    created = mongo_folders.create_folder(body("Docs"))
    assert [call[:2] for call in log.calls] == [(FOLDERS, "find"), (FOLDERS, "insert_one")]
    [(_, _, args, kwargs)] = log.named("insert_one")
    assert kwargs == {}
    assert args[0] == {
        "_id": created.id,
        "name": "Docs",
        "name_key": "docs",
        "parent_id": None,
        "schema_version": 1,
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    assert clock.calls == 1


def test_update_is_one_compare_and_set_on_id_and_revision(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    box = mongo_folders.create_folder(body("box"))
    other = mongo_folders.create_folder(body("other"))
    log.take()
    mongo_folders.update_folder(box.id, FolderUpdate(name="New", parent_id=other.id, revision=1))
    [(coll, _, args, kwargs)] = log.named("find_one_and_update")
    assert coll == FOLDERS
    assert args[0] == {"_id": box.id, "revision": 1}
    assert args[1] == {
        "$set": {
            "name": "New",
            "name_key": "new",
            "parent_id": other.id,
            "revision": 2,
            "updated_at": NOW.replace(second=2),
        }
    }
    assert kwargs == {"return_document": ReturnDocument.AFTER}


def test_delete_moves_the_graphs_first_then_drops_the_record_then_the_children(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    top = mongo_folders.create_folder(body("top"))
    mid = mongo_folders.create_folder(body("mid", top.id))
    mongo_folders.create_folder(body("low", mid.id))
    log.take()
    mongo_folders.delete_folder(mid.id)
    steps = [(c[0], c[1]) for c in log.calls if c[1] in ("update_many", "delete_one")]
    assert steps == [(GRAPHS, "update_many"), (FOLDERS, "delete_one"), (FOLDERS, "update_many")]
    graphs_step, remove, children = (c for c in log.calls if c[1] in ("update_many", "delete_one"))
    assert graphs_step[2] == ({"folder_id": mid.id}, {"$set": {"folder_id": top.id}})
    assert remove[2] == ({"_id": mid.id},)
    assert children[2][0] == {"parent_id": mid.id}
    update = children[2][1]
    assert set(update) == {"$set", "$inc"}
    assert update["$inc"] == {"revision": 1}
    assert update["$set"]["parent_id"] == top.id
    assert update["$set"]["updated_at"] == NOW.replace(second=3)


def test_deleting_a_top_level_folder_moves_its_graphs_to_the_top(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    box = mongo_folders.create_folder(body("box"))
    log.take()
    mongo_folders.delete_folder(box.id)
    [(_, _, args, _)] = log.named("update_many")
    assert args == ({"folder_id": box.id}, {"$set": {"folder_id": None}})


def test_a_folder_without_children_makes_no_folder_update_on_delete(
    mongo_folders: MongoFolderRepository, log: CallLog, clock: Ticker
) -> None:
    box = mongo_folders.create_folder(body("box"))
    log.take()
    before = clock.calls
    mongo_folders.delete_folder(box.id)
    assert [c[0] for c in log.named("update_many")] == [GRAPHS]
    assert clock.calls == before  # nothing was re-parented, so no time was needed


def test_a_clashing_delete_touches_nothing(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    top = mongo_folders.create_folder(body("top"))
    docs = mongo_folders.create_folder(body("Docs", top.id))
    mongo_folders.create_folder(body("Reports", top.id))
    mongo_folders.create_folder(body("reports", docs.id))
    log.take()
    with pytest.raises(FolderNameTakenError):
        mongo_folders.delete_folder(docs.id)
    assert log.named("update_many") == []
    assert log.named("delete_one") == []


def test_put_inserts_a_new_folder_and_replaces_an_existing_one_by_id(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    mongo_folders.ping()
    log.take()
    mongo_folders.put_folder(folder(5, "Five"))
    assert [c[:2] for c in log.calls] == [(FOLDERS, "find"), (FOLDERS, "insert_one")]
    log.take()
    mongo_folders.put_folder(folder(5, "Six", revision=3), overwrite=True)
    [(_, _, args, kwargs)] = log.named("replace_one")
    assert args[0] == {"_id": fid(5)}
    assert args[1]["name"] == "Six"
    assert args[1]["name_key"] == "six"
    assert args[1]["revision"] == 3
    assert kwargs == {"upsert": True}
    assert log.named("insert_one") == []


def test_a_move_asks_which_graphs_exist_and_sets_only_the_folder_field(
    mongo_folders: MongoFolderRepository, mongo_repo: MongoGraphRepository, log: CallLog
) -> None:
    box = mongo_folders.create_folder(body("box"))
    _put_graph(mongo_repo, ID_B, None)
    _put_graph(mongo_repo, ID_A, None)
    log.take()
    report = mongo_folders.move_graphs([ID_C, ID_B, ID_A, ID_B], box.id)
    assert (report.moved, report.missing) == (2, [ID_C])
    assert log.calls == [
        (FOLDERS, "find_one", ({"_id": box.id}, {"_id": 1}), {}),
        (GRAPHS, "distinct", ("_id", {"_id": {"$in": [ID_C, ID_B, ID_A]}}), {}),
        (
            GRAPHS,
            "update_many",
            ({"_id": {"$in": [ID_A, ID_B]}}, {"$set": {"folder_id": box.id}}),
            {},
        ),
    ]


def test_a_move_to_the_top_level_does_not_look_for_a_folder(
    mongo_folders: MongoFolderRepository, mongo_repo: MongoGraphRepository, log: CallLog
) -> None:
    _put_graph(mongo_repo, ID_A, fid(7))
    log.take()
    mongo_folders.move_graphs([ID_A], None)
    assert [c[:2] for c in log.calls] == [(GRAPHS, "distinct"), (GRAPHS, "update_many")]
    assert log.calls[1][2][1] == {"$set": {"folder_id": None}}


def test_malformed_ids_in_a_move_reach_the_server_never(
    mongo_folders: MongoFolderRepository, log: CallLog
) -> None:
    for graphs, target in ((["../x"], None), ([ID_A], "../x"), ([ID_A], "root")):
        with pytest.raises(NotFoundError):
            mongo_folders.move_graphs(graphs, target)
    assert log.calls == []


def test_the_store_writes_only_to_its_two_collections_and_only_those_fields(
    mongo_folders: MongoFolderRepository, mongo_repo: MongoGraphRepository, log: CallLog
) -> None:
    top = mongo_folders.create_folder(body("top"))
    mongo_folders.create_folder(body("kid", top.id))
    _put_graph(mongo_repo, ID_A, top.id)
    log.take()
    mongo_folders.move_graphs([ID_A], None)
    mongo_folders.delete_folder(top.id)
    for coll, method, args, _ in log.calls:
        assert coll in {FOLDERS, GRAPHS}
        if coll == GRAPHS and method == "update_many":
            assert list(args[1]) == ["$set"]
            assert list(args[1]["$set"]) == ["folder_id"]
