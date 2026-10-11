"""``POST /settings/mongo/{name}/test`` and ``POST /settings/storage/test``."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import BusyError
from sankey_studio.mongo import MongoClients
from sankey_studio.web.routers.settings import router
from tests.web.test_routes_settings_support import (
    BASE,
    PASSWORD,
    break_ping,
    error_of,
    put_body,
)
from tests.web.test_routes_sources_support import BLOCKER_TEXT, block_sources_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import NoReturn

    from sankey_studio.models import AppSettings
    from tests.web.conftest import AppFactory, WebApp

MONGO_TEST = f"{BASE}/mongo/test/test"
STORAGE_TEST = f"{BASE}/storage/test"


@pytest.fixture
def web(make_app: AppFactory, app_settings: AppSettings) -> WebApp:
    return make_app([router], settings=app_settings)


@pytest.fixture
def slots(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The connection names whose slot was entered (the real slot is replaced by a recorder)."""
    entered: list[str] = []

    @contextmanager
    def record(connection: str) -> Iterator[None]:
        entered.append(connection)
        yield

    monkeypatch.setattr(web.services.mongo, "slot", record)
    return entered


# --------------------------------------------------------------------------- mongo


def test_a_stored_connection_answers_a_ping(web: WebApp) -> None:
    response = web.client.post(MONGO_TEST)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ok", "latency_ms"}
    assert body["ok"] is True
    assert isinstance(body["latency_ms"], float)
    assert body["latency_ms"] >= 0


@pytest.mark.parametrize(("measured", "shown"), [(12.34, 12.3), (12.36, 12.4), (0.04, 0.0)])
def test_the_latency_is_rounded_to_a_tenth_of_a_millisecond(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, measured: float, shown: float
) -> None:
    pings: list[str] = []

    def fake_ping(_self: MongoClients, connection: str) -> float:
        pings.append(connection)
        return measured

    monkeypatch.setattr(MongoClients, "ping", fake_ping)
    response = web.client.post(MONGO_TEST)
    assert response.json() == {"ok": True, "latency_ms": shown}
    assert pings == ["test"]


def test_the_ping_runs_inside_the_connection_slot(web: WebApp, slots: list[str]) -> None:
    assert web.client.post(MONGO_TEST).status_code == 200
    assert slots == ["test"]


def test_a_busy_connection_is_a_503_busy(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> None:
    def busy(connection: str) -> NoReturn:
        raise BusyError(f"MongoDB connection '{connection}' is busy; try again shortly")

    monkeypatch.setattr(web.services.mongo, "slot", busy)
    response = web.client.post(MONGO_TEST)
    assert response.status_code == 503
    assert error_of(response) == {
        "code": "busy",
        "message": "MongoDB connection 'test' is busy; try again shortly",
        "details": [],
    }


@pytest.mark.parametrize(
    ("name", "shown"),
    [("nope", "nope"), ("Prod-1.db", "Prod-1.db"), ("a%20b", "?"), ("%3Cb%3Ex", "?")],
)
def test_an_unknown_connection_is_a_404_and_gets_no_slot(
    web: WebApp, slots: list[str], name: str, shown: str
) -> None:
    response = web.client.post(f"{BASE}/mongo/{name}/test")
    assert response.status_code == 404
    assert error_of(response) == {
        "code": "source_not_found",
        "message": f"Unknown MongoDB connection '{shown}'",
        "details": [],
    }
    assert slots == []


def test_an_unreachable_server_is_a_503_that_names_only_the_connection(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    break_ping(monkeypatch, web)
    response = web.client.post(MONGO_TEST)
    assert response.status_code == 503
    assert error_of(response) == {
        "code": "storage_error",
        "message": "MongoDB connection 'test' is unreachable",
        "details": [],
    }
    assert PASSWORD not in response.text
    assert "mongo.invalid" not in response.text


def test_the_mongo_probe_does_not_need_the_sources_directory(web: WebApp) -> None:
    blocker = block_sources_dir(web.config)
    response = web.client.post(MONGO_TEST)
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert blocker.read_bytes() == BLOCKER_TEXT


def test_an_unknown_connection_is_a_404_even_with_an_unusable_sources_directory(
    web: WebApp,
) -> None:
    block_sources_dir(web.config)
    response = web.client.post(f"{BASE}/mongo/nope/test")
    assert response.status_code == 404
    assert error_of(response)["code"] == "source_not_found"


def test_the_mongo_probe_never_creates_the_sources_directory(web: WebApp) -> None:
    assert web.client.post(MONGO_TEST).status_code == 200
    assert not web.config.effective_sources_dir.exists()


def test_the_mongo_probe_is_post_only(web: WebApp) -> None:
    assert web.client.get(MONGO_TEST).status_code == 405
    assert web.client.put(MONGO_TEST).status_code == 405


# --------------------------------------------------------------------------- storage


def candidate(web: WebApp, **fields: Any) -> dict[str, Any]:
    return {**put_body(web.client), **fields}


def test_the_file_store_passes_and_nothing_is_saved(web: WebApp) -> None:
    before = web.config.settings_file.read_bytes()
    response = web.client.post(STORAGE_TEST, json=candidate(web, theme="dark"))
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert web.config.settings_file.read_bytes() == before
    assert web.services.settings().theme == "system"


def test_a_mongo_store_passes_when_the_connection_answers(web: WebApp) -> None:
    before = web.config.settings_file.read_bytes()
    body = candidate(web, storage_backend="mongo", storage_connection="test")
    response = web.client.post(STORAGE_TEST, json=body)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert web.services.settings().storage_backend == "file"
    assert web.config.settings_file.read_bytes() == before


def test_an_unreachable_mongo_store_fails_without_saving(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    break_ping(monkeypatch, web)
    body = candidate(web, storage_backend="mongo", storage_connection="test")
    response = web.client.post(STORAGE_TEST, json=body)
    assert response.status_code == 503
    assert error_of(response)["code"] == "storage_error"
    assert PASSWORD not in response.text
    assert web.services.settings().storage_backend == "file"


def test_a_candidate_with_a_new_connection_and_its_uri_can_be_probed(web: WebApp) -> None:
    new = {"name": "second", "uri": "mongodb://other.invalid:27017/", "default_database": None}
    body = candidate(web, storage_backend="mongo", storage_connection="second")
    body["mongo_connections"] = [*body["mongo_connections"], new]
    response = web.client.post(STORAGE_TEST, json=body)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert [c.name for c in web.services.settings().mongo_connections] == ["test"]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"storage_backend": "mongo", "storage_connection": "nope"}, "settings_error"),
        ({"mongo_connections": [{"name": "fresh"}]}, "settings_error"),
        ({"storage_backend": "sqlite"}, "validation_error"),
        ({"max_upload_mb": 0}, "validation_error"),
    ],
)
def test_a_bad_candidate_is_a_422(web: WebApp, change: dict[str, Any], code: str) -> None:
    response = web.client.post(STORAGE_TEST, json=candidate(web, **change))
    assert response.status_code == 422
    assert error_of(response)["code"] == code


def test_the_storage_probe_needs_a_body_and_is_post_only(web: WebApp) -> None:
    assert web.client.post(STORAGE_TEST).status_code == 422
    assert web.client.get(STORAGE_TEST).status_code == 405


def test_the_probes_follow_the_csrf_and_content_type_rules_of_unsafe_routes(web: WebApp) -> None:
    text = {"Content-Type": "text/plain"}
    assert web.bare.post(MONGO_TEST).status_code == 403
    assert web.bare.post(MONGO_TEST, content=b"x", headers=text).status_code == 403
    assert web.client.post(MONGO_TEST, content=b"x", headers=text).status_code == 415
    assert web.bare.post(MONGO_TEST, json={}).status_code == 200
