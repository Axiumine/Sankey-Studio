"""E2E A.1 (settings): defaults, a PUT that is stored, ranges, and settings that act at once."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import MANY_LINKS, graph_draft
from tests.e2e.support.clients import json_of, make_client, upload_source
from tests.e2e.support.http_a_settings import (
    SETTINGS_PATH,
    get_settings,
    keys_of,
    put_settings,
    reset_settings,
    stored_settings,
)

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

MIB = 2**20
LIMITS = {
    "max_links": 1500,
    "max_drawn_links": 60,
    "max_upload_mb": 2,
    "mongo_timeout_ms": 2500,
    "theme": "dark",
}


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module; the fixture below resets its settings before every test."""
    return module_server


@pytest.fixture(autouse=True)
def factory_settings(live_server: LiveServer, api: httpx.Client) -> None:
    reset_settings(api, live_server)


def check_defaults(live_server: LiveServer, api: httpx.Client) -> None:
    settings = get_settings(api)
    assert (settings["storage_backend"], settings["storage_connection"]) == ("file", None)
    assert (settings["storage_database"], settings["theme"]) == ("sankey_studio", "system")
    assert settings["mongo_connections"] == []
    assert (settings["max_links"], settings["max_drawn_links"]) == (200_000, 3000)
    assert (settings["max_upload_mb"], settings["mongo_timeout_ms"]) == (25, 15_000)
    assert settings["bootstrap"] == {
        "sources_dir": str(live_server.sources_dir),
        "remote_mode": False,
        "writes_allowed": True,
    }
    assert settings["default_style"]["donut"]["max_slices"] == 6
    assert "uri" not in set(keys_of(settings))
    assert not live_server.settings_file.exists()  # defaults are not written until a save


def test_a_fresh_install_reports_the_documented_defaults(make_server: ServerFactory) -> None:
    live_server = make_server()  # its own server: nothing was ever saved on it
    with make_client(live_server) as api:
        check_defaults(live_server, api)


def test_the_get_answer_can_be_sent_back_unchanged(api: httpx.Client) -> None:
    before = get_settings(api)
    saved = put_settings(api, before)
    assert saved["settings"] == before
    assert saved["copy_report"] is None
    assert get_settings(api) == before


def test_a_saved_change_is_returned_listed_and_written_to_disk(
    live_server: LiveServer, api: httpx.Client
) -> None:
    saved = put_settings(api, {**get_settings(api), **LIMITS})
    assert {key: saved["settings"][key] for key in LIMITS} == LIMITS
    assert {key: get_settings(api)[key] for key in LIMITS} == LIMITS
    on_disk = stored_settings(live_server)
    assert {key: on_disk[key] for key in LIMITS} == LIMITS
    mode = stat.S_IMODE(live_server.settings_file.stat().st_mode)
    assert mode == 0o600  # the file may hold connection strings: owner only


def test_the_upload_limit_follows_the_saved_setting_at_once(api: httpx.Client) -> None:
    content = "a,b,1\n" * 250_000  # 1.5 MiB
    put_settings(api, {**get_settings(api), "max_upload_mb": 1})
    refused = upload_source(api, "big.csv", content)
    assert json_of(refused, 413)["error"]["code"] == "payload_too_large"
    put_settings(api, {**get_settings(api), "max_upload_mb": 2})
    assert json_of(upload_source(api, "big.csv", content), 201)["size"] == len(content)
    assert len(content) > MIB


def test_the_graph_size_limit_follows_the_saved_setting_at_once(api: httpx.Client) -> None:
    draft = graph_draft(MANY_LINKS.csv)
    assert json_of(api.post("/api/v1/preview", json=draft))["stats"]["links"] == MANY_LINKS.links
    put_settings(api, {**get_settings(api), "max_links": 100})
    refused = api.post("/api/v1/preview", json=draft)
    assert json_of(refused, 413)["error"]["code"] == "graph_too_large"
    put_settings(api, {**get_settings(api), "max_links": 5000})
    assert api.post("/api/v1/preview", json=draft).status_code == 200


def test_the_draw_limit_follows_the_saved_setting_at_once(api: httpx.Client) -> None:
    put_settings(api, {**get_settings(api), "max_drawn_links": 50})
    bundle = json_of(api.post("/api/v1/preview", json=graph_draft(MANY_LINKS.csv)))
    assert (bundle["stats"]["links"], bundle["stats"]["drawn_links"]) == (MANY_LINKS.links, 50)
    assert any("50" in warning for warning in bundle["warnings"])


def test_the_default_style_for_new_graphs_is_stored_and_checked(api: httpx.Client) -> None:
    current = get_settings(api)
    style = {
        **current["default_style"],
        "font_size": 20,
        "donut": {**current["default_style"]["donut"], "max_slices": 4},
    }
    saved = put_settings(api, {**current, "default_style": style})
    assert saved["settings"]["default_style"] == style
    assert get_settings(api)["default_style"]["donut"]["max_slices"] == 4
    too_big = {**style, "font_size": 99}
    refused = api.put(SETTINGS_PATH, json={**current, "default_style": too_big})
    error = json_of(refused, 422)["error"]
    assert any("default_style.font_size" in line for line in error["details"]), error["details"]
    assert get_settings(api)["default_style"]["font_size"] == 20  # the refused save changed nothing
