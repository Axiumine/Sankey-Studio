"""The settings routes in the three modes: local, remote read-only and remote with writes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.mongo import MongoClients
from sankey_studio.util import MASKED_URI
from sankey_studio.web.deps import MSG_READ_ONLY, GuardedRoute
from sankey_studio.web.routers.settings import router
from tests.conftest import TEST_URI
from tests.web.test_routes_settings_support import (
    BASE,
    MASKED_TEST_URI,
    PASSWORD,
    error_of,
    put_body,
    stored_uri,
)

if TYPE_CHECKING:
    from sankey_studio.models import AppSettings
    from tests.web.conftest import AppFactory, Mode, WebApp

REFUSED = {"code": "read_only_mode", "message": MSG_READ_ONLY, "details": []}
UNSAFE = [
    ("PUT", BASE),
    ("POST", f"{BASE}/storage/test"),
    ("POST", f"{BASE}/mongo/test/test"),
]


@pytest.fixture
def read_only(make_app: AppFactory, app_settings: AppSettings) -> WebApp:
    return make_app([router], mode="remote_read_only", settings=app_settings)


def test_the_read_only_listing_hides_hosts_and_user_names(read_only: WebApp) -> None:
    response = read_only.client.get(BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["mongo_connections"] == [
        {
            "name": "test",
            "uri_masked": MASKED_URI,
            "has_secret": True,
            "default_database": "flows",
        }
    ]
    for hidden in ("tester", "mongo.invalid", PASSWORD, "27017"):
        assert hidden not in response.text
    assert body["bootstrap"]["remote_mode"] is True
    assert body["bootstrap"]["writes_allowed"] is False


@pytest.mark.parametrize(("method", "path"), UNSAFE)
def test_every_persisting_route_answers_403_read_only_mode(
    read_only: WebApp, method: str, path: str
) -> None:
    body = {**put_body(read_only.client), "theme": "dark"}
    response = read_only.client.request(method, path, json=body)
    assert response.status_code == 403
    assert error_of(response) == REFUSED
    assert read_only.services.settings().theme == "system"
    assert stored_uri(read_only) == TEST_URI


@pytest.mark.parametrize(("method", "path"), UNSAFE)
def test_the_guard_answers_before_the_body_is_judged(
    read_only: WebApp, method: str, path: str
) -> None:
    response = read_only.client.request(method, path, json={"storage_backend": "bogus"})
    assert response.status_code == 403
    assert error_of(response) == REFUSED


UNDECODABLE = [b"{", b"not json", b"\xff\xfe", b'{"theme": ', b""]
JSON = {"Content-Type": "application/json"}


@pytest.mark.parametrize(("method", "path"), UNSAFE)
@pytest.mark.parametrize("raw", UNDECODABLE)
def test_an_undecodable_body_is_a_403_not_a_422_in_read_only_mode(
    read_only: WebApp, method: str, path: str, raw: bytes
) -> None:
    response = read_only.client.request(method, path, content=raw, headers=JSON)
    assert response.status_code == 403
    assert error_of(response) == REFUSED
    assert response.headers["Content-Type"] == "application/json"
    assert read_only.services.settings().theme == "system"


@pytest.mark.parametrize(("method", "path"), UNSAFE[:2])
@pytest.mark.parametrize("mode", ["local", "remote_writes"])
def test_where_writes_are_allowed_an_undecodable_body_is_still_a_422(
    make_app: AppFactory, method: str, path: str, mode: Mode
) -> None:
    web = make_app([router], mode=mode)
    response = web.client.request(method, path, content=b"{", headers=JSON)
    assert response.status_code == 422
    assert error_of(response)["code"] == "validation_error"


def test_the_settings_router_guards_by_its_route_class() -> None:
    assert router.route_class is GuardedRoute
    assert all(isinstance(route, GuardedRoute) for route in router.routes)


def test_a_refused_probe_never_touches_mongo(
    read_only: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: Any) -> float:
        pytest.fail("a read-only app must not ping")

    monkeypatch.setattr(MongoClients, "ping", forbidden)
    assert read_only.client.post(f"{BASE}/mongo/test/test").status_code == 403
    body = {**put_body(read_only.client), "storage_backend": "mongo", "storage_connection": "test"}
    assert read_only.client.post(f"{BASE}/storage/test", json=body).status_code == 403


def test_remote_mode_with_writes_behaves_like_local_mode_but_shows_the_flags(
    make_app: AppFactory, app_settings: AppSettings
) -> None:
    web = make_app([router], mode="remote_writes", settings=app_settings)
    listed = web.client.get(BASE).json()
    assert listed["bootstrap"] == {
        "sources_dir": str(web.config.effective_sources_dir),
        "remote_mode": True,
        "writes_allowed": True,
    }
    assert listed["mongo_connections"][0]["uri_masked"] == MASKED_TEST_URI
    saved = web.client.put(BASE, json={**put_body(web.client), "theme": "dark"})
    assert saved.status_code == 200
    assert web.services.settings().theme == "dark"
    assert web.client.post(f"{BASE}/mongo/test/test").status_code == 200
    assert web.client.post(f"{BASE}/storage/test", json=put_body(web.client)).status_code == 200


def test_local_mode_reports_writes_allowed(make_app: AppFactory, app_settings: AppSettings) -> None:
    web = make_app([router], settings=app_settings)
    bootstrap = web.client.get(BASE).json()["bootstrap"]
    assert (bootstrap["remote_mode"], bootstrap["writes_allowed"]) == (False, True)
