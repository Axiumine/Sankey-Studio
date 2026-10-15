"""Shared fixtures. Tests never touch a real MongoDB: they use mongomock.

Autouse guards (every test): ``SANKEY_*`` environment variables are removed, so a developer's
``SANKEY_MONGO_URI`` can never seed a real connection; git's repository-local variables
(``GIT_DIR``, ``GIT_INDEX_FILE``...) are removed, so a run under a git hook never reaches the
real repository; and the pymongo client constructor is replaced by a tripwire, so no code path
can open a socket to a real server. Tests marked ``@pytest.mark.mongo`` (they run only with
``SANKEY_TEST_MONGO_URI``) are exempt from the first and the last.

Each agent may add a ``conftest.py`` only inside its own test sub-directory
(``tests/sources``, ``tests/storage``, ``tests/render``, ``tests/web``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Protocol

import mongomock
import pymongo.mongo_client
import pytest
from pydantic import SecretStr
from scripts.githook_git import FALLBACK_LOCAL_ENV

from sankey_studio.config import BootstrapConfig
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.mongo import MongoClients
from sankey_studio.sources.base import SourceContext

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pymongo import MongoClient

TEST_URI = "mongodb://tester:hunter2@mongo.invalid:27017/?appName=tests"
#: The one SANKEY_* variable tests may see (read only by ``@pytest.mark.mongo`` tests).
REAL_MONGO_ENV = "SANKEY_TEST_MONGO_URI"


@pytest.fixture(autouse=True)
def _scrub_sankey_env(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Remove SANKEY_* variables so ``BootstrapConfig()`` is hermetic."""
    is_real = request.node.get_closest_marker("mongo") is not None
    for name in [n for n in os.environ if n.startswith("SANKEY_")]:
        if is_real and name == REAL_MONGO_ENV:
            continue
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _scrub_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove git's repository-local variables (GIT_DIR, GIT_INDEX_FILE...).

    A test that runs under a git hook inherits them, and a ``git init`` or ``git add`` in a
    ``tmp_path`` would then act on the real repository. Variables such as ``GIT_CONFIG_GLOBAL``
    are not repository-local and stay.
    """
    for name in FALLBACK_LOCAL_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_real_mongo(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Fail loudly if anything constructs a real ``pymongo.MongoClient``."""
    if request.node.get_closest_marker("mongo") is not None:
        return

    def _refuse(*_args: Any, **_kwargs: Any) -> None:
        msg = "tests must not create a real MongoClient (use the mongomock fixtures)"
        raise AssertionError(msg)

    monkeypatch.setattr(pymongo.mongo_client.MongoClient, "__init__", _refuse)


@pytest.fixture
def bootstrap(tmp_path: Path) -> BootstrapConfig:
    """Config with an isolated data dir. ``allowed_hosts`` includes the TestClient host."""
    return BootstrapConfig(
        data_dir=tmp_path / "data",
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
    )


def build_connection(
    name: str = "test", uri: str = TEST_URI, default_database: str | None = "flows"
) -> MongoConnection:
    """A ``MongoConnection`` from a plain string URI.

    ``MongoConnection.uri`` is a ``SecretStr`` and mypy runs with ``pydantic.mypy`` ``init_typed``,
    so ``MongoConnection(uri="mongodb://...")`` is a type error. Write ``uri=SecretStr("...")`` or
    use this helper (the ``make_connection`` fixture) instead of a ``type: ignore``.
    """
    return MongoConnection(name=name, uri=SecretStr(uri), default_database=default_database)


class ConnectionFactory(Protocol):
    def __call__(
        self, name: str = ..., uri: str = ..., default_database: str | None = ...
    ) -> MongoConnection: ...


@pytest.fixture
def make_connection() -> ConnectionFactory:
    """Factory for ``MongoConnection`` objects from a plain string URI (``build_connection``)."""
    return build_connection


@pytest.fixture
def app_settings() -> AppSettings:
    """Settings with one mongomock-backed connection named ``test``."""
    return AppSettings(mongo_connections=[build_connection()])


@pytest.fixture
def mongo_client() -> MongoClient[Any]:
    """A fresh in-memory MongoDB shared by everything in one test."""
    return mongomock.MongoClient(tz_aware=True)


@pytest.fixture
def mongo_clients(app_settings: AppSettings, mongo_client: MongoClient[Any]) -> MongoClients:
    """``MongoClients`` that always hands out ``mongo_client`` (no network, ever)."""
    return MongoClients(lambda: app_settings, factory=lambda _uri, _timeout: mongo_client)


class SourceContextFactory(Protocol):
    def __call__(
        self,
        *,
        strict: bool = False,
        settings: AppSettings | None = None,
        sources_dir: Path | None = None,
    ) -> SourceContext: ...


@pytest.fixture
def make_source_ctx(
    app_settings: AppSettings, mongo_clients: MongoClients, tmp_path: Path
) -> SourceContextFactory:
    """Builder for ``SourceContext`` (sources dir defaults to an empty ``tmp_path/sources``)."""

    def build(
        *,
        strict: bool = False,
        settings: AppSettings | None = None,
        sources_dir: Path | None = None,
    ) -> SourceContext:
        root = sources_dir or tmp_path / "sources"
        root.mkdir(parents=True, exist_ok=True)
        return SourceContext(
            settings=settings or app_settings,
            sources_dir=root,
            mongo=mongo_clients,
            strict=strict,
        )

    return build


@pytest.fixture
def source_ctx(make_source_ctx: Callable[..., SourceContext]) -> SourceContext:
    """Default lenient context (mongomock Mongo, empty sources dir)."""
    return make_source_ctx()
