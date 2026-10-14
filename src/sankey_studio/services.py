"""``Services``: the only place that wires settings, Mongo clients, storage and source context.

The web layer talks to this class and nothing else. One instance lives for the whole process.

* ``graphs()`` hands out ONE repository per ``(backend, connection, database, graphs_dir)`` so
  the file locks (and the Mongo slots) are shared by every request; it is rebuilt only when that
  key changes. ``folders()`` does the same for the library folders under the SAME key, so the
  two always sit on the same backend (on files they share one lock and one directory).
* ``update_settings`` changes the storage target in a fixed order that never loses data: ping the
  destination, optionally copy the folders and the graphs, then persist the settings. The old
  store is never deleted and any failure leaves the stored settings untouched.
* ``update_settings`` and ``test_storage`` (it connects to a caller-supplied URI) are privileged:
  both raise ``ReadOnlyModeError`` in remote mode without ``--allow-remote-writes``.
* ``settings_transaction()`` serialises every writer of ``settings.json`` on ONE lock. A writer
  that derives the new settings from the stored ones (the ``PUT /settings`` merge keeps a secret
  the caller did not resend) reads, merges and saves inside it, so it always merges against the
  latest stored settings and no concurrent save is lost. The lock is re-entrant: ``update_settings``
  takes it again for itself, and it is held across the ping/copy that a storage switch already
  does there (that is the whole point of a switch being atomic) and across no other network call.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sankey_studio.errors import ReadOnlyModeError, StorageError
from sankey_studio.mongo import ClientFactory, MongoClients, default_factory
from sankey_studio.sources.base import SourceContext
from sankey_studio.storage import (
    SettingsStore,
    Stores,
    copy_library,
    dump_settings,
    load_settings,
    make_folder_repository,
    make_graph_repository,
    make_stores,
)
from sankey_studio.storage.atomic import DIR_MODE, os_reason

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sankey_studio.config import BootstrapConfig
    from sankey_studio.models import AppSettings
    from sankey_studio.storage import CopyReport, FolderRepository, GraphRepository

#: ``(backend, connection, database, resolved graphs_dir)``
_RepoKey = tuple[str, str | None, str, "Path"]

MSG_READ_ONLY = "Settings cannot be changed in read-only remote mode (--allow-remote-writes)"
MSG_READ_ONLY_TEST = "Storage cannot be tested in read-only remote mode (--allow-remote-writes)"


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """The settings as saved, plus the report of the graph copy when one ran."""

    settings: AppSettings
    copy_report: CopyReport | None = None


def _uris(settings: AppSettings) -> dict[str, str]:
    return {c.name: c.uri.get_secret_value() for c in settings.mongo_connections}


def _storage_identity(settings: AppSettings) -> tuple[str | None, ...]:
    """What makes two settings point at the same graph store (the URI counts, in memory only)."""
    if settings.storage_backend == "file":
        return ("file",)
    wanted = settings.storage_connection
    uri = next(
        (c.uri.get_secret_value() for c in settings.mongo_connections if c.name == wanted), ""
    )
    return "mongo", settings.storage_connection, settings.storage_database, uri


class Services:
    def __init__(self, config: BootstrapConfig, mongo_factory: ClientFactory | None = None) -> None:
        self.config = config
        self._factory = mongo_factory or default_factory
        self._store = SettingsStore(config)
        #: Reads the stored settings on every ``get``, so edits apply without a restart.
        self.mongo = MongoClients(self._store.load, self._factory)
        self._graphs_lock = threading.Lock()
        self._graphs: tuple[_RepoKey, GraphRepository] | None = None
        self._folders: tuple[_RepoKey, FolderRepository] | None = None
        #: Re-entrant: ``settings_transaction`` encloses ``update_settings``, which locks itself.
        self._update_lock = threading.RLock()

    @classmethod
    def create(
        cls, config: BootstrapConfig, *, mongo_factory: ClientFactory | None = None
    ) -> Services:
        return cls(config, mongo_factory)

    def close(self) -> None:
        self.mongo.close()

    def settings(self) -> AppSettings:
        return self._store.load()

    # ------------------------------------------------------------------ storage

    def _repo_key(self, settings: AppSettings) -> _RepoKey:
        """What identifies the stores of ``settings``: graphs and folders share it."""
        return (
            settings.storage_backend,
            settings.storage_connection,
            settings.storage_database,
            self.config.graphs_dir.resolve(),
        )

    def graphs(self) -> GraphRepository:
        """The cached repository for the current settings (one instance per equal key)."""
        settings = self.settings()
        key = self._repo_key(settings)
        with self._graphs_lock:
            if self._graphs is None or self._graphs[0] != key:
                self._graphs = (key, make_graph_repository(settings, self.mongo, self.config))
            return self._graphs[1]

    def folders(self) -> FolderRepository:
        """The cached folder repository for the current settings, under the key of ``graphs()``."""
        settings = self.settings()
        key = self._repo_key(settings)
        with self._graphs_lock:
            if self._folders is None or self._folders[0] != key:
                self._folders = (key, make_folder_repository(settings, self.mongo, self.config))
            return self._folders[1]

    @contextmanager
    def _candidate(self, settings: AppSettings) -> Iterator[Stores]:
        """Graphs and folders on candidate ``settings``, own clients (nothing is saved)."""
        clients = MongoClients(lambda: settings, self._factory)
        try:
            yield make_stores(settings, clients, self.config)
        finally:
            clients.close()

    def _require_privileged_writes(self, message: str) -> None:
        """``ReadOnlyModeError`` (403) in remote mode without ``--allow-remote-writes``."""
        if not self.config.privileged_writes_allowed:
            raise ReadOnlyModeError(message)

    def test_storage(self, settings: AppSettings) -> None:
        """Ping the storage target of ``settings`` without saving anything.

        Refused like ``update_settings`` in read-only remote mode: the probe connects to a URI the
        caller supplies, which only a caller who may change the settings should be able to do.
        """
        self._require_privileged_writes(MSG_READ_ONLY_TEST)
        with self._candidate(settings) as stores:
            stores.ping()

    @contextmanager
    def settings_transaction(self) -> Iterator[None]:
        """Hold the one settings lock: read, merge, validate and save as a single step.

        Use it around ``settings()`` + ``update_settings(...)`` whenever the new settings are
        derived from the stored ones. ``test_storage`` never takes it (it saves nothing).
        """
        with self._update_lock:
            yield

    def update_settings(self, new: AppSettings, *, migrate: bool = False) -> UpdateResult:
        """Validate, switch the storage target when it changed, persist, drop stale clients."""
        self._require_privileged_writes(MSG_READ_ONLY)
        candidate = load_settings(dump_settings(new))  # SettingsError before any I/O
        with self._update_lock:
            old = self.settings()
            report = None
            if _storage_identity(old) != _storage_identity(candidate):
                report = self._switch_storage(candidate, migrate=migrate)
            saved = self._store.save(candidate)
            self._drop_stale_clients(old, saved)
        return UpdateResult(saved, report)

    def _switch_storage(self, new: AppSettings, *, migrate: bool) -> CopyReport | None:
        with self._candidate(new) as destination:
            destination.ping()
            if not migrate:
                return None
            return copy_library(Stores(self.graphs(), self.folders()), destination)

    def _drop_stale_clients(self, old: AppSettings, new: AppSettings) -> None:
        if old.mongo_timeout_ms != new.mongo_timeout_ms:  # the timeout is baked into a client
            self.mongo.invalidate(None)
            return
        current = _uris(new)
        for name, uri in _uris(old).items():
            if current.get(name) != uri:
                self.mongo.invalidate(name)

    # ------------------------------------------------------------------ sources

    def sources_dir(self) -> Path:
        """The managed sources directory, created on demand (and only that directory)."""
        path = self.config.effective_sources_dir
        try:
            path.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"The sources directory is not usable: {os_reason(exc)}") from exc
        return path

    def source_context(self, strict: bool = False) -> SourceContext:
        return SourceContext(
            settings=self.settings(),
            sources_dir=self.sources_dir(),
            mongo=self.mongo,
            strict=strict,
        )
