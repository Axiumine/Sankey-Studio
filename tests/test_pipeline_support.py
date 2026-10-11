"""Helpers shared by ``tests/test_pipeline*.py`` and ``tests/test_bundle*.py`` (no tests here)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sankey_studio import pipeline
from sankey_studio.config import BootstrapConfig
from sankey_studio.models import (
    AppSettings,
    GraphDraft,
    Link,
    ManualSource,
    MongoSource,
    StyleSpec,
    TextSource,
    TransformSpec,
)
from sankey_studio.services import Services
from sankey_studio.sources import open_source
from sankey_studio.storage import dump_settings, load_settings
from tests.conftest import build_connection

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import pytest
    from pymongo import MongoClient

    from sankey_studio.models import SankeyGraph

CSV = "source,target,value\na,b,10\nb,c,4\n"
HOUR_NS = 3_600_000_000_000


@dataclass(slots=True)
class PipelineEnv:
    """``Services`` over an isolated data dir and an in-memory MongoDB (connection ``test``)."""

    services: Services
    config: BootstrapConfig
    mongo: MongoClient[Any]

    @property
    def sources_dir(self) -> Path:
        return self.config.effective_sources_dir

    def change_settings(self, **fields: Any) -> AppSettings:
        """Save the current settings with ``fields`` replaced (real URIs kept) and return them."""
        doc = {**dump_settings(self.services.settings()), **fields}
        return self.services.update_settings(load_settings(doc)).settings


@contextmanager
def make_env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    config = BootstrapConfig(data_dir=tmp_path / "data")
    services = Services.create(config, mongo_factory=lambda _uri, _timeout: mongo_client)
    services.update_settings(AppSettings(mongo_connections=[build_connection()]))
    try:
        yield PipelineEnv(services, config, mongo_client)
    finally:
        services.close()


def manual_draft(
    *links: tuple[str, str, float, str | None], style: StyleSpec | None = None, **transform: Any
) -> GraphDraft:
    """A manual-source draft from ``(source, target, value, category)`` tuples."""
    return GraphDraft(
        source=ManualSource(
            links=[Link(source=s, target=t, value=v, category=c) for s, t, v, c in links]
        ),
        transform=TransformSpec.model_validate(transform),
        style=style or StyleSpec(),
    )


def csv_draft(text: str = CSV, **transform: Any) -> GraphDraft:
    return GraphDraft(
        source=TextSource(content=text),
        transform=TransformSpec.model_validate(transform),
    )


def file_draft(path: str = "flows.csv", **transform: Any) -> GraphDraft:
    return GraphDraft(
        source=TextSource(origin="file", path=path),
        transform=TransformSpec.model_validate(transform),
    )


def mongo_draft(**fields: Any) -> GraphDraft:
    """A find-mode draft on ``flows.links`` of the connection ``test``."""
    spec = {"connection": "test", "database": "flows", "collection": "links", **fields}
    return GraphDraft(source=MongoSource.model_validate(spec))


@dataclass(slots=True)
class Loads:
    """How many times a source was opened (a cache hit opens none)."""

    count: int = 0


def count_loads(monkeypatch: pytest.MonkeyPatch) -> Loads:
    loads = Loads()
    real = open_source

    def counted(*args: Any) -> Any:
        loads.count += 1
        return real(*args)

    monkeypatch.setattr(pipeline, "open_source", counted)
    return loads


@dataclass(slots=True)
class FakeClock:
    """A settable monotonic clock for ``ResultCache(clock=...)``."""

    now: float = 1000.0

    def __call__(self) -> float:
        return self.now


class RecordingCache:
    """A dict-backed ``GraphCache`` that remembers every call (the app's cache, as a fake)."""

    def __init__(self) -> None:
        self.items: dict[str, SankeyGraph] = {}
        self.gets: list[str] = []
        self.puts: list[tuple[str, float]] = []

    def get(self, key: str, /) -> SankeyGraph | None:
        self.gets.append(key)
        return self.items.get(key)

    def put(self, key: str, value: SankeyGraph, ttl_s: float, /) -> None:
        self.puts.append((key, ttl_s))
        self.items[key] = value


def age_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the wall clock of the pipeline run an hour ahead: files written so far look old.

    A file touched in the last two seconds is never cached (``RACY_WINDOW_NS``), so every test
    that expects a file to be served from the cache starts here.
    """
    monkeypatch.setattr(pipeline, "_wall_ns", lambda: time.time_ns() + HOUR_NS)
