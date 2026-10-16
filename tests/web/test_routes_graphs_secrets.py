# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Secret hygiene of the draw routes: a Mongo failure never leaks the connection string.

Every route that reads a Mongo-backed graph (preview, entries, export, the saved render, the saved
export and the compare view) is driven with a driver that fails and echoes the URI, the password
and the host in its message. The answer is the standard envelope with the generic text of
``mongo_errors`` (connection NAME and exception class only), and neither the body nor any log
record, traceback included, holds a piece of the secret.
"""

from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest
from mongomock.collection import Collection
from pymongo.errors import (
    ExecutionTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from sankey_studio.models import AppSettings
from sankey_studio.web.routers import compare, exports, graphs, preview
from tests.web.test_routes_graphs_support import API, code, save_source

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.conftest import ConnectionFactory
    from tests.web.conftest import AppFactory, WebApp

PASSWORD: Final = "hunter2"
HOST: Final = "db.internal"
URI: Final = f"mongodb://admin:{PASSWORD}@{HOST}:27017/flows"
ECHO: Final = f"cannot use {URI} (password {PASSWORD}) on {HOST}"
SOURCE: Final = {"type": "mongo", "connection": "prod", "collection": "moves"}


class Failure(NamedTuple):
    make: Callable[[], BaseException]
    message: str  # what the client may be told


FAILURES: Final = {
    "driver": Failure(
        lambda: PyMongoError(ECHO), "MongoDB operation on 'prod' failed: PyMongoError"
    ),
    "unreachable": Failure(
        lambda: ServerSelectionTimeoutError(ECHO), "MongoDB connection 'prod' is unreachable"
    ),
    "timeout": Failure(
        lambda: ExecutionTimeout(ECHO), "MongoDB query on 'prod' exceeded the time limit"
    ),
    "unauthorised": Failure(
        lambda: OperationFailure(ECHO, code=13), "MongoDB connection 'prod' is not authorised"
    ),
    "refused": Failure(
        lambda: OperationFailure(ECHO, code=2), "MongoDB query on 'prod' failed: OperationFailure"
    ),
    "value": Failure(lambda: ValueError(ECHO), "MongoDB operation on 'prod' failed: ValueError"),
    "overflow": Failure(
        lambda: OverflowError(ECHO), "MongoDB operation on 'prod' failed: OverflowError"
    ),
}


class Request(NamedTuple):
    method: str
    path: str  # with {saved} standing for the id of the stored graph
    body: dict[str, Any] | None


REQUESTS: Final = {
    "preview": Request("POST", "/preview", {"source": SOURCE}),
    "entries": Request("POST", "/entries", {"source": SOURCE}),
    "draft export": Request("POST", "/export?format=csv", {"source": SOURCE}),
    "saved render": Request("GET", "/graphs/{saved}/render", None),
    "saved export": Request("GET", "/graphs/{saved}/export?format=csv", None),
    "compare": Request("GET", "/compare/render?ids={saved}", None),
}


class Case(NamedTuple):
    request: Request
    failure: Failure


CASES: Final = {
    f"{request_name}-{failure_name}": Case(request, failure)
    for (request_name, request), (failure_name, failure) in itertools.product(
        REQUESTS.items(), FAILURES.items()
    )
}


@pytest.fixture
def web(make_app: AppFactory, make_connection: ConnectionFactory) -> WebApp:
    settings = AppSettings(mongo_connections=[make_connection("prod", URI, "flows")])
    return make_app(
        [graphs.router, preview.router, compare.router, exports.router], settings=settings
    )


def fail_every_query(monkeypatch: pytest.MonkeyPatch, failure: Failure) -> list[BaseException]:
    """Make every ``find`` and ``aggregate`` of the (mongomock) driver raise ``failure``.

    The list collects what was raised, so a test can prove that the driver was reached.
    """
    raised: list[BaseException] = []

    def boom(*_args: object, **_kwargs: object) -> None:
        raised.append(failure.make())
        raise raised[-1]

    monkeypatch.setattr(Collection, "find", boom)
    monkeypatch.setattr(Collection, "aggregate", boom)
    return raised


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
def test_a_driver_failure_tells_the_client_nothing_about_the_connection(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, case: Case
) -> None:
    saved = save_source(web, "From Mongo", SOURCE).id
    raised = fail_every_query(monkeypatch, case.failure)
    caplog.set_level(logging.DEBUG)
    request = case.request
    response = web.client.request(
        request.method, API + request.path.format(saved=saved), json=request.body
    )
    assert len(raised) == 1  # the failing driver was reached: the checks below are not vacuous
    assert response.status_code == 422
    assert code(response) == "source_error"
    assert response.json()["error"] == {
        "code": "source_error",
        "message": case.failure.message,
        "details": [],
    }
    for secret in (PASSWORD, HOST, "mongodb://", "admin"):
        assert secret not in response.text
        assert secret not in caplog.text
