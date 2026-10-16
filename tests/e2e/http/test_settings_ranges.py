# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E A.1 (settings): the ranges of every field, edges accepted, outside refused, nothing changed.

One server for the whole module: every test starts from the settings it reads and sets only the
field it is about, so the order does not matter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.clients import json_of
from tests.e2e.support.http_a_settings import SETTINGS_PATH, get_settings, put_settings

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


#: (field, lowest accepted, highest accepted): the documented ranges of API.md section 2.4.
RANGES = [
    ("max_links", 100, 5_000_000),
    ("max_drawn_links", 50, 20_000),
    ("max_upload_mb", 1, 100),
    ("mongo_timeout_ms", 500, 300_000),
]


@pytest.mark.parametrize(("field", "low", "high"), RANGES)
def test_the_edges_of_every_range_are_accepted(
    api: httpx.Client, field: str, low: int, high: int
) -> None:
    for value in (low, high):
        saved = put_settings(api, {**get_settings(api), field: value})
        assert saved["settings"][field] == value
        assert get_settings(api)[field] == value


def _outside(field: str, value: int) -> tuple[dict[str, Any], str]:
    return {field: value}, f"body.{field}"


REFUSED = [
    pytest.param(*_outside("max_links", 99), id="max_links-below"),
    pytest.param(*_outside("max_links", 5_000_001), id="max_links-above"),
    pytest.param(*_outside("max_drawn_links", 49), id="max_drawn_links-below"),
    pytest.param(*_outside("max_drawn_links", 20_001), id="max_drawn_links-above"),
    pytest.param(*_outside("max_upload_mb", 0), id="max_upload_mb-below"),
    pytest.param(*_outside("max_upload_mb", 101), id="max_upload_mb-above"),
    pytest.param(*_outside("mongo_timeout_ms", 499), id="mongo_timeout_ms-below"),
    pytest.param(*_outside("mongo_timeout_ms", 300_001), id="mongo_timeout_ms-above"),
    pytest.param({"theme": "purple"}, "body.theme", id="theme"),
    pytest.param({"storage_backend": "ftp"}, "body.storage_backend", id="backend"),
    pytest.param({"bogus": 1}, "body.bogus: Extra inputs are not permitted", id="unknown-field"),
    pytest.param({"max_links": "many"}, "body.max_links", id="wrong-type"),
]


@pytest.mark.parametrize(("change", "detail"), REFUSED)
def test_a_value_outside_its_range_is_refused_and_changes_nothing(
    api: httpx.Client, change: dict[str, Any], detail: str
) -> None:
    before = get_settings(api)
    refused = api.put(SETTINGS_PATH, json={**before, **change})
    error = json_of(refused, 422)["error"]
    assert error["code"] == "validation_error"
    assert any(line.startswith(detail) for line in error["details"]), error["details"]
    assert get_settings(api) == before


def test_a_body_that_is_not_json_is_a_clean_422(api: httpx.Client) -> None:
    refused = api.put(SETTINGS_PATH, content=b"{nope", headers={"Content-Type": "application/json"})
    assert json_of(refused, 422)["error"]["details"] == ["body.1: JSON decode error"]


def test_a_non_json_content_type_is_refused_with_415(api: httpx.Client) -> None:
    refused = api.put(
        SETTINGS_PATH, content=b"max_links=500", headers={"Content-Type": "text/plain"}
    )
    assert json_of(refused, 415)["error"]["code"] == "unsupported_media_type"
