"""Fixtures of the replica-set suite (``make e2e-mongo-rs``, docs/e2e.md section C).

The flows of ``tests/e2e/mongo`` again, against a REPLICA SET you run yourself. The URI comes from
``SANKEY_TEST_MONGO_RS_URI`` (environment, else the repo-root ``.env``; ``support.rs_env``). Without
it a test is skipped with the reason. The ``e2e-mongo-rs`` check of the release gate (pre-push
of ``main`` and tags) runs this directory: there a skip fails the check.

``real_rs_env`` is the same ``FlowEnv`` as ``real_env`` (``tests/e2e/mongo/conftest.py``): a live
server whose connections open through the production client factory, and a ``pymongo`` client used
ONLY inside the database named in the path of the URI (``support.rs_world``): it must be empty
when a test starts, its collections are dropped at teardown after the server stopped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import REAL_MONGO_RS_ENV
from tests.e2e.support.http_b_world import open_env
from tests.e2e.support.rs_env import rs_uri
from tests.e2e.support.rs_world import real_rs_world

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.e2e.support.http_b_world import FlowEnv, MongoWorld
    from tests.e2e.support.server import ServerFactory


@pytest.fixture
def real_rs_uri() -> str:
    uri = rs_uri()
    if not uri:
        pytest.skip(f"needs {REAL_MONGO_RS_ENV} (a MongoDB replica set: environment or .env)")
    return uri


@pytest.fixture
def rs_world(real_rs_uri: str) -> Iterator[MongoWorld]:
    world = real_rs_world(real_rs_uri)
    try:
        yield world
    finally:
        world.drop()


@pytest.fixture
def real_rs_env(make_server: ServerFactory, rs_world: MongoWorld) -> Iterator[FlowEnv]:
    with open_env(make_server, rs_world) as env:
        try:
            yield env
        finally:
            env.server.stop()  # no connection of the app is open when the database goes
