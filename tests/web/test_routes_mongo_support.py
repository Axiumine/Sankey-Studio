"""Helpers of ``tests/web/test_routes_mongo*.py`` (no tests here).

``build_rig`` serves the Mongo router over a ``FakeMongo`` (the recording fake of the MONGO tests:
mongomock has no ``list_databases`` and a ``list_collection_names`` without options), so a test
can see the exact arguments the driver would have received.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sankey_studio.config import BootstrapConfig
from sankey_studio.services import Services
from sankey_studio.storage import SettingsStore
from sankey_studio.web.app import create_app
from sankey_studio.web.routers.mongo import router
from tests.sources.test_mongo_fakes import FakeMongo
from tests.web.conftest import SAME_ORIGIN, TEST_HOSTS, new_client

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient
    from pymongo import MongoClient

    from sankey_studio.models import AppSettings

BASE = "/api/v1/mongo"
PASSWORD = "hunter2"
#: ``(remote_mode, remote_writes)``
LOCAL = (False, False)
REMOTE_READ_ONLY = (True, False)


class RigMongo(FakeMongo):
    """``FakeMongo`` that also closes: ``Services.close`` closes the clients it handed out."""

    closed = 0

    def close(self) -> None:
        self.closed += 1


@dataclass(frozen=True, slots=True)
class Rig:
    """The client, the fake behind it and the services (to patch the slot)."""

    client: TestClient
    fake: RigMongo
    services: Services
    config: BootstrapConfig


def error_of(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}
    error: dict[str, Any] = body["error"]
    assert set(error) == {"code", "message", "details"}
    return error


def build_rig(
    tmp_path: Path, fake: RigMongo, settings: AppSettings, mode: tuple[bool, bool] = LOCAL
) -> Iterator[Rig]:
    """A running app over ``fake``; generator for ``yield``-style fixtures (closes the services)."""
    remote_mode, remote_writes = mode
    config = BootstrapConfig(
        data_dir=tmp_path / "data",
        allowed_hosts=list(TEST_HOSTS),
        remote_mode=remote_mode,
        remote_writes=remote_writes,
    )
    SettingsStore(config).save(settings)
    client_of_fake = cast("MongoClient[Any]", fake)
    services = Services.create(config, mongo_factory=lambda _uri, _timeout: client_of_fake)
    app = create_app(config, services=services, routers=[router])
    with new_client(app, SAME_ORIGIN) as client:
        try:
            yield Rig(client, fake, services, config)
        finally:
            services.close()


def record_slots(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the connection slot by a recorder; the names whose slot gets entered."""
    entered: list[str] = []

    @contextmanager
    def record(connection: str) -> Iterator[None]:
        entered.append(connection)
        yield

    monkeypatch.setattr(rig.services.mongo, "slot", record)
    return entered
