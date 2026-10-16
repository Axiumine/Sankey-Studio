# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests for ``storage.base``: ids, document upgrades and the Protocol surface."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from sankey_studio.errors import ConflictError, NotFoundError, StorageError
from sankey_studio.models import (
    SCHEMA_VERSION,
    GraphCreate,
    GraphDefinition,
    GraphSummary,
    ManualSource,
)
from sankey_studio.storage.base import (
    MONGO_GRAPHS_COLLECTION,
    GraphRepository,
    check_graph_id,
    decode_mongo_doc,
    encode_mongo_doc,
    find_unsafe_key,
    new_graph_id,
    upgrade_doc,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo import MongoClient

    from sankey_studio.models import GraphUpdate

NOW = datetime(2025, 5, 1, 12, 0, tzinfo=UTC)
BAD_IDS = [
    "../x",
    "..%2f",
    "a" * 31,
    "a" * 33,
    "A" * 32,
    "g" * 32,
    "a" * 32 + "\n",
    "\x00" + "a" * 31,
    "../" + "a" * 29,
    "",
    " " + "a" * 31,
]


def test_new_ids_are_valid() -> None:
    ids = {new_graph_id() for _ in range(50)}
    assert len(ids) == 50
    for graph_id in ids:
        assert check_graph_id(graph_id) == graph_id
    assert check_graph_id(uuid.uuid4().hex)


@pytest.mark.parametrize("bad", BAD_IDS)
def test_malformed_ids_are_not_found(bad: str) -> None:
    with pytest.raises(NotFoundError):
        check_graph_id(bad)


#: The models trim surrounding whitespace before the pattern check ("<id>\n" becomes a valid id);
#: path/query ids never go through a model, they go through ``check_graph_id`` above.
@pytest.mark.parametrize("bad", [b for b in BAD_IDS if b != "a" * 32 + "\n"])
def test_models_reject_malformed_ids(bad: str) -> None:
    with pytest.raises(ValidationError):
        GraphSummary(
            id=bad,
            name="n",
            description="",
            tags=[],
            source_type="manual",
            revision=1,
            updated_at=NOW,
        )
    with pytest.raises(ValidationError):
        GraphDefinition(id=bad, name="n", source=ManualSource(), created_at=NOW, updated_at=NOW)


def _doc(**extra: object) -> dict[str, object]:
    return {
        "id": "a" * 32,
        "name": "g",
        "source": {"type": "manual", "links": []},
        "created_at": NOW,
        "updated_at": NOW,
        **extra,
    }


def test_upgrade_doc_strips_mongo_id_and_defaults_schema_version() -> None:
    out = upgrade_doc({**_doc(), "_id": "a" * 32})
    assert "_id" not in out
    assert out["schema_version"] == 1
    graph = GraphDefinition.model_validate(out)
    assert graph.schema_version == SCHEMA_VERSION


def test_upgrade_doc_does_not_mutate_its_input() -> None:
    src = {**_doc(), "_id": "x"}
    upgrade_doc(src)
    assert "_id" in src
    assert "schema_version" not in src


@pytest.mark.parametrize("version", [SCHEMA_VERSION + 1, 99, 0, -1, "1"])
def test_upgrade_doc_refuses_unusable_schema_versions(version: object) -> None:
    with pytest.raises(StorageError):
        upgrade_doc(_doc(schema_version=version))


@pytest.mark.parametrize(
    ("version", "tail"),
    [(0, "has an invalid schema version"), (99, "was written by a newer version of sankey-studio")],
)
@pytest.mark.parametrize(("args", "noun"), [((), "graph"), (("folder",), "folder")])
def test_upgrade_doc_names_the_record_in_its_messages(
    version: int, tail: str, args: tuple[str, ...], noun: str
) -> None:
    with pytest.raises(StorageError) as info:
        upgrade_doc(_doc(schema_version=version), *args)
    assert info.value.message == f"Stored {noun} {tail}"


def test_persisted_shape_ignores_unknown_fields_but_requests_do_not() -> None:
    graph = GraphDefinition.model_validate(_doc(removed_in_later_version=1))
    assert graph.id == "a" * 32
    with pytest.raises(ValidationError):
        GraphCreate.model_validate({"name": "n", "source": {"type": "manual"}, "id": "a" * 32})


def test_persisted_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        GraphDefinition.model_validate(_doc(created_at=datetime(2025, 1, 1)))  # noqa: DTZ001 - a naive datetime is the input under test
    with pytest.raises(ValidationError):
        GraphSummary(
            id="a" * 32,
            name="n",
            description="",
            tags=[],
            source_type="manual",
            revision=1,
            updated_at=datetime(2025, 1, 1),  # noqa: DTZ001 - naive datetime under test
        )


def test_conflict_error_carries_the_current_revision() -> None:
    err = ConflictError("stale", current_revision=4, current_updated_at=NOW)
    assert err.current_revision == 4
    assert err.details == ["revision=4", f"updated_at={NOW.isoformat()}"]
    assert ConflictError("exists").details == []


def test_protocol_surface_is_frozen() -> None:
    names = {n for n in vars(GraphRepository) if not n.startswith("_")}
    assert names == {
        "list_graphs",
        "count",
        "all_tags",
        "get",
        "create",
        "update",
        "put",
        "iter_definitions",
        "unreadable_ids",
        "delete",
        "ping",
    }


class _Stub:
    """Compile-time proof (mypy) that the Protocol is implementable with these signatures."""

    def list_graphs(
        self, *, query: str | None = None, tag: str | None = None, limit: int = 200, offset: int = 0
    ) -> list[GraphSummary]:
        del query, tag, limit, offset  # the stub only has to match the Protocol signature
        return []

    def count(self, *, query: str | None = None, tag: str | None = None) -> int:
        del query, tag  # the stub only has to match the Protocol signature
        return 0

    def all_tags(self) -> list[str]:
        return []

    def get(self, graph_id: str) -> GraphDefinition:
        raise NotFoundError(graph_id)

    def create(self, data: GraphCreate, *, folder_id: str | None = None) -> GraphDefinition:
        del data, folder_id  # the stub only has to match the Protocol signature
        raise NotImplementedError

    def update(self, graph_id: str, data: GraphUpdate) -> GraphDefinition:
        raise NotImplementedError

    def put(self, graph: GraphDefinition, *, overwrite: bool = False) -> GraphDefinition:
        del overwrite  # the stub only has to match the Protocol signature
        return graph

    def iter_definitions(self) -> Iterator[GraphDefinition]:
        return iter(())

    def unreadable_ids(self) -> list[str]:
        return []

    def delete(self, graph_id: str) -> None:
        raise NotFoundError(graph_id)

    def ping(self) -> None:
        return None


def test_stub_satisfies_protocol() -> None:
    repo: GraphRepository = _Stub()
    assert repo.count() == 0
    assert list(repo.iter_definitions()) == []
    assert repo.unreadable_ids() == []


def test_mongo_store_collection_is_not_the_generic_name() -> None:
    assert MONGO_GRAPHS_COLLECTION == "sankey_studio_graphs"


# --------------------------------------------------------------------------- Mongo documents

#: Keys a user can type: dots and a leading "$" are rejected by MongoDB < 5.0 (mongomock accepts
#: them, so a store test that only round-trips through mongomock proves nothing).
NASTY_KEYS = ("a.b", "$x", "R&D.net", "$", "x.", ".y", "$where")


def _nasty_definition(source: dict[str, Any] | None = None) -> GraphDefinition:
    return GraphDefinition.model_validate(
        {
            "id": "b" * 32,
            "name": "nasty",
            "source": source or {"type": "manual", "links": []},
            "transform": {"merge_nodes": {key: f"{key}2" for key in NASTY_KEYS}},
            "style": {
                "node_colors": dict.fromkeys(NASTY_KEYS, "#112233"),
                "category_colors": dict.fromkeys(NASTY_KEYS, "#445566"),
            },
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


MONGO_SOURCE: dict[str, Any] = {
    "type": "mongo",
    "connection": "c",
    "collection": "flows",
    "filter": {"amount": {"$gt": 5}, "meta.flow": {"$in": ["a", "b"]}, "$or": [{"x.y": 1}]},
    "pipeline": [{"$match": {"meta.year": 2025}}, {"$group": {"_id": "$kind", "v": {"$sum": 1}}}],
}


def test_find_unsafe_key_reports_where_without_echoing_the_key() -> None:
    assert find_unsafe_key({"a": {"b": [1, {"c": 2}]}}) is None
    assert find_unsafe_key({"_id": "x", "n": [{"k": 1}]}) is None
    assert find_unsafe_key({"style": {"node_colors": {"a.b": "#112233"}}}) == "style.node_colors"
    assert find_unsafe_key({"a": [{"b": {"$x": 1}}]}) == "a.b"
    assert find_unsafe_key({"$set": 1}) == "<root>"
    assert find_unsafe_key({"a\0b": 1}) == "<root>"
    assert find_unsafe_key({1: "x"}) == "<root>"
    assert "a.b" not in (find_unsafe_key({"p": {"a.b": 1}}) or "")


def test_find_unsafe_key_survives_deep_documents() -> None:
    doc: dict[str, Any] = {}
    node = doc
    for _ in range(50_000):
        child: dict[str, Any] = {}
        node["k"] = child
        node = child
    node["$bad"] = 1
    assert find_unsafe_key(doc) is not None


def test_the_plain_dump_of_a_nasty_graph_is_not_storable() -> None:
    """The bug this codec exists for: the model dump keeps user text as dict keys."""
    graph = _nasty_definition(MONGO_SOURCE)
    dump = graph.model_dump(mode="json")
    assert find_unsafe_key(dump) is not None


@pytest.mark.parametrize("source", [None, MONGO_SOURCE], ids=["manual", "mongo"])
def test_encoded_documents_have_no_unsafe_field_names(source: dict[str, Any] | None) -> None:
    graph = _nasty_definition(source)
    stored = encode_mongo_doc(graph.model_dump(mode="json"))
    assert find_unsafe_key(stored) is None
    assert stored["transform"]["merge_nodes"] == [[key, f"{key}2"] for key in NASTY_KEYS]
    assert stored["style"]["node_colors"] == [[key, "#112233"] for key in NASTY_KEYS]
    assert stored["style"]["category_colors"] == [[key, "#445566"] for key in NASTY_KEYS]
    if source is not None:
        assert isinstance(stored["source"]["filter"], str)
        assert isinstance(stored["source"]["pipeline"], str)


@pytest.mark.parametrize("source", [None, MONGO_SOURCE], ids=["manual", "mongo"])
def test_mongo_document_codec_round_trips(source: dict[str, Any] | None) -> None:
    graph = _nasty_definition(source)
    stored = encode_mongo_doc(graph.model_dump(mode="json"))
    # what the driver hands back: arrays as lists, plus the _id the store adds
    back = GraphDefinition.model_validate(
        upgrade_doc(decode_mongo_doc({**copy.deepcopy(stored), "_id": graph.id}))
    )
    assert back == graph
    assert list(back.transform.merge_nodes) == list(NASTY_KEYS)  # order survives


def test_mongo_document_codec_does_not_mutate_its_input() -> None:
    graph = _nasty_definition(MONGO_SOURCE)
    dump = graph.model_dump(mode="json")
    before = copy.deepcopy(dump)
    stored = encode_mongo_doc(dump)
    assert dump == before
    stored_before = copy.deepcopy(stored)
    decode_mongo_doc(stored)
    assert stored == stored_before


def test_codec_leaves_other_sources_and_missing_sections_alone() -> None:
    assert encode_mongo_doc({"id": "x"}) == {"id": "x"}
    assert decode_mongo_doc({"id": "x"}) == {"id": "x"}
    text = {"type": "text", "content": "a,b,1"}
    assert encode_mongo_doc({"source": text})["source"] == text
    assert decode_mongo_doc({"source": text})["source"] == text


@pytest.mark.parametrize(
    "stored",
    [
        {"style": {"node_colors": [["only-a-key"]]}},
        {"style": {"node_colors": [["a", "b", "c"]]}},
        {"style": {"node_colors": [5]}},
        {"style": {"category_colors": [[["unhashable"], "#112233"]]}},
        {"transform": {"merge_nodes": [None]}},
        {"source": {"type": "mongo", "filter": "{not json"}},
        {"source": {"type": "mongo", "pipeline": "[" * 100_000}},
    ],
)
def test_malformed_encoded_fields_are_a_storage_error(stored: dict[str, Any]) -> None:
    with pytest.raises(StorageError, match="unreadable"):
        decode_mongo_doc(stored)


def test_codec_output_round_trips_through_the_driver_api(mongo_client: MongoClient[Any]) -> None:
    """mongomock would also accept the unsafe dump; the assertion on the stored document is what
    protects a real server, and decoding must work on what a cursor returns."""
    graph = _nasty_definition(MONGO_SOURCE)
    collection = mongo_client["flows"][MONGO_GRAPHS_COLLECTION]
    stored = {**encode_mongo_doc(graph.model_dump(mode="json")), "_id": graph.id}
    assert find_unsafe_key(stored) is None
    collection.insert_one(stored)
    raw = collection.find_one({"_id": graph.id})
    assert raw is not None
    assert find_unsafe_key(raw) is None
    assert GraphDefinition.model_validate(upgrade_doc(decode_mongo_doc(raw))) == graph
