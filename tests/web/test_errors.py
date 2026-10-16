# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The error envelope: domain errors, validation 422, routing errors, unexpected 500."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, NamedTuple

import pytest
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from sankey_studio import errors as domain
from tests.web.conftest import SAME_ORIGIN, new_client

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

STAMP = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
JSON = {"Content-Type": "application/json"}


class Raised(NamedTuple):
    name: str
    error: domain.SankeyError
    status: int
    code: str
    details: list[str]


class Internal(domain.SankeyError):
    """A domain error that is a server fault, to sit exactly on the logging boundary."""

    status_code = 500
    code = "internal_domain_error"


RAISED = [
    Raised("source", domain.SourceError("bad row"), 422, "source_error", []),
    Raised("missing", domain.SourceNotFoundError("no file"), 404, "source_not_found", []),
    Raised("unsafe", domain.UnsafeSourceError("no"), 400, "unsafe_source", []),
    Raised("build", domain.GraphBuildError("cycle"), 422, "graph_build_error", []),
    Raised("nocat", domain.NoCategoriesError("none"), 422, "no_categories", []),
    Raised("large", domain.GraphTooLargeError("big"), 413, "graph_too_large", []),
    Raised("notfound", domain.NotFoundError("Graph not found"), 404, "not_found", []),
    Raised(
        "conflict",
        domain.ConflictError("stale", current_revision=3, current_updated_at=STAMP),
        409,
        "conflict",
        ["revision=3", "updated_at=2026-01-02T03:04:05+00:00"],
    ),
    Raised("storage", domain.StorageError("disk"), 503, "storage_error", []),
    Raised("settings", domain.SettingsError("bad"), 422, "settings_error", []),
    Raised(
        "bundle",
        domain.BundleError("bad", details=["graph 2: x"]),
        422,
        "bundle_error",
        ["graph 2: x"],
    ),
    Raised("busy", domain.BusyError("later"), 503, "busy", []),
    Raised(
        "unavailable", domain.ExportUnavailableError("no chrome"), 501, "export_unavailable", []
    ),
    Raised("exportbusy", domain.ExportBusyError("one at a time"), 503, "export_busy", []),
    Raised("toolarge", domain.ExportTooLargeError("pixels"), 422, "export_too_large", []),
    Raised("failed", domain.ExportFailedError("crash"), 502, "export_failed", []),
    Raised("timeout", domain.ExportTimeoutError("slow"), 504, "export_timeout", []),
    Raised("forbidden", domain.ForbiddenError("no"), 403, "forbidden", []),
    Raised("readonly", domain.ReadOnlyModeError("read only"), 403, "read_only_mode", []),
    Raised(
        "media", domain.UnsupportedMediaTypeError("json please"), 415, "unsupported_media_type", []
    ),
    Raised("payload", domain.PayloadTooLargeError("big"), 413, "payload_too_large", []),
    Raised("internal", Internal("broken"), 500, "internal_domain_error", []),
    Raised(
        "base", domain.SankeyError("plain", details=["a", "b"]), 400, "sankey_error", ["a", "b"]
    ),
]


class Body(BaseModel):
    name: str = Field(min_length=3)
    count: int = 0


class Many(BaseModel):
    rows: list[Body]


class Picky(BaseModel):
    note: str = ""

    @field_validator("note")
    @classmethod
    def _short(cls, value: str) -> str:
        if value:
            raise ValueError("y" * 500)
        return value


class Whole(BaseModel):
    a: int = 0

    @model_validator(mode="after")
    def _never(self) -> Whole:
        raise ValueError("the model as a whole is wrong")


router = APIRouter()
ERRORS = {r.name: r.error for r in RAISED}


@router.get("/api/v1/probe/raise/{name}")
def _raise(name: str) -> None:
    raise ERRORS[name]


@router.post("/api/v1/probe/body")
def _body(body: Body) -> dict[str, str]:
    return {"name": body.name}


@router.post("/api/v1/probe/many")
def _many(_rows: Many) -> None:
    return


@router.post("/api/v1/probe/picky")
def _picky(body: Picky) -> dict[str, str]:
    return {"note": body.note}


@router.get("/api/v1/probe/query")
def _query(limit: Annotated[int, Query(ge=1, le=200)] = 10) -> dict[str, int]:
    return {"limit": limit}


@router.get("/api/v1/probe/model")
def _model() -> None:
    Body.model_validate({"name": "ab", "count": "hunter2"})


@router.get("/api/v1/probe/whole")
def _whole() -> None:
    Whole.model_validate({"a": 1})


@router.get("/api/v1/probe/http/{status}")
def _http(status: int) -> None:
    raise HTTPException(
        status_code=status, detail="internal detail with /etc/secret", headers={"X-Extra": "1"}
    )


@router.get("/api/v1/probe/boom")
def _boom() -> None:
    message = "secret mongodb://u:hunter2@h/ in /srv/app/file.py"
    raise RuntimeError(message)


@router.put("/api/v1/probe/only-put")
def _only_put() -> None:
    return


@pytest.fixture
def probe(make_app: AppFactory) -> WebApp:
    return make_app([router])


@pytest.mark.parametrize("case", RAISED, ids=lambda c: c.name)
def test_every_domain_error_is_an_envelope(probe: WebApp, case: Raised) -> None:
    response = probe.client.get(f"/api/v1/probe/raise/{case.name}")
    assert response.status_code == case.status
    assert response.json() == {
        "error": {"code": case.code, "message": case.error.message, "details": case.details}
    }
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_a_server_side_domain_error_is_logged_without_a_traceback(
    probe: WebApp, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="sankey_studio.web.errors"):
        probe.client.get("/api/v1/probe/raise/storage")
        probe.client.get("/api/v1/probe/raise/notfound")
        probe.client.get("/api/v1/probe/raise/internal")
    assert [(r.levelname, r.getMessage(), r.exc_info) for r in caplog.records] == [
        ("WARNING", "StorageError on GET /api/v1/probe/raise/storage: disk", None),
        ("WARNING", "Internal on GET /api/v1/probe/raise/internal: broken", None),
    ]


def test_422_names_the_location_and_never_echoes_the_input(probe: WebApp) -> None:
    response = probe.client.post(
        "/api/v1/probe/body", json={"name": "ab", "count": "hunter2"}, headers=JSON
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "The request is not valid",
            "details": [
                "body.name: String should have at least 3 characters",
                "body.count: Input should be a valid integer, unable to parse string as an integer",
            ],
        }
    }
    assert "hunter2" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_a_query_error_is_located_in_the_query(probe: WebApp) -> None:
    low = probe.client.get("/api/v1/probe/query", params={"limit": 0})
    high = probe.client.get("/api/v1/probe/query", params={"limit": 201})
    top = probe.client.get("/api/v1/probe/query", params={"limit": 200})
    assert low.json()["error"]["details"] == [
        "query.limit: Input should be greater than or equal to 1"
    ]
    assert high.json()["error"]["details"] == [
        "query.limit: Input should be less than or equal to 200"
    ]
    assert (low.status_code, high.status_code, top.status_code) == (422, 422, 200)


def test_malformed_json_is_a_422_without_the_text(probe: WebApp) -> None:
    response = probe.client.post("/api/v1/probe/body", content=b'{"name": "hunter2', headers=JSON)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"] == ["body.9: JSON decode error"]
    assert "hunter2" not in response.text


def test_a_validator_message_is_cut_to_300_characters(probe: WebApp) -> None:
    response = probe.client.post("/api/v1/probe/picky", json={"note": "x"}, headers=JSON)
    (detail,) = response.json()["error"]["details"]
    assert detail == ("body.note: Value error, " + "y" * 500)[:300]
    assert len(detail) == 300


def test_at_most_50_details_are_listed(probe: WebApp) -> None:
    rows = {"rows": [{"name": "ab"}] * 60}
    response = probe.client.post("/api/v1/probe/many", json=rows, headers=JSON)
    details = response.json()["error"]["details"]
    assert response.status_code == 422
    assert len(details) == 50
    assert details[0] == "body.rows.0.name: String should have at least 3 characters"
    assert details[-1] == "body.rows.49.name: String should have at least 3 characters"


def test_a_pydantic_error_raised_inside_a_route_is_a_422_too(probe: WebApp) -> None:
    response = new_client(probe.app, SAME_ORIGIN).get("/api/v1/probe/model")
    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        "name: String should have at least 3 characters",
        "count: Input should be a valid integer, unable to parse string as an integer",
    ]
    assert "hunter2" not in response.text


def test_an_error_without_a_location_has_only_the_message(probe: WebApp) -> None:
    response = probe.client.get("/api/v1/probe/whole")
    assert response.status_code == 422
    assert response.json()["error"]["details"] == ["Value error, the model as a whole is wrong"]


class Status(NamedTuple):
    status: int
    code: str
    message: str


@pytest.mark.parametrize(
    "case",
    [
        Status(404, "not_found", "Not Found"),
        Status(405, "method_not_allowed", "Method Not Allowed"),
        Status(400, "http_error", "Bad Request"),
        Status(418, "http_error", "I'm a Teapot"),
        Status(299, "http_error", "HTTP error"),
    ],
)
def test_other_http_errors_keep_their_status_and_standard_text(probe: WebApp, case: Status) -> None:
    response = probe.client.get(f"/api/v1/probe/http/{case.status}")
    assert response.status_code == case.status
    assert response.json() == {"error": {"code": case.code, "message": case.message, "details": []}}
    assert response.headers["x-extra"] == "1"
    assert "secret" not in response.text


def test_an_unknown_path_is_a_404_envelope_with_headers(probe: WebApp) -> None:
    api = probe.client.get("/api/v1/nope")
    page = probe.client.get("/nope")
    assert api.status_code == page.status_code == 404
    assert (
        api.json()
        == page.json()
        == {"error": {"code": "not_found", "message": "Not Found", "details": []}}
    )
    assert api.headers["cache-control"] == "no-store"
    assert "cache-control" not in page.headers
    assert page.headers["x-content-type-options"] == "nosniff"


def test_a_wrong_method_is_a_405_that_keeps_the_allow_header(probe: WebApp) -> None:
    response = probe.client.post("/api/v1/probe/only-put", headers=JSON, content=b"{}")
    assert response.status_code == 405
    assert response.headers["allow"] == "PUT"
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_an_unexpected_error_is_a_generic_500(probe: WebApp) -> None:
    client = new_client(probe.app, SAME_ORIGIN, raise_exc=False)
    response = client.get("/api/v1/probe/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error", "details": []}
    }
    for leaked in ("hunter2", "mongodb", "/srv/app", "Traceback", "RuntimeError"):
        assert leaked not in response.text
    # produced outside the security-headers middleware, so it must carry them itself
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_an_unexpected_error_still_reaches_the_test_by_default(probe: WebApp) -> None:
    with pytest.raises(RuntimeError, match="secret"):
        probe.client.get("/api/v1/probe/boom")
