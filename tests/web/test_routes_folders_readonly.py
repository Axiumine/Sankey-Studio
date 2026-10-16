# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Remote read-only mode: the folder reads work, every folder write is a 403 before the body."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

import pytest

from sankey_studio.models import FolderCreate
from sankey_studio.web.deps import MSG_READ_ONLY
from sankey_studio.web.routers import folders, graphs
from tests.web.test_routes_graphs_support import API, PLAIN, UNKNOWN_ID, save

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

FOLDERS: Final = f"{API}/folders"
JSON: Final = {"Content-Type": "application/json"}
REFUSED: Final = {"error": {"code": "read_only_mode", "message": MSG_READ_ONLY, "details": []}}
BODIES: Final = [b"{}", b"", b'{"name": "x"}', b"[1, 2]", b"null", b"{", b"not json", b"\xff\xfe"]


class Write(NamedTuple):
    method: str
    path: str


WRITES = [
    Write("POST", FOLDERS),
    Write("PUT", f"{FOLDERS}/{UNKNOWN_ID}"),
    Write("DELETE", f"{FOLDERS}/{UNKNOWN_ID}"),
    Write("POST", f"{API}/graphs/move"),
]


@pytest.fixture
def remote(make_app: AppFactory) -> WebApp:
    return make_app([folders.router, graphs.router], mode="remote_read_only")


@pytest.mark.parametrize("write", WRITES, ids=[f"{w.method} {w.path[8:]}" for w in WRITES])
@pytest.mark.parametrize("body", BODIES)
def test_a_folder_write_is_a_403_whatever_the_body(
    remote: WebApp, write: Write, body: bytes
) -> None:
    response = remote.client.request(write.method, write.path, content=body, headers=JSON)
    assert (response.status_code, response.json()) == (403, REFUSED)


def test_the_refused_writes_stored_nothing(remote: WebApp) -> None:
    graph = save(remote, "g", *PLAIN)
    good = {"name": "Finance", "parent_id": None}
    remote.client.post(FOLDERS, json=good)
    remote.client.post(f"{API}/graphs/move", json={"ids": [graph.id], "folder_id": None})
    assert remote.services.folders().list_folders() == []
    assert remote.services.graphs().get(graph.id).folder_id is None


def test_the_folder_reads_stay_available(remote: WebApp) -> None:
    folder = remote.services.folders().create_folder(FolderCreate(name="F"))
    assert remote.client.get(FOLDERS).json()["items"][0]["id"] == folder.id
    assert remote.client.get(f"{FOLDERS}/{folder.id}").status_code == 200
    scoped = remote.client.get(f"{API}/graphs", params={"folder": "root"})
    assert (scoped.status_code, scoped.json()["total"]) == (200, 0)


def test_with_remote_writes_the_folder_writes_are_open(make_app: AppFactory) -> None:
    web = make_app([folders.router, graphs.router], mode="remote_writes")
    created = web.client.post(FOLDERS, json={"name": "Open"})
    assert created.status_code == 201
    folder = created.json()
    body = {"name": "Renamed", "parent_id": None, "revision": 1}
    assert web.client.put(f"{FOLDERS}/{folder['id']}", json=body).status_code == 200
    moved = web.client.post(f"{API}/graphs/move", json={"ids": [UNKNOWN_ID], "folder_id": None})
    assert (moved.status_code, moved.json()) == (200, {"moved": 0, "missing": [UNKNOWN_ID]})
    assert web.client.delete(f"{FOLDERS}/{folder['id']}").status_code == 204
