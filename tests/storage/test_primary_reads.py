"""The library stores read from the primary, whatever ``readPreference`` the saved URI carries.

A save then a load, a delete then an import: on a replica set a secondary may not have replicated
the write yet, so the graph and folder collections are opened through ``primary_database``.
Source collections (the data a person reads) are not: they keep the URI's preference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pymongo import ReadPreference

from sankey_studio.models import AppSettings
from sankey_studio.mongo import MongoClients, primary_database
from sankey_studio.storage import MongoFolderRepository, MongoGraphRepository, MongoStoreTarget
from tests.conftest import build_connection
from tests.storage.mongo_fakes import Hub

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo import MongoClient

DATABASE = "sankey_studio"
TARGET = MongoStoreTarget("test", DATABASE)
SECONDARY_URI = "mongodb://h1,h2/?replicaSet=rs0&readPreference=secondary"


def test_primary_database_is_the_named_database_on_the_primary(
    mongo_client: MongoClient[Any],
) -> None:
    database = primary_database(mongo_client, "lab")
    assert database.name == "lab"
    assert database["things"].read_preference == ReadPreference.PRIMARY
    assert database["things"].read_preference != ReadPreference.SECONDARY_PREFERRED


def hub_clients(hub: Hub) -> MongoClients:
    settings = AppSettings(mongo_connections=[build_connection("test", SECONDARY_URI)])
    return MongoClients(lambda: settings, factory=hub)


READS: list[tuple[str, Callable[[MongoClients], Any]]] = [
    ("graphs", lambda clients: MongoGraphRepository(clients, TARGET).list_graphs()),
    ("graphs count", lambda clients: MongoGraphRepository(clients, TARGET).count()),
    ("graphs ping", lambda clients: MongoGraphRepository(clients, TARGET).ping()),
    ("folders", lambda clients: MongoFolderRepository(clients, TARGET).list_folders()),
    ("folders ping", lambda clients: MongoFolderRepository(clients, TARGET).ping()),
]


@pytest.mark.parametrize(("name", "read"), READS, ids=[name for name, _ in READS])
def test_a_store_opens_its_database_on_the_primary(
    name: str, read: Callable[[MongoClients], Any]
) -> None:
    hub = Hub()
    read(hub_clients(hub))
    (client,) = hub.clients
    assert client.uri == SECONDARY_URI  # the URI is saved as typed...
    assert client.opened == [(DATABASE, {"read_preference": ReadPreference.PRIMARY})], name


def test_the_collection_handles_of_both_stores_read_the_primary() -> None:
    clients = hub_clients(Hub())
    with MongoGraphRepository(clients, TARGET)._session() as graphs:
        assert graphs.read_preference == ReadPreference.PRIMARY
    with MongoFolderRepository(clients, TARGET)._session() as handles:
        assert handles.graphs.read_preference == ReadPreference.PRIMARY
        assert handles.folders.read_preference == ReadPreference.PRIMARY
