"""The exact driver calls the Mongo store makes (filters, projections, CAS, indexes)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, NamedTuple

import mongomock.collection
import pytest
from pymongo import ReturnDocument

from sankey_studio.storage import mongo_store
from sankey_studio.storage.mongo_store import _filter
from tests.storage.mongo_fakes import Recorder
from tests.storage.support import ID_A, ID_B, NOW, Spec, create_data, definition, update_data

if TYPE_CHECKING:
    from pymongo.collection import Collection

    from sankey_studio.storage import MongoGraphRepository

METHODS = (
    "find",
    "find_one",
    "insert_one",
    "replace_one",
    "find_one_and_update",
    "delete_one",
    "create_index",
    "count_documents",
    "distinct",
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    for name in METHODS:
        original = getattr(mongomock.collection.Collection, name)
        monkeypatch.setattr(mongomock.collection.Collection, name, recorder.wrap(name, original))
    return recorder


def _projected_reads(calls: Recorder) -> list[tuple[Any, ...]]:
    """``find_one`` calls that carry a projection (mongomock also calls ``find_one`` itself)."""
    return [a for a, _ in calls.named("find_one") if len(a) > 1 and a[1] is not None]


# --------------------------------------------------------------------------- _filter


class Filt(NamedTuple):
    query: str | None
    tag: str | None
    expected: dict[str, Any]


def _any_field(pattern: str) -> dict[str, Any]:
    regex = {"$regex": pattern, "$options": "i"}
    return {"$or": [{"name": regex}, {"description": regex}, {"tags": regex}]}


@pytest.mark.parametrize(
    "case",
    [
        Filt(None, None, {}),
        Filt("", None, {}),
        Filt("  ", None, {}),
        Filt("abc", None, _any_field("abc")),
        Filt("  abc  ", None, _any_field("abc")),
        Filt("a.b", None, _any_field(re.escape("a.b"))),
        Filt(".*", None, _any_field(r"\.\*")),
        Filt("$x (y) [z]", None, _any_field(re.escape("$x (y) [z]"))),
        Filt("x" * 300, None, _any_field("x" * 200)),
        Filt(None, "t", {"tags": "t"}),
        Filt(None, "", {}),
        Filt("abc", "t", {**_any_field("abc"), "tags": "t"}),
    ],
)
def test_filter(case: Filt) -> None:
    assert _filter(case.query, case.tag) == case.expected


def test_a_search_term_is_matched_literally_by_the_server() -> None:
    assert re.fullmatch(_filter(".*", None)["$or"][0]["name"]["$regex"], ".*") is not None
    assert re.fullmatch(_filter(".*", None)["$or"][0]["name"]["$regex"], "anything") is None


# --------------------------------------------------------------------------- reads


def test_a_listing_asks_for_summaries_only_in_the_documented_order(
    mongo_repo: MongoGraphRepository, calls: Recorder
) -> None:
    mongo_repo.put(definition(ID_A, "a"))
    calls.calls.clear()
    mongo_repo.list_graphs(query="a", tag="t", limit=7, offset=3)
    [(args, kwargs)] = calls.named("find")
    assert args[0] == _filter("a", "t")
    assert {k: v for k, v in args[1].items() if k != "_id"} == mongo_store._SUMMARY_FIELDS  # copy
    assert len(args) == 2
    assert kwargs == {}
    assert mongo_store._SUMMARY_FIELDS == {
        "name": 1,
        "description": 1,
        "tags": 1,
        "source.type": 1,
        "revision": 1,
        "updated_at": 1,
    }
    assert mongo_store._SORT == [("updated_at", -1), ("_id", 1)]


def test_the_default_page_size_is_exactly_two_hundred(mongo_repo: MongoGraphRepository) -> None:
    for i in range(201):
        mongo_repo.put(definition(f"{i:032x}", f"g{i}"))
    assert mongo_repo.count() == 201
    assert len(mongo_repo.list_graphs()) == 200
    assert len(mongo_repo.list_graphs(offset=200)) == 1


def test_a_zero_limit_never_reaches_the_server(
    mongo_repo: MongoGraphRepository, calls: Recorder
) -> None:
    """Mongo reads ``limit(0)`` as "no limit"."""
    mongo_repo.put(definition(ID_A, "a"))
    calls.calls.clear()
    assert mongo_repo.list_graphs(limit=0) == []
    assert mongo_repo.list_graphs(limit=-5) == []
    assert calls.named("find") == []


def test_count_all_tags_and_get_use_the_plain_queries(
    mongo_repo: MongoGraphRepository, calls: Recorder
) -> None:
    mongo_repo.put(definition(ID_A, "a", spec=Spec(tags=("x",))))
    calls.calls.clear()
    mongo_repo.count(query="a", tag="x")
    mongo_repo.all_tags()
    mongo_repo.get(ID_A)
    assert calls.named("count_documents") == [((_filter("a", "x"),), {})]
    assert calls.named("distinct") == [(("tags",), {})]
    assert calls.named("find_one") == [(({"_id": ID_A},), {})]


def test_iter_definitions_pages_with_skip_and_limit(
    mongo_repo: MongoGraphRepository, calls: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(5):
        mongo_repo.put(definition(f"{i:032x}", f"g{i}"))
    monkeypatch.setattr(mongo_store, "ITER_PAGE", 2)
    calls.calls.clear()
    assert [g.name for g in mongo_repo.iter_definitions()] == [f"g{i}" for i in range(5)]
    assert [args for args, _ in calls.named("find")] == [({},), ({},), ({},)]


class Pages(NamedTuple):
    graphs: int
    page: int
    queries: int


@pytest.mark.parametrize(
    "case",
    [
        Pages(0, 2, 1),
        Pages(1, 2, 1),
        Pages(2, 2, 2),  # a full page may be followed by more: ask once more
        Pages(3, 2, 2),
        Pages(4, 2, 3),
        Pages(5, 2, 3),
        Pages(5, 5, 2),
        Pages(5, 6, 1),
    ],
)
def test_page_boundaries(
    mongo_repo: MongoGraphRepository, monkeypatch: pytest.MonkeyPatch, case: Pages
) -> None:
    for i in range(case.graphs):
        mongo_repo.put(definition(f"{i:032x}", f"g{i}"))
    monkeypatch.setattr(mongo_store, "ITER_PAGE", case.page)
    queries: list[int] = []
    original: Any = mongomock.collection.Collection.find

    def counting(self: Any, *args: Any, **kwargs: Any) -> Any:
        queries.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(mongomock.collection.Collection, "find", counting)
    assert len(list(mongo_repo.iter_definitions())) == case.graphs
    assert len(queries) == case.queries


def test_the_default_page_size_is_one_hundred() -> None:
    assert mongo_store.ITER_PAGE == 100


# --------------------------------------------------------------------------- writes


def test_update_is_one_compare_and_set_on_id_and_revision(
    mongo_repo: MongoGraphRepository, calls: Recorder
) -> None:
    created = mongo_repo.create(create_data("old"))
    calls.calls.clear()
    mongo_repo.update(created.id, update_data(1, "new", Spec("d", ("t",), links=2)))
    [(args, kwargs)] = calls.named("find_one_and_update")
    assert args[0] == {"_id": created.id, "revision": 1}
    assert set(args[1]) == {"$set"}
    changes = args[1]["$set"]
    assert set(changes) == {
        "name",
        "description",
        "tags",
        "source",
        "transform",
        "style",
        "schema_version",
        "revision",
        "updated_at",
    }
    assert (changes["name"], changes["revision"], changes["updated_at"]) == (
        "new",
        2,
        NOW.replace(second=1),
    )
    assert kwargs == {"return_document": ReturnDocument.AFTER}
    projected = _projected_reads(calls)
    assert projected == []  # a successful update needs no second read of the revision


def test_a_lost_update_reads_the_current_revision_with_a_projection(
    mongo_repo: MongoGraphRepository, calls: Recorder
) -> None:
    created = mongo_repo.create(create_data("g"))
    calls.calls.clear()
    with pytest.raises(Exception, match="modified"):
        mongo_repo.update(created.id, update_data(5))
    [(flt, projection)] = _projected_reads(calls)
    assert flt == {"_id": created.id}
    assert {k: v for k, v in projection.items() if k != "_id"} == {"revision": 1, "updated_at": 1}


def test_create_inserts_once_without_replacing(
    mongo_repo: MongoGraphRepository, calls: Recorder
) -> None:
    graph = mongo_repo.create(create_data("g"))
    [(args, kwargs)] = calls.named("insert_one")
    assert args[0]["_id"] == graph.id
    assert kwargs == {}
    assert calls.named("replace_one") == []


def test_put_inserts_and_put_overwrite_replaces_with_upsert(
    mongo_repo: MongoGraphRepository, calls: Recorder
) -> None:
    mongo_repo.put(definition(ID_A, "a"))
    mongo_repo.put(definition(ID_B, "b"), overwrite=True)
    [(insert_args, _)] = calls.named("insert_one")
    assert insert_args[0]["_id"] == ID_A
    [(replace_args, replace_kwargs)] = calls.named("replace_one")
    assert replace_args[0] == {"_id": ID_B}
    assert replace_args[1]["_id"] == ID_B
    assert replace_kwargs == {"upsert": True}


def test_delete_filters_on_the_id(mongo_repo: MongoGraphRepository, calls: Recorder) -> None:
    mongo_repo.put(definition(ID_A, "a"))
    calls.calls.clear()
    mongo_repo.delete(ID_A)
    assert calls.named("delete_one") == [(({"_id": ID_A},), {})]


# --------------------------------------------------------------------------- indexes


def test_reads_create_no_index_and_the_first_write_creates_both_once(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any], calls: Recorder
) -> None:
    mongo_repo.list_graphs()
    mongo_repo.count()
    mongo_repo.all_tags()
    assert calls.named("create_index") == []
    created = mongo_repo.create(create_data("g"))
    assert [args for args, _ in calls.named("create_index")] == [("updated_at",), ("tags",)]
    mongo_repo.put(definition(ID_A, "a"))
    mongo_repo.update(created.id, update_data(1))
    mongo_repo.delete(ID_A)
    assert len(calls.named("create_index")) == 2  # not again
    assert set(mongo_collection.index_information()) == {"_id_", "updated_at_1", "tags_1"}


def test_updates_and_deletes_alone_create_no_index(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any], calls: Recorder
) -> None:
    mongo_collection.insert_one({"_id": ID_A, "revision": 1})
    with pytest.raises(Exception, match=r"modified|unreadable"):
        mongo_repo.update(ID_A, update_data(9))
    mongo_repo.delete(ID_A)
    assert calls.named("create_index") == []


def test_ping_always_ensures_the_indexes_and_marks_the_repository_ready(
    mongo_repo: MongoGraphRepository, calls: Recorder
) -> None:
    mongo_repo.ping()
    assert len(calls.named("create_index")) == 2
    mongo_repo.create(create_data("g"))  # already prepared by ping
    assert len(calls.named("create_index")) == 2
    mongo_repo.ping()
    assert len(calls.named("create_index")) == 4


def test_the_collection_is_the_graph_collection_of_the_storage_database(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    graph = mongo_repo.create(create_data("g"))
    assert mongo_collection.full_name == "sankey_studio.sankey_studio_graphs"
    assert mongo_collection.count_documents({"_id": graph.id}) == 1
    assert re.fullmatch(r"[0-9a-f]{32}", graph.id)
