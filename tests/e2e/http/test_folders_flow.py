"""E2E: library folders ("collections") over the live API, on the file store and on Mongo.

The scenarios live in ``tests.e2e.support.http_b_folder_flows`` and are shared with the real-Mongo
suite (``tests/e2e/mongo/test_real_folders_flow.py``): nested folders and their rules, graphs saved
in a folder and moved, a duplicate that stays next to its original, delete that moves everything
up, the boot data of the library page, bundles that carry the tree, the storage switch that copies
it, and (on the in-memory server) the unique sibling index. The tests below add the remote
read-only server, which refuses every folder write and keeps the reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.models import FolderCreate
from tests.e2e.support.builders import graph_create
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.http_b_folder_flows import (
    FOLDER_FLOWS,
    FOLDERS,
    GRAPHS,
    UNKNOWN,
)
from tests.e2e.support.http_b_security import snapshot
from tests.e2e.support.http_b_world import mongomock_world, open_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv
    from tests.e2e.support.server import ServerFactory

WRITES = [
    ("POST", FOLDERS, {"name": "attack"}),
    ("PUT", f"{FOLDERS}/{UNKNOWN}", {"name": "attack", "parent_id": None, "revision": 1}),
    ("DELETE", f"{FOLDERS}/{UNKNOWN}", None),
    ("POST", f"{GRAPHS}/move", {"ids": [UNKNOWN], "folder_id": None}),
]


@pytest.fixture
def env(make_server: ServerFactory) -> Iterator[FlowEnv]:
    with open_env(make_server, mongomock_world()) as flow_env:
        yield flow_env


@pytest.mark.parametrize("scenario", FOLDER_FLOWS)
def test_folder_flow(env: FlowEnv, scenario: Scenario) -> None:
    scenario(env)


@pytest.mark.parametrize(("method", "path", "body"), WRITES, ids=lambda value: str(value)[:24])
def test_a_read_only_remote_server_refuses_every_folder_write(
    make_server: ServerFactory, method: str, path: str, body: object
) -> None:
    server = make_server(remote_mode=True)
    server.services.folders().create_folder(FolderCreate(name="Kept"))
    with make_client(server) as api:
        before = snapshot(api, server)
        answer = api.request(method, path, json=body)
        assert (answer.status_code, answer.json()["error"]["code"]) == (403, "read_only_mode")
        assert snapshot(api, server) == before
        assert [i["name"] for i in json_of(api.get(FOLDERS))["items"]] == ["Kept"]
        assert api.get(GRAPHS, params={"folder": "root"}).status_code == 200


def test_remote_writes_open_the_folder_writes_again(make_server: ServerFactory) -> None:
    server = make_server(remote_mode=True, allow_remote_writes=True)
    with make_client(server) as api:
        folder = json_of(api.post(FOLDERS, json={"name": "Open"}), 201)
        graph = json_of(
            api.post(GRAPHS, params={"folder": folder["id"]}, json=graph_create("g")), 201
        )
        assert graph["folder_id"] == folder["id"]
        moved = api.post(f"{GRAPHS}/move", json={"ids": [graph["id"]], "folder_id": None})
        assert json_of(moved) == {"moved": 1, "missing": []}
        assert api.delete(f"{FOLDERS}/{folder['id']}").status_code == 204


def test_a_hostile_folder_name_comes_back_as_text_and_is_inert_on_the_page(
    make_server: ServerFactory,
) -> None:
    name = "<img src=x onerror=alert(1)>"
    with make_client(make_server()) as api:
        folder = json_of(api.post(FOLDERS, json={"name": name}), 201)
        assert json_of(api.get(f"{FOLDERS}/{folder['id']}"))["name"] == name
        page = api.get("/", headers={"Accept": "text/html"}).text
        assert name not in page
        assert "<img" not in page
