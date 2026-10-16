# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Fixtures for the MongoDB source tests (``mongo_`` prefix; the TEXT tests use ``text_``).

Everything runs on mongomock or on the fakes of ``test_mongo_fakes``: no real server, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import pytest

from sankey_studio.models import AppSettings, MongoSource
from sankey_studio.sources import open_source
from sankey_studio.sources.base import Diagnostics
from tests.sources.test_mongo_fakes import fake_ctx

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import RawLink
    from sankey_studio.sources.base import SourceContext
    from tests.sources.test_mongo_fakes import FakeMongo


@dataclass(frozen=True, slots=True)
class MongoResult:
    """What one source run produced."""

    rows: list[RawLink]
    diag: Diagnostics


class MongoRunner(Protocol):
    def __call__(self, spec: MongoSource, *, strict: bool = False) -> MongoResult: ...


class FakeRunner(Protocol):
    def __call__(self, fake: FakeMongo, spec: MongoSource, *, strict: bool = False) -> MongoResult:
        """Run ``spec`` against a fake client instead of mongomock."""
        ...


class FakeCtxFactory(Protocol):
    def __call__(self, fake: FakeMongo, *, strict: bool = False) -> SourceContext:
        """A context whose Mongo clients always hand out ``fake``."""
        ...


class SpecFactory(Protocol):
    def __call__(self, **fields: Any) -> MongoSource: ...


@pytest.fixture
def mongo_spec() -> SpecFactory:
    """``MongoSource`` on collection ``events`` of connection ``test`` (default db ``flows``)."""

    def build(**fields: Any) -> MongoSource:
        return MongoSource.model_validate({"connection": "test", "collection": "events", **fields})

    return build


@pytest.fixture
def mongo_seed(mongo_client: MongoClient[Any]) -> Callable[[list[dict[str, Any]]], None]:
    """Insert documents into ``flows.events`` of the in-memory server."""

    def seed(docs: list[dict[str, Any]]) -> None:
        if docs:  # mongomock refuses an empty insert_many
            mongo_client["flows"]["events"].insert_many(docs)

    return seed


def _drain(spec: MongoSource, ctx: SourceContext) -> MongoResult:
    diag = Diagnostics()
    return MongoResult(rows=list(open_source(spec, ctx).iter_links(diag)), diag=diag)


@pytest.fixture
def mongo_run(make_source_ctx: Callable[..., SourceContext]) -> MongoRunner:
    """Run a spec against the mongomock server and collect rows plus diagnostics."""

    def run(spec: MongoSource, *, strict: bool = False) -> MongoResult:
        return _drain(spec, make_source_ctx(strict=strict))

    return run


@pytest.fixture
def mongo_capped_settings(app_settings: AppSettings) -> AppSettings:
    """Settings that allow at most 100 raw links (``max_links``)."""
    return AppSettings(mongo_connections=app_settings.mongo_connections, max_links=100)


@pytest.fixture
def mongo_capped_ctx(
    mongo_capped_settings: AppSettings, make_source_ctx: Callable[..., SourceContext]
) -> SourceContext:
    """A context whose settings allow at most 100 raw links (``max_links``)."""
    return make_source_ctx(settings=mongo_capped_settings)


@pytest.fixture
def mongo_fake_ctx(app_settings: AppSettings, tmp_path: Path) -> FakeCtxFactory:
    def build(fake: FakeMongo, *, strict: bool = False) -> SourceContext:
        return fake_ctx(fake, app_settings, tmp_path, strict=strict)

    return build


@pytest.fixture
def mongo_fake_run(mongo_fake_ctx: FakeCtxFactory) -> FakeRunner:
    """Run a spec against a ``FakeMongo`` (call recording, driver errors, closed cursors)."""

    def run(fake: FakeMongo, spec: MongoSource, *, strict: bool = False) -> MongoResult:
        return _drain(spec, mongo_fake_ctx(fake, strict=strict))

    return run
