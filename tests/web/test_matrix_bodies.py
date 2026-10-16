# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Body caps on every unsafe route of the FULL app: N bytes pass, N + 1 answer 413."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest

from sankey_studio.models import AppSettings
from sankey_studio.web.security import IMPORT_BODY_BYTES, JSON_BODY_BYTES, MIB
from tests.web.test_matrix_support import UNSAFE, UPLOAD, Endpoint, ids

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx2 import Response

    from tests.web.conftest import WebApp

IMPORT: Final = Endpoint("POST", "/api/v1/graphs/import", "/api/v1/graphs/import")
JSON_ROUTES: Final = [e for e in UNSAFE if e not in {UPLOAD, IMPORT}]
JSON: Final = {"Content-Type": "application/json"}
MULTIPART: Final = {"Content-Type": "multipart/form-data; boundary=x"}
CHUNK: Final = 64 * 1024


class Cap(NamedTuple):
    """A route class: its endpoint(s), headers and the cap in bytes."""

    label: str
    endpoint: Endpoint
    headers: dict[str, str]
    limit: int


def upload_limit() -> int:
    return AppSettings().max_upload_mb * MIB + MIB


CAPS = [
    Cap("json", Endpoint("POST", "/api/v1/preview", "/api/v1/preview"), JSON, 8 * MIB),
    Cap("import", IMPORT, JSON, 16 * MIB),
    Cap("upload", UPLOAD, MULTIPART, 26 * MIB),
]


def stream(size: int) -> Iterator[bytes]:
    """``size`` bytes in 64 KiB chunks: sent chunked, with no ``Content-Length``."""
    sent = 0
    while sent < size:
        chunk = min(CHUNK, size - sent)
        sent += chunk
        yield b" " * chunk


def refused(response: Response) -> tuple[int, Any]:
    return response.status_code, response.json()


def too_large(limit: int) -> tuple[int, dict[str, object]]:
    return 413, {
        "error": {
            "code": "payload_too_large",
            "message": "The request body is too large",
            "details": [f"limit_bytes={limit}"],
        }
    }


def test_the_caps_are_the_spec_numbers() -> None:
    assert JSON_BODY_BYTES == 8 * MIB
    assert IMPORT_BODY_BYTES == 16 * MIB
    assert upload_limit() == 26 * MIB
    assert [c.limit for c in CAPS] == [JSON_BODY_BYTES, IMPORT_BODY_BYTES, upload_limit()]


@pytest.mark.parametrize("endpoint", JSON_ROUTES, ids=ids(JSON_ROUTES))
def test_a_json_route_refuses_one_byte_over_8_mib(web: WebApp, endpoint: Endpoint) -> None:
    body = b" " * (JSON_BODY_BYTES + 1)
    response = web.client.request(endpoint.method, endpoint.path, content=body, headers=JSON)
    assert refused(response) == too_large(JSON_BODY_BYTES)


@pytest.mark.parametrize("cap", CAPS, ids=[c.label for c in CAPS])
def test_the_cap_applies_to_the_declared_length(web: WebApp, cap: Cap) -> None:
    body = b" " * (cap.limit + 1)
    response = web.client.post(cap.endpoint.path, content=body, headers=cap.headers)
    assert refused(response) == too_large(cap.limit)


@pytest.mark.parametrize("cap", CAPS, ids=[c.label for c in CAPS])
def test_the_cap_applies_to_a_chunked_body_with_no_content_length(web: WebApp, cap: Cap) -> None:
    response = web.client.post(
        cap.endpoint.path, content=stream(cap.limit + 1), headers=cap.headers
    )
    assert refused(response) == too_large(cap.limit)


@pytest.mark.parametrize("cap", CAPS, ids=[c.label for c in CAPS])
def test_a_body_of_exactly_the_cap_is_not_a_413(web: WebApp, cap: Cap) -> None:
    sent = web.client.post(cap.endpoint.path, content=b" " * cap.limit, headers=cap.headers)
    chunked = web.client.post(cap.endpoint.path, content=stream(cap.limit), headers=cap.headers)
    assert sent.status_code != 413
    assert chunked.status_code != 413


def test_the_import_route_takes_what_the_json_routes_refuse(web: WebApp) -> None:
    between = b" " * (JSON_BODY_BYTES + 1)
    response = web.client.post(IMPORT.path, content=between, headers=JSON)
    assert refused(response)[0] == 422  # not a JSON document, but past the size check
    assert response.json()["error"]["code"] == "validation_error"


def test_the_upload_cap_follows_the_live_setting(web: WebApp) -> None:
    saved = web.client.put("/api/v1/settings", json={"max_upload_mb": 1})
    assert saved.status_code == 200
    at_cap = web.client.post(UPLOAD.path, content=b" " * (2 * MIB), headers=MULTIPART)
    over = web.client.post(UPLOAD.path, content=b" " * (2 * MIB + 1), headers=MULTIPART)
    assert at_cap.status_code != 413
    assert refused(over) == too_large(2 * MIB)
