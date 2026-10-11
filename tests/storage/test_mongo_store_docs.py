"""What the Mongo store actually writes: key-safe documents, datetimes, damaged records."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

import mongomock
import pytest
from bson import ObjectId

from sankey_studio.errors import ConflictError, NotFoundError, StorageError
from sankey_studio.models import GraphDefinition
from sankey_studio.mongo import MongoClients
from sankey_studio.storage import MongoGraphRepository, mongo_store
from sankey_studio.storage.base import (
    MONGO_GRAPHS_COLLECTION,
    decode_mongo_doc,
    encode_mongo_doc,
    find_unsafe_key,
    upgrade_doc,
)
from tests.storage.conftest import STORE_DATABASE, STORE_TARGET
from tests.storage.support import (
    ID_A,
    ID_B,
    ID_C,
    NASTY_KEYS,
    NOW,
    Ticker,
    create_data,
    definition,
    nasty_create,
    update_data,
)

if TYPE_CHECKING:
    from pymongo import MongoClient
    from pymongo.collection import Collection

    from sankey_studio.models import AppSettings


def _raw(collection: Collection[Any], graph_id: str) -> dict[str, Any]:
    found: dict[str, Any] | None = collection.find_one({"_id": graph_id})
    assert found is not None
    return found


def _restored(raw: dict[str, Any]) -> GraphDefinition:
    doc = decode_mongo_doc(raw)
    doc["id"] = doc.pop("_id")
    return GraphDefinition.model_validate(upgrade_doc(doc))


# --------------------------------------------------------------------------- key safety


@pytest.mark.parametrize("mongo", [False, True], ids=["manual", "mongo-source"])
def test_create_stores_a_key_safe_document_that_decodes_back(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any], mongo: bool
) -> None:
    graph = mongo_repo.create(nasty_create(mongo=mongo))
    raw = _raw(mongo_collection, graph.id)
    assert find_unsafe_key(raw) is None
    assert _restored(raw) == graph
    assert mongo_repo.get(graph.id) == graph
    assert raw["transform"]["merge_nodes"] == [[key, f"{key}2"] for key in NASTY_KEYS]
    assert raw["style"]["node_colors"] == [[key, "#112233"] for key in NASTY_KEYS]
    assert raw["style"]["category_colors"] == [[key, "#445566"] for key in NASTY_KEYS]
    if mongo:
        assert isinstance(raw["source"]["filter"], str)
        assert json.loads(raw["source"]["filter"])["meta.flow"] == {"$in": ["a", "b"]}
        assert isinstance(raw["source"]["pipeline"], str)


@pytest.mark.parametrize("mongo", [False, True], ids=["manual", "mongo-source"])
def test_put_stores_a_key_safe_document(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any], mongo: bool
) -> None:
    source = nasty_create(mongo=mongo)
    graph = GraphDefinition(
        id=ID_B,
        name=source.name,
        source=source.source,
        transform=source.transform,
        style=source.style,
        created_at=NOW,
        updated_at=NOW,
    )
    mongo_repo.put(graph)
    assert find_unsafe_key(_raw(mongo_collection, ID_B)) is None
    mongo_repo.put(graph, overwrite=True)
    raw = _raw(mongo_collection, ID_B)
    assert find_unsafe_key(raw) is None
    assert _restored(raw) == graph
    assert mongo_repo.get(ID_B) == graph


@pytest.mark.parametrize("mongo", [False, True], ids=["manual", "mongo-source"])
def test_update_writes_key_safe_fields_only(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any], mongo: bool
) -> None:
    created = mongo_repo.create(create_data("plain"))
    source = nasty_create(mongo=mongo)
    updated = mongo_repo.update(
        created.id,
        update_data(1, "nasty").model_copy(
            update={"source": source.source, "transform": source.transform, "style": source.style}
        ),
    )
    raw = _raw(mongo_collection, created.id)
    assert find_unsafe_key(raw) is None
    assert _restored(raw) == updated
    assert mongo_repo.get(created.id) == updated
    assert [pair[0] for pair in raw["transform"]["merge_nodes"]] == list(NASTY_KEYS)


def test_the_document_is_keyed_by_underscore_id_with_real_datetimes(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    graph = mongo_repo.create(create_data("g"))
    raw = _raw(mongo_collection, graph.id)
    assert "id" not in raw
    assert raw["_id"] == graph.id
    assert raw["created_at"] == raw["updated_at"] == NOW
    assert isinstance(raw["created_at"], datetime)
    assert isinstance(raw["updated_at"], datetime)
    assert raw["revision"] == 1
    assert raw["schema_version"] == 1
    assert mongo_collection.count_documents({}) == 1


def test_an_update_leaves_id_and_creation_time_alone(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    graph = mongo_repo.create(create_data("g"))
    mongo_repo.update(graph.id, update_data(1, "renamed"))
    raw = _raw(mongo_collection, graph.id)
    assert raw["_id"] == graph.id
    assert raw["created_at"] == NOW
    assert raw["updated_at"] == NOW + timedelta(seconds=1)
    assert (raw["name"], raw["revision"], raw["schema_version"]) == ("renamed", 2, 1)
    assert mongo_collection.count_documents({}) == 1


def test_an_update_replaces_the_whole_source_document(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    graph = mongo_repo.create(
        create_data("g").model_copy(update={"source": nasty_create(mongo=True).source})
    )
    assert "filter" in _raw(mongo_collection, graph.id)["source"]
    mongo_repo.update(graph.id, update_data(1, "manual now"))
    assert _raw(mongo_collection, graph.id)["source"] == {
        "type": "manual",
        "links": [{"source": "s0", "target": "t0", "value": 1.0, "category": None}],
    }


def _unsafe_encoder(dump: Any) -> dict[str, Any]:
    return {**encode_mongo_doc(dump), "$set": {"a.b": 1}}


@pytest.mark.parametrize("operation", ["create", "put", "put-overwrite", "update"])
def test_a_document_with_an_unsafe_key_is_refused_before_it_reaches_the_driver(
    mongo_repo: MongoGraphRepository,
    mongo_collection: Collection[Any],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    created = mongo_repo.create(create_data("seed"))
    before = mongo_collection.count_documents({})
    monkeypatch.setattr(mongo_store, "encode_mongo_doc", _unsafe_encoder)
    calls = {
        "create": lambda: mongo_repo.create(create_data("x")),
        "put": lambda: mongo_repo.put(definition(ID_C, "x")),
        "put-overwrite": lambda: mongo_repo.put(definition(created.id, "x"), overwrite=True),
        "update": lambda: mongo_repo.update(created.id, update_data(1, "x")),
    }
    with pytest.raises(StorageError) as info:
        calls[operation]()
    assert info.value.message == "The graph holds a field name that MongoDB cannot store"
    assert "a.b" not in str(info.value)
    assert mongo_collection.count_documents({}) == before
    assert _raw(mongo_collection, created.id)["name"] == "seed"


# --------------------------------------------------------------------------- datetimes


@dataclass(slots=True)
class NaiveStore:
    """A store on a driver that hands back naive datetimes (not built ``tz_aware``)."""

    repo: MongoGraphRepository
    collection: Collection[Any]


@pytest.fixture
def naive_store(app_settings: AppSettings, clock: Ticker) -> NaiveStore:
    client: MongoClient[Any] = mongomock.MongoClient(tz_aware=False)
    clients = MongoClients(lambda: app_settings, factory=lambda _uri, _timeout: client)
    return NaiveStore(
        MongoGraphRepository(clients, STORE_TARGET, clock=clock),
        client[STORE_DATABASE][MONGO_GRAPHS_COLLECTION],
    )


def test_naive_datetimes_from_a_driver_without_tz_support_are_read_as_utc(
    naive_store: NaiveStore,
) -> None:
    created = naive_store.repo.create(create_data("g"))
    raw = _raw(naive_store.collection, created.id)
    assert raw["created_at"].tzinfo is None  # the premise: this driver is naive
    stored = naive_store.repo.get(created.id)
    assert stored.created_at == stored.updated_at == NOW
    assert stored.updated_at.utcoffset() == timedelta(0)
    [summary] = naive_store.repo.list_graphs()
    assert summary.updated_at == NOW
    assert [g.updated_at for g in naive_store.repo.iter_definitions()] == [NOW]


def test_the_clock_is_used_for_both_timestamps_and_stays_in_milliseconds(
    mongo_repo: MongoGraphRepository,
) -> None:
    created = mongo_repo.create(create_data("g"))
    assert created.created_at.microsecond % 1000 == 0
    assert created.created_at.tzinfo is not None
    assert created.created_at.astimezone(UTC) == NOW


# --------------------------------------------------------------------------- damaged records


def _valid_raw(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> dict[str, Any]:
    graph = mongo_repo.create(create_data("template"))
    raw = _raw(mongo_collection, graph.id)
    mongo_collection.delete_one({"_id": graph.id})
    return raw


class Broken(NamedTuple):
    label: str
    changes: dict[str, Any]
    message: str


UNREADABLE = "Stored graph is unreadable"
BROKEN = [
    Broken("no name", {"name": None}, UNREADABLE),
    Broken("empty name", {"name": ""}, UNREADABLE),
    Broken("source not a dict", {"source": "oops"}, UNREADABLE),
    Broken("no source type", {"source": {}}, UNREADABLE),
    Broken("bad tags", {"tags": "not-a-list"}, UNREADABLE),
    Broken("bad revision", {"revision": "x"}, UNREADABLE),
    Broken("zero revision", {"revision": 0}, UNREADABLE),
    Broken("text timestamp", {"updated_at": "yesterday"}, UNREADABLE),
    Broken("object id", {"_id": ObjectId()}, UNREADABLE),
    Broken(
        "unreadable pair list",
        {"style": {"node_colors": [["only-a-key"]]}},
        "Stored graph has an unreadable encoded field",
    ),
    Broken(
        "newer schema",
        {"schema_version": 99},
        "Stored graph was written by a newer version of sankey-studio",
    ),
    Broken("bad schema", {"schema_version": "1"}, "Stored graph has an invalid schema version"),
]


@pytest.mark.parametrize("case", BROKEN, ids=[b.label for b in BROKEN])
def test_a_damaged_record_is_skipped_in_streams_and_get_refuses_it(
    mongo_repo: MongoGraphRepository,
    mongo_collection: Collection[Any],
    caplog: pytest.LogCaptureFixture,
    case: Broken,
) -> None:
    template = _valid_raw(mongo_repo, mongo_collection)
    healthy = mongo_repo.put(definition(ID_C, "healthy"))
    bad_id = case.changes.get("_id", ID_A)
    mongo_collection.insert_one({**template, **case.changes, "_id": bad_id})
    with caplog.at_level(logging.WARNING):
        assert [g.id for g in mongo_repo.iter_definitions()] == [healthy.id]
    assert [r.getMessage() for r in caplog.records] == [
        f"Skipping unreadable stored graph {bad_id!r}"
    ]
    if isinstance(bad_id, str):  # an ObjectId key cannot even be asked for by id
        with pytest.raises(StorageError) as info:
            mongo_repo.get(bad_id)
        assert info.value.message == case.message


GONE = object()


class Summary(NamedTuple):
    field: str
    value: object
    listed: bool


@pytest.mark.parametrize(
    "case",
    [
        Summary("name", GONE, False),
        Summary("name", 5, False),
        Summary("tags", GONE, True),  # no tag list reads as no tags
        Summary("tags", "not-a-list", False),
        Summary("description", GONE, True),
        Summary("revision", GONE, False),
        Summary("revision", "x", False),
        Summary("updated_at", GONE, False),
        Summary("updated_at", "yesterday", False),
        Summary("source", GONE, False),
        Summary("source", "oops", False),
        Summary("source", {"type": "ftp"}, False),
    ],
    ids=lambda c: f"{c.field}={'gone' if c.value is GONE else c.value}",
)
def test_a_record_with_a_damaged_summary_is_skipped_in_listings(
    mongo_repo: MongoGraphRepository,
    mongo_collection: Collection[Any],
    caplog: pytest.LogCaptureFixture,
    case: Summary,
) -> None:
    template = _valid_raw(mongo_repo, mongo_collection)
    mongo_repo.put(definition(ID_C, "healthy"))
    broken = {**template, "_id": ID_A}
    if case.value is GONE:
        del broken[case.field]
    else:
        broken[case.field] = case.value
    mongo_collection.insert_one(broken)
    with caplog.at_level(logging.WARNING):
        listed = [s.id for s in mongo_repo.list_graphs()]
    if case.listed:
        assert listed == [ID_A, ID_C]
        assert caplog.records == []
        if case.field == "description":
            assert mongo_repo.list_graphs()[0].description == ""
    else:
        assert listed == [ID_C]
        assert [r.getMessage() for r in caplog.records] == [
            f"Skipping unreadable stored graph {ID_A!r}"
        ]


def test_get_of_a_missing_id_is_not_found_and_of_a_foreign_document_is_unreadable(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    with pytest.raises(NotFoundError, match="Graph not found"):
        mongo_repo.get(ID_A)
    mongo_collection.insert_one({"_id": ID_A, "something": "else"})
    with pytest.raises(StorageError, match=UNREADABLE):
        mongo_repo.get(ID_A)


class Stored(NamedTuple):
    label: str
    fields: dict[str, Any]
    revision: int | None
    updated: bool


@pytest.mark.parametrize(
    "case",
    [
        Stored("good", {"revision": 5, "updated_at": NOW}, 5, True),
        Stored("text revision", {"revision": "5", "updated_at": NOW}, None, True),
        Stored("text time", {"revision": 5, "updated_at": "now"}, 5, False),
        Stored("nothing", {}, None, False),
    ],
    ids=lambda c: c.label,
)
def test_a_stale_update_reads_what_it_can_of_a_damaged_current_record(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any], case: Stored
) -> None:
    mongo_collection.insert_one({"_id": ID_A, **case.fields})
    with pytest.raises(ConflictError) as info:
        mongo_repo.update(ID_A, update_data(1))
    assert info.value.current_revision == case.revision
    assert (info.value.current_updated_at == NOW) is case.updated
    if not case.updated:
        assert info.value.current_updated_at is None


def test_a_stale_update_on_a_naive_driver_still_reports_the_time(naive_store: NaiveStore) -> None:
    created = naive_store.repo.create(create_data("g"))
    with pytest.raises(ConflictError) as info:
        naive_store.repo.update(created.id, update_data(7))
    assert info.value.current_updated_at == NOW
    assert info.value.current_revision == 1


def test_a_duplicate_put_over_a_damaged_record_is_a_conflict_without_details(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    mongo_collection.insert_one({"_id": ID_A})
    with pytest.raises(ConflictError) as info:
        mongo_repo.put(definition(ID_A, "x"))
    assert info.value.details == []


def test_every_write_stamps_the_current_schema_version(
    mongo_repo: MongoGraphRepository,
    mongo_collection: Collection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = mongo_repo.create(create_data("g"))
    assert _raw(mongo_collection, created.id)["schema_version"] == 1
    monkeypatch.setattr(mongo_store, "SCHEMA_VERSION", 2)
    monkeypatch.setattr("sankey_studio.storage.base.SCHEMA_VERSION", 2)  # the next release
    mongo_repo.update(created.id, update_data(1, "again"))
    assert _raw(mongo_collection, created.id)["schema_version"] == 2
