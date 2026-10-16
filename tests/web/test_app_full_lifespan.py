# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The FULL app owns the ``Services`` it builds: shutdown closes them and their Mongo clients."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from fastapi.testclient import TestClient

from sankey_studio.config import BootstrapConfig
from sankey_studio.services import Services
from sankey_studio.storage import SettingsStore
from sankey_studio.web.app import create_app
from tests.web.conftest import SAME_ORIGIN, TEST_HOSTS

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI
    from pymongo import MongoClient

    from sankey_studio.models import AppSettings


class Rig(NamedTuple):
    app: FastAPI
    closed: list[str]


@pytest.fixture
def rig(
    tmp_path: Path,
    mongo_client: MongoClient[Any],
    app_settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> Rig:
    """``create_app(config)`` over mongomock: the app builds (and so owns) its ``Services``."""
    config = BootstrapConfig(data_dir=tmp_path / "data", allowed_hosts=list(TEST_HOSTS))
    SettingsStore(config).save(app_settings)
    closed: list[str] = []
    monkeypatch.setattr(type(mongo_client), "close", lambda _self: closed.append("client"))
    monkeypatch.setattr(
        Services,
        "create",
        staticmethod(lambda cfg: Services(cfg, lambda _uri, _timeout: mongo_client)),
    )
    return Rig(create_app(config), closed)


def ping(client: TestClient) -> int:
    """Makes the app open its Mongo client (the probe of the stored ``test`` connection)."""
    return client.post("/api/v1/settings/mongo/test/test").status_code


def test_shutdown_closes_the_services_the_app_built(rig: Rig) -> None:
    app = rig.app
    assert isinstance(app.state.services, Services)
    with TestClient(app, headers=SAME_ORIGIN) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        assert ping(client) == 200
        assert rig.closed == []
    assert rig.closed == ["client"]


def fail_inside(app: FastAPI, message: str) -> None:
    with TestClient(app, headers=SAME_ORIGIN) as client:
        assert ping(client) == 200
        raise RuntimeError(message)


def test_shutdown_closes_the_services_when_the_app_fails_inside(rig: Rig) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        fail_inside(rig.app, "boom")
    assert rig.closed == ["client"]


def test_the_full_app_uses_a_lifespan_not_event_handlers(rig: Rig) -> None:
    router = rig.app.router
    assert router.lifespan_context is not None
    assert getattr(router, "on_startup", []) == []
    assert getattr(router, "on_shutdown", []) == []
