"""The upload route's body cap follows ``max_upload_mb``; read-only mode closes it unread."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings
from sankey_studio.web.deps import MSG_READ_ONLY, require_writes
from sankey_studio.web.middleware import BodySizeLimit
from sankey_studio.web.security import (
    IMPORT_PATH,
    MIB,
    UPLOAD_BODY_BYTES,
    UPLOAD_PATH,
    BodyLimits,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from starlette.types import Message, Receive, Scope, Send

    from tests.web.conftest import AppFactory, Mode

JSON_PATH = "/api/v1/probe"
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
MULTIPART = {"Content-Type": "multipart/form-data; boundary=x"}
READ_ONLY_ENVELOPE = {"error": {"code": "read_only_mode", "message": MSG_READ_ONLY, "details": []}}


class Cap(NamedTuple):
    mb: int
    cap: int


#: ``max_upload_mb`` and the cap it gives: the setting plus 1 MiB of multipart framing.
CAPS = [Cap(1, 2 * MIB), Cap(25, 26 * MIB), Cap(100, 101 * MIB)]


def _mb(value: int) -> Callable[[], int]:
    return lambda: value


async def _size(request: Request) -> JSONResponse:
    return JSONResponse({"size": len(await request.body())})


def _inner() -> Starlette:
    return Starlette(routes=[Route("/{path:path}", _size, methods=METHODS)])


def _limited(limits: BodyLimits) -> TestClient:
    return TestClient(BodySizeLimit(_inner(), limits))


def _chunks(count: int) -> Iterator[bytes]:
    for _ in range(count):
        yield b"a"


# --------------------------------------------------------------------------- BodyLimits


@pytest.mark.parametrize("case", CAPS, ids=lambda c: f"{c.mb}MB")
def test_the_upload_limit_is_the_setting_plus_one_mib(case: Cap) -> None:
    assert BodyLimits(upload_mb=_mb(case.mb)).upload_limit() == case.cap


def test_without_a_live_setting_the_static_ceiling_applies() -> None:
    assert BodyLimits().upload_limit() == UPLOAD_BODY_BYTES == 101 * MIB
    assert BodyLimits(upload_bytes=7).upload_limit() == 7


def test_the_setting_is_read_on_every_call() -> None:
    values = iter([1, 2])
    limits = BodyLimits(upload_mb=lambda: next(values))
    assert (limits.upload_limit(), limits.upload_limit()) == (2 * MIB, 3 * MIB)


# --------------------------------------------------------------------------- the middleware


@pytest.mark.parametrize("case", CAPS[:2], ids=lambda c: f"{c.mb}MB")
def test_a_declared_upload_at_the_cap_passes_and_one_byte_over_is_refused(case: Cap) -> None:
    client = _limited(BodyLimits(upload_mb=_mb(case.mb)))
    at_cap = client.post(UPLOAD_PATH, content=b"a" * case.cap)
    over = client.post(UPLOAD_PATH, content=b"a" * (case.cap + 1))
    assert (at_cap.status_code, at_cap.json()) == (200, {"size": case.cap})
    assert over.status_code == 413
    assert over.json()["error"]["code"] == "payload_too_large"
    assert over.json()["error"]["details"] == [f"limit_bytes={case.cap}"]


def test_a_chunked_upload_without_content_length_is_counted_against_the_setting() -> None:
    client = _limited(BodyLimits(upload_bytes=3, upload_mb=_mb(1)))
    cap = 2 * MIB
    at_cap = client.post(UPLOAD_PATH, content=iter([b"a" * cap]))
    over = client.post(UPLOAD_PATH, content=iter([b"a" * cap, b"a"]))
    assert "content-length" not in at_cap.request.headers
    assert (at_cap.status_code, at_cap.json()) == (200, {"size": cap})
    assert over.status_code == 413
    assert over.json()["error"]["details"] == [f"limit_bytes={cap}"]


def test_the_cap_is_read_per_request_so_a_changed_setting_applies_at_once() -> None:
    setting = [1]
    client = _limited(BodyLimits(upload_mb=lambda: setting[0]))
    body = b"a" * (2 * MIB + 1)
    assert client.post(UPLOAD_PATH, content=body).status_code == 413
    setting[0] = 2
    assert client.post(UPLOAD_PATH, content=body).status_code == 200


def test_other_routes_keep_their_own_caps_and_never_read_the_setting() -> None:
    calls: list[int] = []

    def reads() -> int:
        calls.append(1)
        return 1

    limits = BodyLimits(json_bytes=10, import_bytes=20, upload_mb=reads)
    client = _limited(limits)
    assert client.post(JSON_PATH, content=b"a" * 10).status_code == 200
    assert client.post(JSON_PATH, content=b"a" * 11).status_code == 413
    assert client.post(IMPORT_PATH, content=b"a" * 20).status_code == 200
    assert client.post(IMPORT_PATH, content=b"a" * 21).status_code == 413
    assert calls == []


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_a_safe_request_to_the_upload_route_never_reads_the_setting(method: str) -> None:
    def fails() -> int:
        raise AssertionError

    client = _limited(BodyLimits(upload_mb=fails, writes_allowed=False))
    assert client.request(method, UPLOAD_PATH).status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_read_only_mode_refuses_every_unsafe_request_to_the_upload_route(method: str) -> None:
    client = _limited(BodyLimits(upload_mb=_mb(25), writes_allowed=False))
    response = client.request(method, UPLOAD_PATH, content=b"a")
    assert response.status_code == 403
    assert response.json() == READ_ONLY_ENVELOPE
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", [JSON_PATH, IMPORT_PATH, UPLOAD_PATH + "/x", UPLOAD_PATH + "/"])
def test_read_only_mode_leaves_the_other_paths_to_their_own_routes(path: str) -> None:
    client = _limited(BodyLimits(writes_allowed=False))
    assert client.post(path, content=b"a").status_code == 200


def test_the_read_only_refusal_comes_before_any_byte_is_read() -> None:
    reads: list[str] = []
    started: list[str] = []

    async def receive() -> Message:
        reads.append("receive")
        return {"type": "http.request", "body": b"a" * 100, "more_body": True}

    async def send(message: Message) -> None:
        started.append(message["type"])

    async def inner(_scope: Scope, _receive: Receive, _send: Send) -> None:
        started.append("inner")

    scope: Scope = {"type": "http", "method": "POST", "path": UPLOAD_PATH, "headers": []}
    limits = BodyLimits(writes_allowed=False)
    asyncio.run(BodySizeLimit(inner, limits)(scope, receive, send))
    assert reads == []
    assert started == ["http.response.start", "http.response.body"]


def test_unreadable_settings_answer_in_the_envelope_and_the_route_is_not_run() -> None:
    def unreadable() -> int:
        raise SettingsError("Settings file is corrupt", details=["moved"])

    response = _limited(BodyLimits(upload_mb=unreadable)).post(UPLOAD_PATH, content=b"a")
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "settings_error",
            "message": "Settings file is corrupt",
            "details": ["moved"],
        }
    }


def test_an_unexpected_settings_failure_is_not_swallowed() -> None:
    def broken() -> int:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _limited(BodyLimits(upload_mb=broken)).post(UPLOAD_PATH, content=b"a")


# --------------------------------------------------------------------------- the whole app

probe = APIRouter()
consumed: list[int] = []


class _Size(BaseModel):
    size: int


@probe.post(UPLOAD_PATH, dependencies=[Depends(require_writes)])
async def _upload(file: UploadFile) -> _Size:
    return _Size(size=len(await file.read()))


@probe.get(UPLOAD_PATH)
async def _listing() -> _Size:
    return _Size(size=0)


raw = APIRouter()


@raw.post(UPLOAD_PATH)
async def _raw_size(request: Request) -> _Size:
    return _Size(size=len(await request.body()))


def _multipart(parts: int) -> Iterator[bytes]:
    """A valid multipart body of ``parts`` 64 KiB chunks; records how many were pulled."""
    yield b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\n'
    for index in range(parts):
        consumed.append(index)
        yield b"a" * 65536
    yield b"\r\n--x--\r\n"


@pytest.fixture(autouse=True)
def _reset_consumed() -> None:
    consumed.clear()


def test_the_app_cap_follows_the_stored_setting_and_a_later_edit(make_app: AppFactory) -> None:
    web = make_app([raw], settings=AppSettings(max_upload_mb=1))
    cap = 2 * MIB
    assert web.client.post(UPLOAD_PATH, content=b"a" * cap, headers=MULTIPART).status_code == 200
    over = web.client.post(UPLOAD_PATH, content=b"a" * (cap + 1), headers=MULTIPART)
    assert over.status_code == 413
    assert over.json()["error"]["details"] == [f"limit_bytes={cap}"]
    web.services.update_settings(AppSettings(max_upload_mb=2))
    larger = web.client.post(UPLOAD_PATH, content=b"a" * (cap + 1), headers=MULTIPART)
    assert (larger.status_code, larger.json()) == (200, {"size": cap + 1})
    still_over = web.client.post(UPLOAD_PATH, content=b"a" * (3 * MIB + 1), headers=MULTIPART)
    assert still_over.status_code == 413


def test_the_default_setting_caps_the_app_at_26_mib_not_at_the_ceiling(
    make_app: AppFactory,
) -> None:
    web = make_app([raw])
    cap = 26 * MIB
    fits = web.client.post(UPLOAD_PATH, content=b"a" * cap, headers=MULTIPART)
    over = web.client.post(UPLOAD_PATH, content=b"a" * (cap + 1), headers=MULTIPART)
    assert (fits.status_code, fits.json()) == (200, {"size": cap})
    assert over.status_code == 413
    assert over.json()["error"]["details"] == [f"limit_bytes={cap}"]


def test_a_read_only_app_refuses_an_upload_without_reading_or_spooling_it(
    make_app: AppFactory,
) -> None:
    web = make_app([probe], mode="remote_read_only")
    response = web.client.post(UPLOAD_PATH, content=_multipart(160), headers=MULTIPART)
    assert response.status_code == 403
    assert response.json() == READ_ONLY_ENVELOPE
    assert consumed == []  # nothing was pulled from the client, let alone parsed to disk


def test_a_read_only_app_still_lists_the_files(make_app: AppFactory) -> None:
    response = make_app([probe], mode="remote_read_only").client.get(UPLOAD_PATH)
    assert (response.status_code, response.json()) == (200, {"size": 0})


@pytest.mark.parametrize("mode", ["local", "remote_writes"])
def test_an_app_that_may_write_reads_the_whole_upload(make_app: AppFactory, mode: Mode) -> None:
    web = make_app([probe], mode=mode)
    response = web.client.post(UPLOAD_PATH, content=_multipart(160), headers=MULTIPART)
    assert (response.status_code, response.json()) == (200, {"size": 160 * 65536})
    assert len(consumed) == 160
