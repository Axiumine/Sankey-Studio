# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Saved-graph storage: the repositories, the settings file and migration helpers.

``make_graph_repository`` and ``make_folder_repository`` pick the backend named by
``AppSettings`` (``make_stores`` builds both as a ``Stores`` pair); ``services.Services`` is the
only caller that wires them. The file backend needs the data directory to be writable by this
process only; the Mongo backend needs WRITE permission on ``AppSettings.storage_database``
(collections ``sankey_studio_graphs`` and ``sankey_studio_collections``, the library folders).
Run ONE worker process: file locking is per process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.storage.base import GraphRepository
from sankey_studio.storage.files import FileFolderRepository, FileGraphRepository
from sankey_studio.storage.folders_base import FolderRepository
from sankey_studio.storage.migrate import (
    CopyReport,
    FolderCopy,
    copy_folders,
    copy_graphs,
    copy_library,
)
from sankey_studio.storage.mongo_folder_store import MongoFolderRepository
from sankey_studio.storage.mongo_store import MongoGraphRepository, MongoStoreTarget
from sankey_studio.storage.settings_store import SettingsStore, dump_settings, load_settings
from sankey_studio.storage.stores import Stores

if TYPE_CHECKING:
    from sankey_studio.config import BootstrapConfig
    from sankey_studio.models import AppSettings
    from sankey_studio.mongo import MongoClients

__all__ = [
    "CopyReport",
    "FileFolderRepository",
    "FileGraphRepository",
    "FolderCopy",
    "FolderRepository",
    "GraphRepository",
    "MongoFolderRepository",
    "MongoGraphRepository",
    "MongoStoreTarget",
    "SettingsStore",
    "Stores",
    "copy_folders",
    "copy_graphs",
    "copy_library",
    "dump_settings",
    "load_settings",
    "make_folder_repository",
    "make_graph_repository",
    "make_stores",
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


def make_folder_repository(
    settings: AppSettings, clients: MongoClients, config: BootstrapConfig
) -> FolderRepository:
    """The folder repository of the same backend (``file`` -> ``<data_dir>/graphs/folders.json``).

    On the file backend it shares the lock and the listing index with the graph repository of the
    same directory, so a folder change and a graph write exclude each other.
    """
    if settings.storage_backend == "mongo":
        return MongoFolderRepository(clients, storage_target(settings))
    return FileFolderRepository(config.graphs_dir)


def make_stores(settings: AppSettings, clients: MongoClients, config: BootstrapConfig) -> Stores:
    """Graphs and folders of ``settings`` as one pair."""
    return Stores(
        make_graph_repository(settings, clients, config),
        make_folder_repository(settings, clients, config),
    )
