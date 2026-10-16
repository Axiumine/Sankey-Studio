# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The Mongo routes under failure and policy: unknown connections, slots, driver errors, modes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from pymongo.errors import ExecutionTimeout, PyMongoError, ServerSelectionTimeoutError

from sankey_studio.errors import BusyError
from sankey_studio.web.routers.mongo import router
from tests.web.test_routes_mongo_support import (
    BASE,
    PASSWORD,
    REMOTE_READ_ONLY,
    RigMongo,
    build_rig,
    error_of,
    record_slots,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import NoReturn

    from sankey_studio.models import AppSettings
    from tests.web.conftest import AppFactory
    from tests.web.test_routes_mongo_support import Rig

SAMPLE = {"database": "flows", "collection": "links"}


class Endpoint(NamedTuple):
    """A route of the router, with the query string it needs."""

    path: str
    params: dict[str, str]


ENDPOINTS = [
    Endpoint("databases", {}),
    Endpoint("collections", {"database": "flows"}),
    Endpoint("sample", SAMPLE),
]
IDS = [e.path for e in ENDPOINTS]


@pytest.fixture
def rig(tmp_path: Path, app_settings: AppSettings) -> Iterator[Rig]:
    yield from build_rig(tmp_path, RigMongo(), app_settings)


@pytest.fixture
def read_only(tmp_path: Path, app_settings: AppSettings) -> Iterator[Rig]:
    yield from build_rig(tmp_path, RigMongo(), app_settings, REMOTE_READ_ONLY)


def get(rig: Rig, name: str, endpoint: Endpoint) -> tuple[int, Any]:
    response = rig.client.get(f"{BASE}/{name}/{endpoint.path}", params=endpoint.params)
    return response.status_code, response.json()


# --------------------------------------------------------------------------- connections


class Unknown(NamedTuple):
    """A connection name as it appears in the URL and as the error message shows it."""

    url: str
    shown: str


UNKNOWN = [Unknown("nope", "nope"), Unknown("a%20b", "?")]


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=IDS)
@pytest.mark.parametrize("unknown", UNKNOWN, ids=[u.url for u in UNKNOWN])
def test_an_unknown_connection_is_a_404_before_any_client_or_slot_exists(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, endpoint: Endpoint, unknown: Unknown
) -> None:
    slots = record_slots(rig, monkeypatch)
    response = rig.client.get(f"{BASE}/{unknown.url}/{endpoint.path}", params=endpoint.params)
    assert response.status_code == 404
    assert error_of(response) == {
        "code": "source_not_found",
        "message": f"Unknown MongoDB connection '{unknown.shown}'",
        "details": [],
    }
    assert (slots, rig.fake.calls) == ([], [])


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=IDS)
def test_every_request_runs_inside_the_connection_slot(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, endpoint: Endpoint
) -> None:
    slots = record_slots(rig, monkeypatch)
    status, _body = get(rig, "test", endpoint)
    assert status == 200
    assert slots == ["test"]


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=IDS)
def test_a_busy_connection_is_a_503_busy(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, endpoint: Endpoint
) -> None:
    def busy(connection: str) -> NoReturn:
        raise BusyError(f"MongoDB connection '{connection}' is busy; try again shortly")

    monkeypatch.setattr(rig.services.mongo, "slot", busy)
    status, body = get(rig, "test", endpoint)
    assert status == 503
    assert body["error"]["code"] == "busy"
    assert rig.fake.calls == []


# --------------------------------------------------------------------------- driver failures


class Failure(NamedTuple):
    error: Exception
    status: int
    code: str
    message: str


SECRET_TEXT = f"mongodb://tester:{PASSWORD}@mongo.invalid:27017 failed"
FAILURES = [
    Failure(
        PyMongoError(SECRET_TEXT),
        422,
        "source_error",
        "MongoDB operation on 'test' failed: PyMongoError",
    ),
    Failure(
        ServerSelectionTimeoutError(SECRET_TEXT),
        422,
        "source_error",
        "MongoDB connection 'test' is unreachable",
    ),
    Failure(
        ExecutionTimeout(SECRET_TEXT),
        422,
        "source_error",
        "MongoDB query on 'test' exceeded the time limit",
    ),
]


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=IDS)
@pytest.mark.parametrize("failure", FAILURES, ids=[type(f.error).__name__ for f in FAILURES])
def test_a_driver_failure_names_the_connection_and_never_the_driver_text(
    rig: Rig, caplog: pytest.LogCaptureFixture, endpoint: Endpoint, failure: Failure
) -> None:
    rig.fake.call_error = failure.error
    with caplog.at_level(logging.DEBUG):
        response = rig.client.get(f"{BASE}/test/{endpoint.path}", params=endpoint.params)
    assert response.status_code == failure.status
    assert error_of(response) == {"code": failure.code, "message": failure.message, "details": []}
    assert PASSWORD not in response.text
    assert PASSWORD not in caplog.text
    assert "mongo.invalid" not in response.text


def test_a_failure_in_the_middle_of_a_sample_is_the_same_kind_of_error(rig: Rig) -> None:
    rig.fake.docs = [{"a": 1}]
    rig.fake.iter_error = PyMongoError(SECRET_TEXT)
    status, body = get(rig, "test", ENDPOINTS[2])
    assert status == 422
    assert body["error"]["message"] == "MongoDB operation on 'test' failed: PyMongoError"
    assert all(cursor.closed for cursor in rig.fake.cursors)


# --------------------------------------------------------------------------- policy


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=IDS)
def test_inspection_stays_available_in_remote_read_only_mode(
    read_only: Rig, endpoint: Endpoint
) -> None:
    read_only.fake.names = ["flows"]
    status, _body = get(read_only, "test", endpoint)
    assert status == 200


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=IDS)
def test_a_cross_site_get_is_refused_before_a_connection_opens(
    rig: Rig, endpoint: Endpoint
) -> None:
    response = rig.client.get(
        f"{BASE}/test/{endpoint.path}",
        params=endpoint.params,
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403
    assert error_of(response)["code"] == "forbidden"
    assert rig.fake.calls == []


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=IDS)
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_the_routes_only_read(rig: Rig, endpoint: Endpoint, method: str) -> None:
    response = rig.client.request(
        method, f"{BASE}/test/{endpoint.path}", params=endpoint.params, json={}
    )
    assert response.status_code == 405
    assert rig.fake.calls == []


def test_the_services_close_the_clients_they_opened(rig: Rig) -> None:
    assert get(rig, "test", ENDPOINTS[0])[0] == 200
    rig.services.close()
    assert rig.fake.closed == 1


# --------------------------------------------------------------------------- real driver fake


def test_a_sample_runs_against_the_in_memory_server_too(
    make_app: AppFactory, app_settings: AppSettings
) -> None:
    web = make_app([router], settings=app_settings)
    web.mongo["flows"]["links"].insert_many(
        [{"from": "A", "to": "B", "amount": 3}, {"from": "A", "to": "C", "amount": 4}]
    )
    response = web.client.get(f"{BASE}/test/sample", params={**SAMPLE, "n": 1})
    assert response.status_code == 200
    body = response.json()
    [document] = body["documents"]
    assert {k: v for k, v in document.items() if k != "_id"} == {
        "from": "A",
        "to": "B",
        "amount": 3,
    }
    assert isinstance(document["_id"], str)
    assert body["suggested"]["source"] == "from"
    assert body["suggested"]["target"] == "to"
    assert body["suggested"]["value"] == "amount"
