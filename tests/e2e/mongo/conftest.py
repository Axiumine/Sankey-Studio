# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Fixtures of the real-MongoDB suite (E2E.md section C).

Nothing here runs without ``SANKEY_TEST_MONGO_URI``: ``real_mongo_uri`` (``tests/e2e/conftest.py``)
skips the test with the reason, before any client exists. Use the project-local compose Mongo
(``make mongo-up``, ``mongodb://127.0.0.1:27117``) or a server you started yourself; never the
MongoDBs of other projects on 27017-27019.

``real_env`` is the same ``FlowEnv`` the mongomock suite uses (``tests/e2e/http``), built on a
``real_world``: a live Sankey Studio server whose connections open through the production client
factory, a recording HTTP client, and a ``pymongo`` client used ONLY inside one database named
``sankey_e2e_<8 hex>`` (documents are seeded there, the graph store lives there). The database is
dropped at teardown, after the server has stopped, even when the test failed; no other database
is read, written or dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_b_world import open_env, real_world

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.e2e.support.http_b_world import FlowEnv
    from tests.e2e.support.server import ServerFactory


@pytest.fixture
def real_env(make_server: ServerFactory, real_mongo_uri: str) -> Iterator[FlowEnv]:
    world = real_world(real_mongo_uri)
    try:
        with open_env(make_server, world) as env:
            try:
                yield env
            finally:
                env.server.stop()  # no connection of the app is open when the database goes
    finally:
        world.drop()
