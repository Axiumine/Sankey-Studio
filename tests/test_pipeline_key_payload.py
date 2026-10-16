# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``cache_key``: the exact bytes that are hashed (field names, compact JSON, stamps, no style)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio import pipeline
from sankey_studio.models import MongoSource, TextSource
from sankey_studio.pipeline import cache_key
from sankey_studio.util import mask_uri
from tests.conftest import TEST_URI
from tests.test_pipeline_support import (
    CSV,
    PipelineEnv,
    age_files,
    csv_draft,
    file_draft,
    make_env,
    manual_draft,
    mongo_draft,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import GraphDraft


class HashSpy:
    """Stands in for ``hashlib`` inside ``pipeline``: remembers what was hashed, hashes it."""

    def __init__(self) -> None:
        self.seen: list[bytes] = []

    def sha256(self, data: bytes) -> Any:
        self.seen.append(data)
        return hashlib.sha256(data)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> HashSpy:
    spy = HashSpy()
    monkeypatch.setattr(pipeline, "hashlib", SimpleNamespace(sha256=spy.sha256))
    return spy


@pytest.fixture
def env(
    tmp_path: Path, mongo_client: MongoClient[Any], monkeypatch: pytest.MonkeyPatch
) -> Iterator[PipelineEnv]:
    age_files(monkeypatch)
    with make_env(tmp_path, mongo_client) as value:
        yield value


def payload_of(
    env: PipelineEnv, spy: HashSpy, draft: GraphDraft, *, hashes: int = 1
) -> dict[str, Any]:
    """The JSON object behind ``cache_key(draft)``; checks the key is the digest of those bytes.

    ``hashes`` is how many digests the call computes (a Mongo stamp digests its secret first); the
    payload is always the last one.
    """
    key = cache_key(draft, env.services.source_context())
    assert key is not None
    assert len(spy.seen) == hashes
    raw = spy.seen[-1]
    assert key == hashlib.sha256(raw).hexdigest()
    payload: dict[str, Any] = json.loads(raw)
    assert raw == json.dumps(payload, separators=(",", ":")).encode("ascii")
    return payload


def test_the_payload_is_source_transform_row_cap_and_stamp_and_never_the_style(
    env: PipelineEnv, spy: HashSpy
) -> None:
    draft = csv_draft(top_links=5)
    payload = payload_of(env, spy, draft)
    assert sorted(payload) == ["max_links", "source", "stamp", "transform"]
    assert payload["source"] == draft.source.model_dump(mode="json", exclude={"write_back"})
    assert "write_back" not in payload["source"]  # a consent preference is not data
    assert payload["transform"] == draft.transform.model_dump(mode="json")
    assert payload["max_links"] == env.services.settings().max_links
    assert payload["stamp"] == {}


def test_the_source_keeps_its_default_fields_in_the_payload(env: PipelineEnv, spy: HashSpy) -> None:
    source = payload_of(env, spy, csv_draft())["source"]
    assert source["type"] == "text"
    assert source["origin"] == "inline"
    assert source["content"] == CSV
    assert source["path"] is None


def test_a_value_that_only_json_mode_can_write_still_has_a_key(
    env: PipelineEnv, spy: HashSpy
) -> None:
    when = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    draft = mongo_draft(filter={"when": when})
    payload = payload_of(env, spy, draft, hashes=2)
    assert payload["source"]["filter"] == {"when": "2020-01-02T03:04:05Z"}


def test_a_file_is_stamped_with_its_inode_size_and_times(env: PipelineEnv, spy: HashSpy) -> None:
    env.sources_dir.mkdir(parents=True, exist_ok=True)
    path = env.sources_dir / "flows.csv"
    path.write_text(CSV)
    info = path.lstat()
    assert payload_of(env, spy, file_draft())["stamp"] == {
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def test_a_mongo_source_is_stamped_with_the_masked_uri_secret_digest_database_and_timeout(
    env: PipelineEnv, spy: HashSpy
) -> None:
    payload = payload_of(env, spy, mongo_draft(), hashes=2)
    assert payload["stamp"] == {
        "uri": mask_uri(TEST_URI),
        "secret_sha256": hashlib.sha256(TEST_URI.encode()).hexdigest(),
        "database": "flows",
        "timeout_ms": env.services.settings().mongo_timeout_ms,
    }
    assert spy.seen[0] == TEST_URI.encode()  # the digest is of the whole secret URI ...
    assert b"hunter2" not in spy.seen[-1]  # ... and only the digest reaches the payload


def test_a_mongo_source_of_an_unknown_connection_has_an_empty_stamp(
    env: PipelineEnv, spy: HashSpy
) -> None:
    assert payload_of(env, spy, mongo_draft(connection="ghost"))["stamp"] == {}


def test_a_manual_source_has_an_empty_stamp(env: PipelineEnv, spy: HashSpy) -> None:
    assert payload_of(env, spy, manual_draft(("a", "b", 1, None)))["stamp"] == {}


def test_the_payload_is_ascii_even_for_non_latin_text(env: PipelineEnv, spy: HashSpy) -> None:
    payload_of(env, spy, csv_draft("source,target,value\né,中,1\n"))
    assert spy.seen[0].isascii()
    assert b"\\u00e9" in spy.seen[0]


def test_a_file_source_without_a_path_is_not_cacheable(env: PipelineEnv) -> None:
    source = TextSource.model_construct(origin="file", path=None)
    assert pipeline._stamp(source, env.services.source_context()) is None


def test_the_mongo_stamp_is_empty_for_a_connection_that_does_not_exist(env: PipelineEnv) -> None:
    source = MongoSource(connection="ghost", database="flows", collection="links")
    assert pipeline._mongo_stamp(source, env.services.source_context()) == {}
