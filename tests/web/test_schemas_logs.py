# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""A settings round trip leaves no secret in the logs (SPEC section 4: bodies and logs)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from sankey_studio.models import AppSettings
from sankey_studio.web.deps import ConfigDep, ServicesDep, require_writes
from sankey_studio.web.schemas import (
    SettingsIn,
    SettingsOut,
    SettingsSaved,
    merge_settings,
    settings_out,
    settings_saved,
)
from tests.conftest import build_connection

if TYPE_CHECKING:
    import pytest

    from tests.web.conftest import AppFactory

PATH = "/api/v1/settings"
PASSWORD = "hunter2"
HOST = "alpha.invalid"
ALPHA = f"mongodb://tester:{PASSWORD}@{HOST}:27017/?appName=tests"

router = APIRouter(prefix="/api/v1")


@router.get("/settings")
def get_settings(services: ServicesDep, config: ConfigDep) -> SettingsOut:
    return settings_out(services.settings(), config)


@router.put("/settings", dependencies=[Depends(require_writes)])
def put_settings(body: SettingsIn, services: ServicesDep, config: ConfigDep) -> SettingsSaved:
    return settings_saved(
        services.update_settings(merge_settings(services.settings(), body)), config
    )


def test_get_and_put_log_neither_the_password_nor_the_host(
    make_app: AppFactory, caplog: pytest.LogCaptureFixture
) -> None:
    settings = AppSettings(mongo_connections=[build_connection("alpha", ALPHA, "flows")])
    web = make_app([router], settings=settings)
    caplog.set_level(logging.DEBUG)
    answer = web.client.get(PATH)
    assert answer.status_code == 200
    body: dict[str, Any] = answer.json()
    assert web.client.put(PATH, json=body).status_code == 200
    renamed = {**body, "mongo_connections": [{**body["mongo_connections"][0], "name": "beta"}]}
    renamed["mongo_connections"][0]["previous_name"] = "alpha"
    assert web.client.put(PATH, json=renamed).status_code == 200
    assert caplog.text != ""
    assert PASSWORD not in caplog.text
    assert HOST not in caplog.text


def test_refused_requests_log_no_secret_either(
    make_app: AppFactory, caplog: pytest.LogCaptureFixture
) -> None:
    settings = AppSettings(mongo_connections=[build_connection("alpha", ALPHA, "flows")])
    web = make_app([router], settings=settings)
    caplog.set_level(logging.DEBUG)
    bad_uri = f"mongodb://tester:{PASSWORD}@{HOST}/?tlsInsecure=true"
    refused = {"mongo_connections": [{"name": "alpha", "uri": bad_uri}]}
    assert web.client.put(PATH, json=refused).status_code == 422
    nameless = {"mongo_connections": [{"name": "gamma", "uri": 5}]}
    assert web.client.put(PATH, json=nameless).status_code == 422
    assert web.client.put(PATH, json={"mongo_connections": [{"name": "gamma"}]}).status_code == 422
    assert PASSWORD not in caplog.text
    assert HOST not in caplog.text
