"""Saved-graph storage: the repositories, the settings file and migration helpers.

``make_graph_repository`` picks the backend named by ``AppSettings``; ``services.Services`` is the
only caller that wires it. The file backend needs the data directory to be writable by this
process only; the Mongo backend needs WRITE permission on ``AppSettings.storage_database``
(collection ``sankey_studio_graphs``). Run ONE worker process: file locking is per process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.storage.base import GraphRepository
from sankey_studio.storage.files import FileGraphRepository
from sankey_studio.storage.migrate import CopyReport, copy_graphs
from sankey_studio.storage.mongo_store import MongoGraphRepository, MongoStoreTarget
from sankey_studio.storage.settings_store import SettingsStore, dump_settings, load_settings

if TYPE_CHECKING:
    from sankey_studio.config import BootstrapConfig
    from sankey_studio.models import AppSettings
    from sankey_studio.mongo import MongoClients

__all__ = [
    "CopyReport",
    "FileGraphRepository",
    "GraphRepository",
    "MongoGraphRepository",
    "MongoStoreTarget",
    "SettingsStore",
    "copy_graphs",
    "dump_settings",
    "load_settings",
    "make_graph_repository",
    "storage_target",
]


def storage_target(settings: AppSettings) -> MongoStoreTarget:
    """The Mongo target named by ``settings`` (``StorageError`` when no connection is selected)."""
    return MongoStoreTarget(settings.storage_connection or "", settings.storage_database)


def make_graph_repository(
    settings: AppSettings, clients: MongoClients, config: BootstrapConfig
) -> GraphRepository:
    """The repository for ``settings.storage_backend`` (``file`` -> ``<data_dir>/graphs``)."""
    if settings.storage_backend == "mongo":
        return MongoGraphRepository(clients, storage_target(settings))
    return FileGraphRepository(config.graphs_dir)
