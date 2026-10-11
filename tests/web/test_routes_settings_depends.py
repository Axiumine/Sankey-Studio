"""Every persisting route of the settings and sources routers refuses by itself.

The body-size middleware already closes the upload route in read-only remote mode; these tests
mount the routers WITHOUT any middleware, so only the guard of each route can answer 403
``read_only_mode``: ``GuardedRoute`` (the settings router's ``route_class``) or the
``require_writes`` dependency (sources).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sankey_studio.config import BootstrapConfig
from sankey_studio.services import Services
from sankey_studio.web.deps import MSG_READ_ONLY
from sankey_studio.web.errors import register_error_handlers
from sankey_studio.web.routers.settings import router as settings_router
from sankey_studio.web.routers.sources import router as sources_router
from tests.web.test_routes_settings_support import BASE

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

FILES = "/api/v1/sources/files"


class Unsafe(NamedTuple):
    """A route that persists or connects: how to call it."""

    method: str
    path: str
    kwargs: dict[str, Any]


UNSAFE = [
    Unsafe("PUT", BASE, {"json": {}}),
    Unsafe("POST", f"{BASE}/storage/test", {"json": {}}),
    Unsafe("POST", f"{BASE}/mongo/test/test", {}),
    Unsafe("POST", FILES, {"files": {"file": ("a.csv", b"x")}}),
    Unsafe("DELETE", f"{FILES}/a.csv", {}),
]


def client_of(config: BootstrapConfig) -> Iterator[TestClient]:
    """The two routers behind nothing but the error handlers."""
    services = Services.create(config)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(settings_router)
    app.include_router(sources_router)
    app.state.config = config
    app.state.services = services
    try:
        yield TestClient(app)
    finally:
        services.close()


@pytest.fixture
def read_only(tmp_path: Path) -> Iterator[TestClient]:
    config = BootstrapConfig(data_dir=tmp_path / "data", remote_mode=True, allowed_hosts=["*"])
    yield from client_of(config)


@pytest.mark.parametrize("case", UNSAFE, ids=[f"{c.method} {c.path}" for c in UNSAFE])
def test_each_persisting_route_has_its_own_read_only_guard(
    read_only: TestClient, case: Unsafe
) -> None:
    response = read_only.request(case.method, case.path, **case.kwargs)
    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "read_only_mode", "message": MSG_READ_ONLY, "details": []}
    }


@pytest.fixture
def local(tmp_path: Path) -> Iterator[TestClient]:
    yield from client_of(BootstrapConfig(data_dir=tmp_path / "data"))


def test_the_same_routes_work_when_writes_are_allowed(local: TestClient) -> None:
    assert local.post(FILES, files={"file": ("a.csv", b"x")}).status_code == 201
    assert local.delete(f"{FILES}/a.csv").status_code == 204
    assert local.put(BASE, json={}).status_code == 200
    assert local.post(f"{BASE}/storage/test", json={}).status_code == 200
