# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``LiveServer``: the real Sankey Studio app served by uvicorn in a thread of the test process.

* Binds ``127.0.0.1`` on an EPHEMERAL port: the socket is bound to port 0 first, the port is read
  back, and the bound socket is handed to uvicorn (no race with another process, never a fixed
  port; 8000 and 27017-27019 belong to other projects on this machine).
* ``Services.create(config, mongo_factory=...)`` with a mongomock factory: there is no MongoDB. One
  ``E2EMongoClient`` (mongomock plus the inspect calls and an outage switch, see ``mongo.py``) per
  server answers every connection name (``LiveServer.mongo``); seed it with the ``seed_mongo``
  option or directly. A configured connection URI is never dialled.
* ``data_dir`` and ``sources_dir`` are fresh directories under the ``root`` the caller passes
  (``tmp_path`` in the fixtures). ``allowed_hosts`` is ``127.0.0.1`` / ``localhost``.
* ``stop()`` (also the fixtures' teardown) asks uvicorn to exit, joins the thread, closes the
  services, re-raises an error the server thread died with and asserts that the port is closed.

``ServerOptions`` (all optional keyword arguments of ``make_server`` / ``running_server``):

* ``remote_mode: bool`` - ``--allow-remote``: read-only remote server (banners, 403 on every write).
* ``allow_remote_writes: bool`` - ``--allow-remote-writes``: only valid together with remote_mode.
* ``allow_source_writes: bool`` - ``--allow-source-writes``: MongoDB write-back on a remote server;
  only valid together with allow_remote_writes.
* ``settings: Mapping[str, Any]`` - ``AppSettings`` fields written to ``settings.json`` before the
  server starts (``{"max_links": 100, "max_drawn_links": 50}``), bypassing the read-only guard.
* ``export_unavailable: bool`` - image exports (svg/png) answer the production 501
  ``export_unavailable`` (see ``unavailable.py``); html/json/csv exports and all else are real.
* ``seed_mongo: Callable[[MongoClient], None]`` - called with the mongomock client before start.
* ``mongo_factory: ClientFactory`` - replaces the mongomock factory ``(uri, timeout_ms) -> client``;
  only the ``@pytest.mark.mongo`` suites do this, with ``sankey_studio.mongo.default_factory``
  and ``SANKEY_TEST_MONGO_URI``. ``LiveServer.mongo`` is then an unused mongomock client.

``ServerFactory`` is the type of the ``make_server`` fixture: ``make_server(**options)``.
"""

from __future__ import annotations

import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, TypedDict, Unpack

import uvicorn

from sankey_studio.config import BootstrapConfig
from sankey_studio.models import AppSettings
from sankey_studio.services import Services
from sankey_studio.storage import SettingsStore
from sankey_studio.web.app import create_app
from tests.e2e.support.mongo import E2EMongoClient
from tests.e2e.support.unavailable import ExportUnavailable
from tests.e2e.support.waits import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from pymongo import MongoClient
    from starlette.types import ASGIApp

    from sankey_studio.mongo import ClientFactory

HOST: Final = "127.0.0.1"
ALLOWED_HOSTS: Final = ("127.0.0.1", "localhost")
START_TIMEOUT_S: Final = 20.0
STOP_TIMEOUT_S: Final = 20.0
GRACEFUL_SHUTDOWN_S: Final = 5
PROBE_TIMEOUT_S: Final = 1.0


class ServerOptions(TypedDict, total=False):
    """The keyword options of ``make_server`` (see the module doc)."""

    remote_mode: bool
    allow_remote_writes: bool
    allow_source_writes: bool
    settings: Mapping[str, Any]
    export_unavailable: bool
    seed_mongo: Callable[[MongoClient[Any]], None]
    mongo_factory: ClientFactory


class ServerFactory(Protocol):
    """``make_server(**options) -> LiveServer``: a started server, stopped at fixture teardown."""

    def __call__(self, **options: Unpack[ServerOptions]) -> LiveServer: ...


class ServerThread(threading.Thread):
    """Runs ``server.run``; an exception is kept for ``LiveServer.stop`` instead of being lost."""

    def __init__(self, server: uvicorn.Server, sock: socket.socket) -> None:
        super().__init__(name="e2e-uvicorn", daemon=True)
        self.server = server
        self.sock = sock
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.server.run(sockets=[self.sock])
        except BaseException as exc:  # noqa: BLE001 - kept and re-raised by LiveServer.stop
            self.error = exc


def port_is_closed(host: str, port: int) -> bool:
    """True when nothing accepts a TCP connection on ``host:port``."""
    try:
        socket.create_connection((host, port), timeout=PROBE_TIMEOUT_S).close()
    except OSError:
        return True
    return False


@dataclass(slots=True)
class LiveServer:
    """A running server: where it is, what backs it, and how to stop it.

    ``url`` is ``http://127.0.0.1:<port>`` (no trailing slash); ``url_for("/graphs/new")`` joins a
    path. ``config`` / ``services`` are the real objects of the app, ``mongo`` is the mongomock
    client behind every Mongo connection. ``data_dir``, ``sources_dir``, ``graphs_dir`` and
    ``settings_file`` are paths of this server only. ``read_only`` is true for the read-only remote
    variant (``remote_mode`` without ``allow_remote_writes``).
    """

    config: BootstrapConfig
    services: Services
    mongo: E2EMongoClient
    options: ServerOptions
    server: uvicorn.Server
    thread: ServerThread
    port: int
    stopped: bool = False

    @property
    def host(self) -> str:
        return HOST

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def url_for(self, path: str) -> str:
        return f"{self.url}/{path.lstrip('/')}"

    @property
    def data_dir(self) -> Path:
        return self.config.data_dir

    @property
    def sources_dir(self) -> Path:
        return self.config.effective_sources_dir

    @property
    def graphs_dir(self) -> Path:
        return self.config.graphs_dir

    @property
    def settings_file(self) -> Path:
        return self.config.settings_file

    @property
    def read_only(self) -> bool:
        return not self.config.privileged_writes_allowed

    def stop(self) -> None:
        """Stop the server, join its thread and assert the port is closed (idempotent)."""
        if self.stopped:
            return
        self.stopped = True
        self.server.should_exit = True
        self.thread.join(STOP_TIMEOUT_S)
        self.thread.sock.close()
        self.services.close()
        if self.thread.is_alive():
            raise AssertionError(f"the server thread did not stop within {STOP_TIMEOUT_S:g}s")
        if self.thread.error is not None:
            raise AssertionError("the server thread died with an error") from self.thread.error
        if not port_is_closed(HOST, self.port):
            raise AssertionError(f"port {self.port} still accepts connections after stop()")


def make_config(root: Path, port: int, options: ServerOptions) -> BootstrapConfig:
    """The bootstrap config of a test server. Every field is passed, so no ``SANKEY_*``
    environment variable of the developer can leak in (init values beat the environment)."""
    return BootstrapConfig(
        host=HOST,
        port=port,
        data_dir=root / "data",
        sources_dir=root / "sources",
        log_level="warning",
        allowed_hosts=list(ALLOWED_HOSTS),
        mongo_uri=None,
        remote_mode=options.get("remote_mode", False),
        remote_writes=options.get("allow_remote_writes", False),
        source_writes=options.get("allow_source_writes", False),
    )


def build_app(config: BootstrapConfig, services: Services, options: ServerOptions) -> ASGIApp:
    """The real ``create_app``, wrapped only when the options ask for a forced 501."""
    app = create_app(config, services=services)
    return ExportUnavailable(app) if options.get("export_unavailable") else app


def make_uvicorn(app: ASGIApp, port: int) -> uvicorn.Server:
    """A uvicorn server for ``app``: h11, no websockets, no logging reconfiguration."""
    config = uvicorn.Config(
        app,
        host=HOST,
        port=port,
        http="h11",
        ws="none",
        lifespan="on",
        log_level="warning",
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
    )
    return uvicorn.Server(config)


def bind_ephemeral() -> socket.socket:
    """A socket bound to ``127.0.0.1`` on a port the OS picked (read it from ``getsockname``)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, 0))
    except OSError:
        sock.close()
        raise
    return sock


def _prepare(
    root: Path, port: int, mongo: MongoClient[Any], options: ServerOptions
) -> tuple[BootstrapConfig, Services]:
    """Config, preloaded settings and services (backed by the mongomock client) of one server."""
    config = make_config(root, port, options)
    overrides = options.get("settings")
    if overrides is not None:
        SettingsStore(config).save(AppSettings(**overrides))
    factory = options.get("mongo_factory") or (lambda _uri, _timeout: mongo)
    return config, Services.create(config, mongo_factory=factory)


def start_server(root: Path, options: ServerOptions | None = None) -> LiveServer:
    """Start a server under ``root`` and return it once uvicorn reports it started."""
    options = options or {}
    mongo = E2EMongoClient(tz_aware=True)
    seed = options.get("seed_mongo")
    if seed is not None:
        seed(mongo)
    sock = bind_ephemeral()
    port = int(sock.getsockname()[1])
    try:
        config, services = _prepare(root, port, mongo, options)
    except BaseException:
        sock.close()
        raise
    server = make_uvicorn(build_app(config, services, options), port)
    thread = ServerThread(server, sock)
    live = LiveServer(config, services, mongo, options, server, thread, port)
    thread.start()
    try:
        wait_until(
            lambda: server.started or not thread.is_alive(),
            timeout=START_TIMEOUT_S,
            what=f"the server on port {port} to start",
        )
    except BaseException:
        live.stop()
        raise
    if not server.started:
        live.stop()  # re-raises the error the thread died with
        raise AssertionError("the server thread exited during start-up")
    return live


@contextmanager
def running_server(root: Path, **options: Unpack[ServerOptions]) -> Iterator[LiveServer]:
    """``start_server`` for a ``with`` block (keyword options); stopped when the block exits."""
    live = start_server(root, options)
    try:
        yield live
    finally:
        live.stop()
