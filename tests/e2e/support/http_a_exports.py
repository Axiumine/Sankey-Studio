# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Export helpers of the HTTP flows: read a ``Content-Disposition`` and call the export routes."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pytest

if TYPE_CHECKING:
    import httpx

NO_CHROME: Final = 501
DISPOSITION: Final = re.compile(r'^attachment; filename="([^"]*)"; filename\*=UTF-8\'\'(\S*)$')
MEDIA_TYPES: Final = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "html": "text/html; charset=utf-8",
    "json": "application/json",
    "csv": "text/csv; charset=utf-8",
}
#: Headers every download carries (docs/api.md section 5.4).
DOWNLOAD_HEADERS: Final = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "sandbox",
    "cache-control": "no-store",
}


@dataclass(frozen=True, slots=True)
class Disposition:
    """The two file names of a ``Content-Disposition``: the ASCII fallback and the UTF-8 one."""

    fallback: str
    utf8: str
    encoded: str


def parse_disposition(response: httpx.Response) -> Disposition:
    """Split ``attachment; filename="..."; filename*=UTF-8''...`` (asserts that shape)."""
    header = response.headers["content-disposition"]
    found = DISPOSITION.match(header)
    assert found, f"unexpected Content-Disposition: {header!r}"
    return Disposition(found[1], urllib.parse.unquote(found[2]), found[2])


def export(api: httpx.Client, graph_id: str, **params: Any) -> httpx.Response:
    """``GET /graphs/{id}/export`` with these query parameters."""
    return api.get(f"/api/v1/graphs/{graph_id}/export", params=params)


def export_draft(api: httpx.Client, draft: dict[str, Any], **params: Any) -> httpx.Response:
    """``POST /export`` of an unsaved draft with these query parameters."""
    return api.post("/api/v1/export", params=params, json=draft)


def assert_download(response: httpx.Response, fmt: str) -> None:
    """Status 200, the content type of ``fmt`` and the headers of a safe attachment."""
    assert response.status_code == 200, response.text[:300]
    assert response.headers["content-type"] == MEDIA_TYPES[fmt]
    for name, value in DOWNLOAD_HEADERS.items():
        assert response.headers[name] == value, name


def need_chrome(response: httpx.Response) -> httpx.Response:
    """Skip the test when the server has no Chrome to draw images (501 ``export_unavailable``)."""
    if response.status_code == NO_CHROME:
        pytest.skip("Chrome is not available: the server answers 501 export_unavailable")
    return response
