# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Fixtures shared by every ``tests/web`` module (router agents import from here).

* ``make_app(routers=None, *, mode="local", settings=None) -> WebApp``: a real ``create_app``
  over a ``tmp_path`` data dir and ``Services`` backed by mongomock (the ``mongo_client``
  fixture of ``tests/conftest.py``; no network, no real Chrome here: monkeypatch
  ``render.export.images._render_image``). ``routers=None`` serves ``ALL_ROUTERS``; a router's
  own tests pass ``routers=[theirs]``. ``mode`` is ``"local"``, ``"remote_read_only"``
  (``remote_mode``) or ``"remote_writes"`` (``remote_mode`` + ``remote_writes``). ``settings``
  is written to ``settings.json`` first (bypassing the read-only guard of ``Services``).
* ``WebApp.client`` sends the headers a browser sends from the app's own pages (``SAME_ORIGIN``),
  so state-changing calls pass the CSRF guard; ``WebApp.bare`` sends nothing extra (a script).
* ``web`` / ``remote_web`` / ``client``: ready-made local and read-only remote apps.
* ``new_client(app, headers=None, *, raise_exc=True)``: a ``TestClient`` (``raise_exc=False``
  turns an unhandled error into the 500 response instead of an exception in the test).
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

import pytest
from fastapi.testclient import TestClient

from sankey_studio.config import BootstrapConfig
from sankey_studio.services import Services
from sankey_studio.storage import SettingsStore
from sankey_studio.web.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from fastapi import APIRouter, FastAPI
    from pymongo import MongoClient

    from sankey_studio.models import AppSettings

#: What a browser sends for a request from one of the app's own pages (TestClient host).
SAME_ORIGIN: Final = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
TEST_HOSTS: Final = ["localhost", "127.0.0.1", "[::1]", "testserver"]

Mode = Literal["local", "remote_read_only", "remote_writes"]
#: ``(remote_mode, remote_writes)`` of each mode.
_MODES: Final[dict[Mode, tuple[bool, bool]]] = {
    "local": (False, False),
    "remote_read_only": (True, False),
    "remote_writes": (True, True),
}


@dataclass(frozen=True, slots=True)
class WebApp:
    """An app plus everything a test needs to poke at it."""

    app: FastAPI
    client: TestClient
    bare: TestClient
    services: Services
    config: BootstrapConfig
    mongo: MongoClient[Any]


class AppFactory(Protocol):
    def __call__(
        self,
        routers: Sequence[APIRouter] | None = None,
        *,
        mode: Mode = "local",
        settings: AppSettings | None = None,
    ) -> WebApp: ...


def new_client(
    app: FastAPI, headers: Mapping[str, str] | None = None, *, raise_exc: bool = True
) -> TestClient:
    """A ``TestClient`` for ``app`` with ``headers`` as defaults."""
    client = TestClient(app, raise_server_exceptions=raise_exc)
    client.headers.update(headers or {})
    return client


@pytest.fixture
def make_app(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[AppFactory]:
    """Factory of ``WebApp`` objects; the clients' lifespans are closed at teardown."""
    stack = ExitStack()

    def build(
        routers: Sequence[APIRouter] | None = None,
        *,
        mode: Mode = "local",
        settings: AppSettings | None = None,
    ) -> WebApp:
        remote_mode, remote_writes = _MODES[mode]
        config = BootstrapConfig(
            data_dir=tmp_path / "data",
            allowed_hosts=list(TEST_HOSTS),
            remote_mode=remote_mode,
            remote_writes=remote_writes,
        )
        if settings is not None:
            SettingsStore(config).save(settings)
        services = Services.create(config, mongo_factory=lambda _uri, _timeout: mongo_client)
        app = create_app(config, services=services, routers=routers)
        client = stack.enter_context(new_client(app, SAME_ORIGIN))
        return WebApp(app, client, new_client(app), services, config, mongo_client)

    with stack:
        yield build


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    """A local app serving ``ALL_ROUTERS``."""
    return make_app()


@pytest.fixture
def remote_web(make_app: AppFactory) -> WebApp:
    """A remote-mode app without ``--allow-remote-writes`` (persisting endpoints answer 403)."""
    return make_app(mode="remote_read_only")


@pytest.fixture
def client(web: WebApp) -> TestClient:
    """The same-origin client of ``web``."""
    return web.client
