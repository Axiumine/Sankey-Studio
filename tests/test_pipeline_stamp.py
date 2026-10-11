"""The stamp of a file source: what moves the cache key, and when a file is too fresh to cache."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

import pytest

from sankey_studio import pipeline
from sankey_studio.pipeline import RACY_WINDOW_NS, build_graph_from_draft, cache_for, cache_key
from tests.graph_support import rows
from tests.test_pipeline_support import (
    CSV,
    PipelineEnv,
    count_loads,
    file_draft,
    make_env,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

SEC = 1_000_000_000
OLD = 10 * SEC
NOW = 1000 * SEC


@dataclass(frozen=True, slots=True)
class StatPath:
    """What ``resolve_source_path`` returns, reduced to the one call the stamp makes."""

    st_ino: int = 7
    st_size: int = 100
    st_mtime_ns: int = OLD
    st_ctime_ns: int = OLD

    def lstat(self) -> StatPath:
        return self


class Keyer(Protocol):
    """``keyer(path)`` is the cache key; ``now_ns`` is what the wall clock reads."""

    def __call__(self, path: StatPath, now_ns: int = NOW, /) -> str | None: ...


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    with make_env(tmp_path, mongo_client) as value:
        yield value


@pytest.fixture
def keyer(env: PipelineEnv, monkeypatch: pytest.MonkeyPatch) -> Keyer:
    """The cache key of a file draft whose stat is ``path`` when the wall clock reads ``now_ns``."""

    def key(path: StatPath, now_ns: int = NOW) -> str | None:
        monkeypatch.setattr(pipeline, "resolve_source_path", lambda _root, _rel: path)
        monkeypatch.setattr(pipeline, "_wall_ns", lambda: now_ns)
        return cache_key(file_draft(), env.services.source_context())

    return key


# --------------------------------------------------------------------------- the stamp


def test_the_same_stat_is_the_same_key(keyer: Keyer) -> None:
    first = keyer(StatPath())
    assert first is not None
    assert keyer(StatPath()) == first


@pytest.mark.parametrize("field", ["st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"])
def test_every_part_of_the_stat_moves_the_key(keyer: Keyer, field: str) -> None:
    base = StatPath()
    other = replace(base, **{field: getattr(base, field) + 1})
    assert keyer(base) is not None
    assert keyer(other) is not None
    assert keyer(other) != keyer(base)


def test_the_window_is_two_seconds() -> None:
    assert RACY_WINDOW_NS == 2 * SEC


def test_the_wall_clock_seam_reads_the_wall_clock() -> None:
    assert abs(pipeline._wall_ns() - time.time_ns()) < SEC


@pytest.mark.parametrize("recent", ["st_mtime_ns", "st_ctime_ns"])
@pytest.mark.parametrize(
    ("age_ns", "cacheable"),
    [
        (RACY_WINDOW_NS + SEC, True),
        (RACY_WINDOW_NS, True),
        (RACY_WINDOW_NS - 1, False),
        (0, False),
        (-SEC, False),
    ],
    ids=["old", "exactly the window", "a tick short", "just now", "in the future"],
)
def test_a_file_touched_within_two_seconds_is_not_cached(
    keyer: Keyer, recent: str, age_ns: int, cacheable: bool
) -> None:
    path = replace(StatPath(), **{recent: NOW - age_ns})
    assert (keyer(path) is not None) is cacheable


# --------------------------------------------------------------------------- real files


def write_flows(env: PipelineEnv, text: str) -> Path:
    env.sources_dir.mkdir(parents=True, exist_ok=True)
    path = env.sources_dir / "flows.csv"
    path.write_text(text)
    return path


def test_a_file_written_just_now_is_loaded_every_time(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_flows(env, CSV)
    loads = count_loads(monkeypatch)
    first = build_graph_from_draft(env.services, file_draft())
    second = build_graph_from_draft(env.services, file_draft())
    assert second is not first
    assert loads.count == 2
    assert cache_for(env.services).size == 0


def test_a_same_size_rewrite_right_after_a_load_is_seen(env: PipelineEnv) -> None:
    path = write_flows(env, CSV)
    build_graph_from_draft(env.services, file_draft())
    path.write_text(CSV.replace("a,b", "x,b"))  # same size, most likely the same mtime tick
    graph = build_graph_from_draft(env.services, file_draft())
    assert rows(graph)[0] == ("x", "b", 10.0, None)


def test_the_same_file_is_cached_once_it_is_two_seconds_old(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_flows(env, CSV)
    monkeypatch.setattr(pipeline, "_wall_ns", lambda: time.time_ns() + 3 * SEC)
    loads = count_loads(monkeypatch)
    first = build_graph_from_draft(env.services, file_draft())
    assert build_graph_from_draft(env.services, file_draft()) is first
    assert loads.count == 1


def test_a_file_replaced_by_one_of_the_same_size_and_mtime_is_loaded_again(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_flows(env, CSV)
    stat = path.stat()
    monkeypatch.setattr(pipeline, "_wall_ns", lambda: time.time_ns() + 3600 * SEC)
    first = build_graph_from_draft(env.services, file_draft())
    other = path.with_name("other.tmp")
    other.write_text(CSV.replace("a,b", "x,b"))
    os.utime(other, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    other.replace(path)  # a new inode with the old size and the old mtime
    graph = build_graph_from_draft(env.services, file_draft())
    assert graph is not first
    assert rows(graph)[0] == ("x", "b", 10.0, None)
