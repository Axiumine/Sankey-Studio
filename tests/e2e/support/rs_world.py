# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``real_rs_world``: a ``MongoWorld`` on a replica set whose database is named by the URI.

The standalone suite makes a database of its own (``sankey_e2e_<8 hex>``) and drops it. A shared
replica set usually gives the test user rights on ONE database only (``readWrite``: no
``dropDatabase``, no rights on a name it has never seen), so here the database is the one in the
path of ``SANKEY_TEST_MONGO_RS_URI`` (``mongodb://user:pw@h1,h2,h3/<database>?replicaSet=rs0``) and:

* it must be EMPTY when a test starts, otherwise the test fails and nothing is touched: a database
  that holds someone's data is not a throwaway one;
* at teardown its collections are dropped (``MongoWorld.drop`` with ``keep_database``), the
  database itself stays;
* ``admin``, ``local`` and ``config`` are refused.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from pymongo.errors import ConfigurationError, PyMongoError

from tests.conftest import REAL_MONGO_RS_ENV
from tests.e2e.support.http_b_world import SYSTEM_DATABASES, real_world

if TYPE_CHECKING:
    from pymongo import MongoClient

    from tests.e2e.support.http_b_world import MongoWorld


SECONDARY_READS = "readPreference=secondaryPreferred"


def member_count(client: MongoClient[Any]) -> int:
    """The data-bearing members the driver knows: the primary and its secondaries."""
    return 1 + len(client.secondaries)


def secondary_reads_uri(uri: str, *, acknowledged_by: int = 0) -> str:
    """``uri`` with ``readPreference=secondaryPreferred`` as the only read preference of its
    query (one that was there is replaced: the driver warns about a duplicate option).

    With ``acknowledged_by`` (the member count) a write of the application also returns only
    once that many members have it (``w=<n>``, in place of any ``w`` of the URI), so that a read
    from a secondary that follows a write cannot be answered before the replica has it."""
    base, _, query = uri.partition("?")
    replaced = ("readpreference=", "w=") if acknowledged_by else ("readpreference=",)
    options = [o for o in query.split("&") if o and not o.lower().startswith(replaced)]
    added = [SECONDARY_READS, *([f"w={acknowledged_by}"] if acknowledged_by else [])]
    return f"{base}?{'&'.join([*options, *added])}"


def real_rs_world(uri: str) -> MongoWorld:
    """A world on the replica set at ``uri``, in the database of its path; fails when that
    database is missing, a system database, unreadable or not empty. The caller owns
    ``world.drop()``."""
    world = real_world(uri, env=REAL_MONGO_RS_ENV)
    try:
        database = _database_of(world)
    except pytest.fail.Exception:
        world.client.close()
        raise
    members = member_count(world.client)
    return replace(world, database=database, keep_database=True, members=members)


def _database_of(world: MongoWorld) -> str:
    try:
        name = world.client.get_default_database().name
    except ConfigurationError:
        pytest.fail(f"{REAL_MONGO_RS_ENV} needs a throwaway database in its path (/name)")
    if name in SYSTEM_DATABASES:
        pytest.fail(f"{REAL_MONGO_RS_ENV} names the system database {name!r}")
    try:
        leftovers = world.client[name].list_collection_names()
    except PyMongoError as exc:
        pytest.fail(f"{REAL_MONGO_RS_ENV}: cannot list the collections: {type(exc).__name__}")
    if leftovers:
        pytest.fail(
            f"{REAL_MONGO_RS_ENV}: database {name!r} holds {len(leftovers)} collection(s); "
            "use an empty throwaway database"
        )
    return name
