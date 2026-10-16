# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""GET /graphs/export refuses what POST /graphs/import would refuse: one cap for both."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

import pytest

from sankey_studio.storage.bundle import export_bundle
from sankey_studio.web.routers import graphs
from sankey_studio.web.security import IMPORT_BODY_BYTES
from tests.web.test_routes_graphs_support import API, code, put_filler

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

EXPORT: Final = f"{API}/graphs/export"
IMPORT: Final = f"{API}/graphs/import"
JSON_HEADERS: Final = {"Content-Type": "application/json"}
#: Letters of eight of the nine graphs that make up an export of the size of the import cap.
BIG: Final = 1_900_000
GRAPHS: Final = 9


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


def export_size(web: WebApp, ids: list[str]) -> int:
    """The byte size the export route serves for ``ids`` (the same JSON, measured here)."""
    return len(json.dumps(export_bundle(web.services.graphs(), ids), indent=2).encode())


def fill_to(web: WebApp, size: int) -> str:
    """Nine stored graphs whose bundle is exactly ``size`` bytes; their ids, comma separated."""
    ids = [put_filler(web, number, BIG) for number in range(1, GRAPHS)]
    ids.append(put_filler(web, GRAPHS, 0))
    bare = export_size(web, ids)
    web.services.graphs().delete(ids[-1])
    ids[-1] = put_filler(web, GRAPHS, size - bare)
    assert export_size(web, ids) == size
    return ",".join(ids)


def test_an_export_of_exactly_the_import_cap_is_served_and_imports_again(web: WebApp) -> None:
    ids = fill_to(web, IMPORT_BODY_BYTES)
    response = web.client.get(f"{EXPORT}?ids={ids}")
    assert response.status_code == 200
    assert len(response.content) == IMPORT_BODY_BYTES == 16 * 1024 * 1024
    assert response.headers["content-type"] == "application/json"
    report = web.client.post(IMPORT, content=response.content, headers=JSON_HEADERS)
    assert report.status_code == 200
    assert report.json()["imported"] == GRAPHS
    assert report.json()["failed"] == 0


def test_an_export_one_byte_over_the_import_cap_is_refused(web: WebApp) -> None:
    ids = fill_to(web, IMPORT_BODY_BYTES + 1)
    response = web.client.get(f"{EXPORT}?ids={ids}")
    assert response.status_code == 422
    assert code(response) == "bundle_error"
    error = response.json()["error"]
    assert error["message"] == (
        "The export is larger than a bundle import accepts; export fewer graphs"
    )
    assert error["details"] == ["limit_bytes=16777216"]
    assert "content-disposition" not in response.headers
    assert response.headers["content-type"] == "application/json"
