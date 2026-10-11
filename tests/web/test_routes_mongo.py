"""``GET /mongo/{name}/databases | collections | sample`` against a recording fake driver."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from tests.sources.test_mongo_fakes import Call
from tests.web.test_routes_mongo_support import BASE, RigMongo, build_rig, error_of

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sankey_studio.models import AppSettings
    from tests.web.test_routes_mongo_support import Rig

TIMEOUT = {"maxTimeMS": 15_000}  # AppSettings.mongo_timeout_ms default
DOCS = [
    {"from": "Income", "to": "Rent", "amount": 1200, "type": "fixed"},
    {"from": "Income", "to": "Food", "amount": 400.5, "type": "variable"},
]


@pytest.fixture
def rig(tmp_path: Path, app_settings: AppSettings) -> Iterator[Rig]:
    yield from build_rig(tmp_path, RigMongo(), app_settings)


# --------------------------------------------------------------------------- databases


def test_databases_are_listed_sorted_without_the_system_ones(rig: Rig) -> None:
    rig.fake.names = ["zeta", "admin", "flows", "local", "config", "alpha"]
    response = rig.client.get(f"{BASE}/test/databases")
    assert response.status_code == 200
    assert response.json() == ["alpha", "flows", "zeta"]
    assert rig.fake.calls == [Call("list_databases", (), {"nameOnly": True, **TIMEOUT})]
    assert response.headers["Cache-Control"] == "no-store"


def test_no_databases_is_an_empty_list(rig: Rig) -> None:
    response = rig.client.get(f"{BASE}/test/databases")
    assert (response.status_code, response.json()) == (200, [])


# --------------------------------------------------------------------------- collections


def test_collections_are_listed_sorted_without_system_collections(rig: Rig) -> None:
    rig.fake.names = ["links", "system.profile", "events", "system.views"]
    response = rig.client.get(f"{BASE}/test/collections", params={"database": "flows"})
    assert response.status_code == 200
    assert response.json() == ["events", "links"]
    assert rig.fake.calls == [Call("list_collection_names", (), TIMEOUT)]
    assert rig.fake.path == ["flows"]


@pytest.mark.parametrize("database", ["admin", "local", "config", "ADMIN"])
def test_a_system_database_is_refused_before_the_driver_is_touched(rig: Rig, database: str) -> None:
    response = rig.client.get(f"{BASE}/test/collections", params={"database": database})
    assert response.status_code == 400
    assert error_of(response)["code"] == "unsafe_source"
    assert rig.fake.calls == []
    assert rig.fake.path == []


class Name(NamedTuple):
    value: str
    status: int
    code: str


BAD_NAMES = [
    Name("", 422, "validation_error"),
    Name("x" * 65, 422, "validation_error"),
    Name("a b", 400, "unsafe_source"),
    Name("a/b", 400, "unsafe_source"),
    Name("a.b", 400, "unsafe_source"),
    Name("$db", 400, "unsafe_source"),
]


@pytest.mark.parametrize(
    "case", BAD_NAMES, ids=[repr(c.value[:6]) + str(len(c.value)) for c in BAD_NAMES]
)
def test_a_malformed_database_name_never_reaches_the_driver(rig: Rig, case: Name) -> None:
    response = rig.client.get(f"{BASE}/test/collections", params={"database": case.value})
    assert response.status_code == case.status
    assert error_of(response)["code"] == case.code
    assert rig.fake.calls == []


def test_a_database_name_of_64_characters_is_accepted(rig: Rig) -> None:
    response = rig.client.get(f"{BASE}/test/collections", params={"database": "x" * 64})
    assert (response.status_code, response.json()) == (200, [])
    assert rig.fake.path == ["x" * 64]


def test_the_database_parameter_is_required_and_nothing_else_is_accepted(rig: Rig) -> None:
    missing = rig.client.get(f"{BASE}/test/collections")
    assert missing.status_code == 422
    assert error_of(missing)["details"] == ["query.database: Field required"]
    extra = rig.client.get(f"{BASE}/test/collections", params={"database": "flows", "x": "1"})
    assert extra.status_code == 422
    assert error_of(extra)["details"][0].startswith("query.x:")
    assert rig.fake.calls == []


# --------------------------------------------------------------------------- sample


def sample(rig: Rig, **params: str | int) -> tuple[int, Any]:
    query = {"database": "flows", "collection": "links", **params}
    response = rig.client.get(f"{BASE}/test/sample", params=query)
    return response.status_code, response.json()


def test_a_sample_returns_documents_and_the_suggested_mapping(rig: Rig) -> None:
    rig.fake.docs = DOCS
    status, body = sample(rig)
    assert status == 200
    assert body == {
        "documents": DOCS,
        "suggested": {"source": "from", "target": "to", "value": "amount", "category": "type"},
    }
    assert rig.fake.path == ["flows", "links"]
    [call] = rig.fake.calls
    assert (call.method, call.args) == ("find", ({},))
    assert call.kwargs == {"limit": 5, "max_time_ms": 15_000, "batch_size": 1}


def test_a_sample_of_unusual_documents_is_json_safe(rig: Rig) -> None:
    rig.fake.docs = [{"_id": b"\x00\x01", "when": float("nan"), "n": {"deep": [1, 2]}}]
    status, body = sample(rig)
    assert status == 200
    [document] = body["documents"]
    assert document["_id"] == "<bytes 2>"
    assert document["when"] == "nan"
    assert document["n"] == {"deep": [1, 2]}


def test_an_empty_collection_samples_to_nothing_and_a_fallback_mapping(rig: Rig) -> None:
    status, body = sample(rig)
    assert status == 200
    assert body["documents"] == []
    assert body["suggested"] == {
        "source": "source",
        "target": "target",
        "value": "value",
        "category": None,
    }


@pytest.mark.parametrize(
    ("n", "status", "limit"),
    [(0, 422, None), (1, 200, 1), (5, 200, 5), (20, 200, 20), (21, 422, None), (-1, 422, None)],
)
def test_the_sample_size_is_one_to_twenty(rig: Rig, n: int, status: int, limit: int | None) -> None:
    got, body = sample(rig, n=n)
    assert got == status
    if limit is None:
        assert body["error"]["code"] == "validation_error"
        assert rig.fake.calls == []
        return
    assert [call.kwargs["limit"] for call in rig.fake.calls] == [limit]


def test_the_sample_size_must_be_a_whole_number(rig: Rig) -> None:
    response = rig.client.get(
        f"{BASE}/test/sample", params={"database": "flows", "collection": "links", "n": "many"}
    )
    assert response.status_code == 422
    assert error_of(response)["details"][0].startswith("query.n:")


@pytest.mark.parametrize(
    ("database", "collection"),
    [
        ("admin", "users"),
        ("local", "oplog.rs"),
        ("config", "settings"),
        ("flows", "system.profile"),
        ("flows", "system.users"),
    ],
)
def test_system_namespaces_are_never_sampled(rig: Rig, database: str, collection: str) -> None:
    status, body = sample(rig, database=database, collection=collection)
    assert status == 400
    assert body["error"]["code"] == "unsafe_source"
    assert rig.fake.calls == []


@pytest.mark.parametrize(("length", "status"), [(120, 200), (121, 422)])
def test_a_collection_name_may_have_120_characters(rig: Rig, length: int, status: int) -> None:
    got, _body = sample(rig, collection="x" * length)
    assert got == status
    assert len(rig.fake.calls) == (1 if status == 200 else 0)


@pytest.mark.parametrize("collection", ["a$b", "$cmd", "a\x00b"])
def test_a_malformed_collection_name_never_reaches_the_driver(rig: Rig, collection: str) -> None:
    status, body = sample(rig, collection=collection)
    assert (status, body["error"]["code"]) == (400, "unsafe_source")
    assert rig.fake.calls == []


@pytest.mark.parametrize("missing", ["database", "collection"])
def test_database_and_collection_are_required(rig: Rig, missing: str) -> None:
    params = {"database": "flows", "collection": "links"}
    del params[missing]
    response = rig.client.get(f"{BASE}/test/sample", params=params)
    assert response.status_code == 422
    assert error_of(response)["details"] == [f"query.{missing}: Field required"]
    assert rig.fake.calls == []
