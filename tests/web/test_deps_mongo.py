# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``MongoContextDep``: a ``SourceContext`` that never needs (or creates) the sources directory."""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

import pytest
from fastapi import APIRouter

from sankey_studio.models import AppSettings
from sankey_studio.sources.base import SourceContext
from sankey_studio.web.deps import MongoContextDep, get_mongo_context
from tests.web.test_routes_sources_support import block_sources_dir

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory

router = APIRouter()
seen: list[SourceContext] = []


@router.get("/api/v1/probe/mongo-context")
def _context(ctx: MongoContextDep) -> dict[str, bool]:
    seen.append(ctx)
    return {"ok": True}


@pytest.fixture(autouse=True)
def _nothing_seen() -> None:
    seen.clear()


def test_the_alias_is_the_dependency_function() -> None:
    assert get_args(MongoContextDep)[1].dependency is get_mongo_context


def test_the_context_carries_the_live_settings_the_clients_and_the_configured_directory(
    make_app: AppFactory, app_settings: AppSettings
) -> None:
    web = make_app([router], settings=app_settings)
    assert web.client.get("/api/v1/probe/mongo-context").status_code == 200
    (ctx,) = seen
    assert isinstance(ctx, SourceContext)
    assert ctx.settings == app_settings
    assert ctx.mongo is web.services.mongo
    assert ctx.sources_dir == web.config.effective_sources_dir
    assert ctx.strict is False


def test_the_settings_are_read_on_every_request(
    make_app: AppFactory, app_settings: AppSettings
) -> None:
    web = make_app([router], settings=app_settings)
    web.client.get("/api/v1/probe/mongo-context")
    web.services.update_settings(AppSettings(theme="dark"))
    web.client.get("/api/v1/probe/mongo-context")
    assert [ctx.settings.theme for ctx in seen] == ["system", "dark"]


def test_the_directory_is_neither_created_nor_required(make_app: AppFactory) -> None:
    web = make_app([router])
    assert web.client.get("/api/v1/probe/mongo-context").status_code == 200
    assert not web.config.effective_sources_dir.exists()
    block_sources_dir(web.config)
    assert web.client.get("/api/v1/probe/mongo-context").status_code == 200
    assert seen[-1].sources_dir == web.config.effective_sources_dir
