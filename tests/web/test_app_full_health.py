# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``GET /api/v1/health``: a liveness answer that never touches storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.web.routers import pages

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, Mode, WebApp

PATH = "/api/v1/health"


def test_health_is_ok_with_the_api_headers(web: WebApp) -> None:
    response = web.client.get(PATH)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("mode", ["local", "remote_read_only", "remote_writes"])
def test_health_is_available_in_every_mode(make_app: AppFactory, mode: Mode) -> None:
    assert make_app(mode=mode).client.get(PATH).json() == {"status": "ok"}


def test_health_works_without_any_data_on_disk(web: WebApp) -> None:
    assert not web.config.graphs_dir.exists()
    assert web.client.get(PATH).status_code == 200
    assert not web.config.graphs_dir.exists()


def test_health_is_get_only_and_refuses_cross_site_reads(web: WebApp) -> None:
    posted = web.client.post(PATH, json={})
    cross = web.bare.get(PATH, headers={"Sec-Fetch-Site": "cross-site"})
    assert (posted.status_code, posted.json()["error"]["code"]) == (405, "method_not_allowed")
    assert (cross.status_code, cross.json()["error"]["code"]) == (403, "forbidden")


def test_the_health_model_only_ever_says_ok() -> None:
    assert pages.HealthOut().model_dump() == {"status": "ok"}
    assert pages.health() == pages.HealthOut(status="ok")
