"""Builders and fakes shared by the storage tests (not a test module)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from sankey_studio.config import BootstrapConfig
from sankey_studio.models import (
    AppSettings,
    GraphCreate,
    GraphDefinition,
    GraphUpdate,
    Link,
    ManualSource,
    MongoConnection,
    MongoSource,
    StyleSpec,
    TransformSpec,
)
from sankey_studio.storage.files.codec import read_graph

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    import pytest

NOW = datetime(2025, 5, 1, 12, 0, 0, tzinfo=UTC)
#: Valid ids with a known sort order.
ID_A, ID_B, ID_C, ID_D = ("a" * 32, "b" * 32, "c" * 32, "d" * 32)
#: Keys a user can type that MongoDB < 5.0 refuses as field names.
NASTY_KEYS = ("a.b", "$x", "R&D.net", "$", "x.", ".y", "$where")


class Ticker:
    """A deterministic clock: every call returns the next instant (``step`` apart)."""

    def __init__(self, start: datetime = NOW, step: timedelta = timedelta(seconds=1)) -> None:
        self.now = start
        self.step = step
        self.calls = 0

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        self.calls += 1
        return current


@dataclass(slots=True)
class Spec:
    """Optional fields of a test graph (``revision``/``updated_at``: stored graphs only)."""

    description: str = ""
    tags: Sequence[str] = field(default_factory=tuple)
    links: int = 1
    revision: int = 1
    updated_at: datetime = NOW


def manual_source(links: int = 1) -> ManualSource:
    return ManualSource(
        links=[Link(source=f"s{i}", target=f"t{i}", value=float(i + 1)) for i in range(links)]
    )


def create_data(name: str = "graph", spec: Spec | None = None) -> GraphCreate:
    spec = spec or Spec()
    return GraphCreate(
        name=name,
        description=spec.description,
        tags=list(spec.tags),
        source=manual_source(spec.links),
    )


def update_data(revision: int, name: str = "graph", spec: Spec | None = None) -> GraphUpdate:
    spec = spec or Spec()
    return GraphUpdate(
        name=name,
        description=spec.description,
        tags=list(spec.tags),
        source=manual_source(spec.links),
        revision=revision,
    )


def definition(
    graph_id: str = ID_A, name: str = "graph", spec: Spec | None = None
) -> GraphDefinition:
    """A stored graph with the given id and timestamps (for ``put`` and for raw documents)."""
    spec = spec or Spec()
    return GraphDefinition(
        id=graph_id,
        name=name,
        description=spec.description,
        tags=list(spec.tags),
        source=manual_source(spec.links),
        revision=spec.revision,
        created_at=NOW,
        updated_at=spec.updated_at,
    )


def nasty_create(*, mongo: bool = False) -> GraphCreate:
    """A graph whose dict keys are all unsafe for MongoDB < 5.0."""
    source: ManualSource | MongoSource = manual_source()
    if mongo:
        source = MongoSource(
            connection="c",
            collection="flows",
            filter={"amount": {"$gt": 5}, "meta.flow": {"$in": ["a", "b"]}, "$or": [{"x.y": 1}]},
            pipeline=[{"$match": {"meta.year": 2025}}],
        )
    return GraphCreate(
        name="nasty",
        source=source,
        transform=TransformSpec(merge_nodes={key: f"{key}2" for key in NASTY_KEYS}),
        style=StyleSpec(
            node_colors=dict.fromkeys(NASTY_KEYS, "#112233"),
            category_colors=dict.fromkeys(NASTY_KEYS, "#445566"),
        ),
    )


@contextmanager
def umask(value: int) -> Iterator[None]:
    """Run a block under another process umask (restored afterwards)."""
    previous = os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


def mode_of(path: Path) -> int:
    """Permission bits of ``path`` (without the file type)."""
    return path.stat().st_mode & 0o7777


class Reads:
    """Counts the graph files the directory index parses (``index.read_graph`` calls)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.paths: list[str] = []
        original = read_graph

        def counting(path: Path) -> GraphDefinition:
            self.paths.append(path.name)
            return original(path)

        monkeypatch.setattr("sankey_studio.storage.files.index.read_graph", counting)


SECRET_URI = "mongodb://tester:hunter2@mongo.invalid:27017/?appName=tests"
OTHER_URI = "mongodb://reader:s3cret-pass@other.invalid:27018/?replicaSet=rs0"


def config_for(root: Any, seed: str | None = None) -> BootstrapConfig:
    """A bootstrap config whose data dir is ``root/data`` (optionally seeding SANKEY_MONGO_URI)."""
    return BootstrapConfig(
        data_dir=root / "data", mongo_uri=None if seed is None else SecretStr(seed)
    )


def settings_with(*connections: tuple[str, str], **fields: Any) -> AppSettings:
    """``AppSettings`` holding ``(name, uri)`` connections (plain strings for the URIs)."""
    return AppSettings(
        mongo_connections=[
            MongoConnection(name=name, uri=SecretStr(uri)) for name, uri in connections
        ],
        **fields,
    )


def placeholder_settings() -> AppSettings:
    """Settings holding a masked secret, built around validation as a buggy caller could."""
    masked = MongoConnection.model_construct(
        name="a", uri=SecretStr("**********"), default_database=None
    )
    return AppSettings.model_construct(mongo_connections=[masked])
