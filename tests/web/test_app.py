"""``create_app``: assembly, middleware order, ownership of services, hooks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from sankey_studio.config import BootstrapConfig
from sankey_studio.pipeline import ResultCache
from sankey_studio.services import Services
from sankey_studio.web import app as app_module
from sankey_studio.web import routers as router_registry
from sankey_studio.web.app import STATIC_DIR, create_app
from sankey_studio.web.middleware import (
    BodySizeLimit,
    CaseInsensitiveTrustedHost,
    CsrfGuard,
    SecurityHeaders,
)
from tests.web.conftest import SAME_ORIGIN, TEST_HOSTS, new_client

if TYPE_CHECKING:
    from sankey_studio.models import AppSettings
    from tests.web.conftest import AppFactory

JSON = {"Content-Type": "application/json"}
NOT_FOUND = {"error": {"code": "not_found", "message": "Not Found", "details": []}}

router = APIRouter()


@router.get("/api/v1/probe")
def _probe() -> dict[str, bool]:
    return {"ok": True}


@router.post("/api/v1/probe")
def _post(payload: dict[str, Any]) -> dict[str, int]:
    return {"keys": len(payload)}


@router.get("/static/vendor/plotly.min.js")
def _vendor() -> PlainTextResponse:
    return PlainTextResponse("served by a router", media_type="text/javascript")


def _config(tmp_path: Path, **options: Any) -> BootstrapConfig:
    return BootstrapConfig(data_dir=tmp_path / "data", allowed_hosts=list(TEST_HOSTS), **options)


def test_only_the_given_routers_are_served(make_app: AppFactory) -> None:
    one = make_app([router])
    none = make_app([])
    assert one.client.get("/api/v1/probe").json() == {"ok": True}
    assert none.client.get("/api/v1/probe").status_code == 404


def test_the_registry_is_the_default(make_app: AppFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router_registry, "ALL_ROUTERS", (router,))
    assert make_app().client.get("/api/v1/probe").json() == {"ok": True}


def test_there_is_no_docs_ui(make_app: AppFactory) -> None:
    web = make_app([router])
    assert (web.app.docs_url, web.app.redoc_url, web.app.openapi_url) == (None, None, None)
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        response = web.client.get(path)
        assert response.status_code == 404
        assert response.json() == NOT_FOUND


def test_the_state_holds_config_services_and_a_result_cache(make_app: AppFactory) -> None:
    web = make_app([router])
    assert web.app.state.config is web.config
    assert web.app.state.services is web.services
    assert isinstance(web.app.state.result_cache, ResultCache)
    assert web.app.title == "Sankey Studio"


def test_seeded_settings_are_visible_even_where_services_would_refuse_to_write(
    make_app: AppFactory, app_settings: AppSettings
) -> None:
    local = make_app(settings=app_settings)
    remote = make_app(mode="remote_read_only", settings=app_settings)
    assert [c.name for c in local.services.settings().mongo_connections] == ["test"]
    assert [c.name for c in remote.services.settings().mongo_connections] == ["test"]
    assert remote.config.remote_mode is True
    assert remote.config.privileged_writes_allowed is False


def test_a_given_result_cache_is_used(tmp_path: Path) -> None:
    cache = ResultCache(max_entries=3)
    app = create_app(_config(tmp_path), result_cache=cache)
    assert app.state.result_cache is cache


def test_a_non_loopback_bind_needs_remote_mode(tmp_path: Path) -> None:
    config = _config(tmp_path).model_copy(update={"host": "192.0.2.10"})
    with pytest.raises(ValueError, match="a non-loopback host needs remote mode") as raised:
        create_app(config)
    assert str(raised.value) == "a non-loopback host needs remote mode (--allow-remote)"
    remote = _config(tmp_path, remote_mode=True).model_copy(update={"host": "192.0.2.10"})
    assert isinstance(create_app(remote), FastAPI)


def _record_closes(monkeypatch: pytest.MonkeyPatch) -> list[Services]:
    closed: list[Services] = []

    def close(self: Services) -> None:
        closed.append(self)

    monkeypatch.setattr(Services, "close", close)
    return closed


def test_the_services_it_builds_are_closed_at_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed = _record_closes(monkeypatch)
    config = _config(tmp_path)
    app = create_app(config)
    assert isinstance(app.state.services, Services)
    assert app.state.services.config is config
    with TestClient(app):
        assert closed == []
    assert closed == [app.state.services]


def test_the_services_a_caller_passes_stay_the_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed = _record_closes(monkeypatch)
    config = _config(tmp_path)
    services = Services.create(config)
    with TestClient(create_app(config, services=services)):
        pass
    assert closed == []


def test_the_middleware_order_is_host_body_headers_csrf(make_app: AppFactory) -> None:
    web = make_app([router])
    stack: list[Any] = web.app.user_middleware  # outermost first
    assert [m.cls for m in stack] == [
        CaseInsensitiveTrustedHost,
        BodySizeLimit,
        SecurityHeaders,
        CsrfGuard,
    ]
    assert stack[0].kwargs == {"allowed_hosts": web.config.allowed_hosts, "www_redirect": False}
    assert stack[3].args == (web.config.allowed_hosts,)


def test_the_outer_middleware_answer_first(make_app: AppFactory) -> None:
    web = make_app([router])
    foreign = {"Origin": "http://evil.example", **JSON}
    big = b"a" * (8 * 2**20 + 1)
    bad_host = web.bare.post(
        "/api/v1/probe", content=big, headers={**foreign, "Host": "evil.example"}
    )
    too_big = web.bare.post("/api/v1/probe", content=big, headers=foreign)
    cross_origin = web.bare.post("/api/v1/probe", content=b"{}", headers=foreign)
    assert bad_host.status_code == 400
    assert too_big.status_code == 413
    assert cross_origin.status_code == 403
    # the CSRF refusal sits inside the security-headers middleware
    assert cross_origin.headers["x-content-type-options"] == "nosniff"


def test_a_wildcard_host_list_serves_any_host_in_remote_mode(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=tmp_path / "data", remote_mode=True, allowed_hosts=["*"])
    client = new_client(create_app(config, routers=[router]), SAME_ORIGIN)
    assert client.get("/api/v1/probe", headers={"Host": "anything.example"}).status_code == 200
    posted = client.post(
        "/api/v1/probe",
        json={"a": 1},
        headers={"Host": "anything.example", "Origin": "http://anything.example"},
    )
    assert posted.json() == {"keys": 1}


def test_the_static_hook_points_at_the_package_directory() -> None:
    assert Path(app_module.__file__).parent / "static" == STATIC_DIR
    assert STATIC_DIR.name == "static"


def test_static_files_are_served_with_the_page_headers(
    make_app: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "hello.txt").write_text("hi", encoding="utf-8")
    monkeypatch.setattr(app_module, "STATIC_DIR", tmp_path / "static")
    web = make_app([router])
    served = web.client.get("/static/hello.txt")
    missing = web.client.get("/static/missing.txt")
    wrong_host = web.bare.get("/static/hello.txt", headers={"Host": "evil.example"})
    wrong_method = web.client.post("/static/hello.txt", json={})
    assert (served.status_code, served.text) == (200, "hi")
    assert web.app.url_path_for("static", path="hello.txt") == "/static/hello.txt"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "cache-control" not in served.headers
    assert (missing.status_code, missing.json()) == (404, NOT_FOUND)
    assert wrong_host.status_code == 400
    assert wrong_method.status_code == 405


def test_a_router_route_wins_over_the_static_mount(make_app: AppFactory) -> None:
    response = make_app([router]).client.get("/static/vendor/plotly.min.js")
    assert response.text == "served by a router"


def test_a_missing_static_directory_is_simply_not_mounted(
    make_app: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "STATIC_DIR", tmp_path / "does-not-exist")
    response = make_app([router]).client.get("/static/x.js")
    assert (response.status_code, response.json()) == (404, NOT_FOUND)
