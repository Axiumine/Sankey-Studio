"""What only a cluster proves: the URI really reaches a replica set, through the production factory.

The flows in ``test_rs_flows.py`` pass on a standalone node too, so these tests pin the topology
itself: the driver discovered a replica set with a primary and at least two data-bearing members,
and the application's own ``MongoClients`` (the client cache, ``default_factory`` and ``ping``) work
on it with the URI exactly as the user saved it. Nothing is written to the server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.mongo import MongoClients, default_factory

if TYPE_CHECKING:
    from tests.e2e.support.http_b_world import MongoWorld

pytestmark = pytest.mark.mongo_rs

MIN_MEMBERS = 2


def test_the_uri_reaches_a_replica_set_with_a_primary(rs_world: MongoWorld) -> None:
    client = rs_world.client
    client.admin.command("ping")  # server selection ran: the topology is known
    assert client.topology_description.topology_type_name == "ReplicaSetWithPrimary"


def test_the_replica_set_has_several_members(rs_world: MongoWorld) -> None:
    hello = rs_world.client.admin.command("hello")
    assert hello.get("setName"), "the server is not a replica set member"
    assert len(hello["hosts"]) >= MIN_MEMBERS


def test_the_application_client_cache_works_on_the_cluster(rs_world: MongoWorld) -> None:
    connection = MongoConnection(
        name="rs", uri=SecretStr(rs_world.uri), default_database=rs_world.database
    )
    clients = MongoClients(lambda: AppSettings(mongo_connections=[connection]), default_factory)
    try:
        assert clients.ping("rs") >= 0
        assert clients.get("rs") is clients.get("rs")
        assert clients.default_database("rs") == rs_world.database
    finally:
        clients.close()
