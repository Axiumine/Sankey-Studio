"""The cache key of a Mongo source follows the SECRET connection string, not just its masked form.

A credential rotation that only changes the password leaves ``mask_uri`` (and so the old stamp)
untouched: a graph loaded with the old credentials must not be served from the cache afterwards.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio import pipeline
from sankey_studio.models import MongoSource
from sankey_studio.pipeline import build_graph_from_draft, cache_for, cache_key
from sankey_studio.util import mask_uri
from tests.conftest import TEST_URI
from tests.test_pipeline_support import PipelineEnv, count_loads, make_env, mongo_draft

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import GraphDraft

ROTATED = TEST_URI.replace("hunter2", "rotated-pw")
SAME_LENGTH = TEST_URI.replace("hunter2", "hunter3")
ROTATIONS = pytest.mark.parametrize(
    "rotated",
    [
        ROTATED,
        SAME_LENGTH,
        TEST_URI.replace("hunter2", "h%40nter2"),
        TEST_URI.replace("hunter2", ""),
    ],
    ids=["new password", "same length", "percent-encoded", "empty password"],
)
SOURCE = MongoSource(connection="test", database="flows", collection="links")
SECOND = "mongodb://other:s3cret@second.invalid:27017/?appName=tests"
SECOND_ROTATED = SECOND.replace("s3cret", "n3w-s3cret")


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    with make_env(tmp_path, mongo_client) as value:
        yield value


def connections(*extra: tuple[str, str], uri: str = TEST_URI) -> list[dict[str, Any]]:
    """The ``mongo_connections`` document: ``test`` (with ``uri``) plus the ``extra`` ones."""
    named = [("test", uri), *extra]
    return [{"name": name, "uri": value, "default_database": "flows"} for name, value in named]


def key_of(env: PipelineEnv, draft: GraphDraft | None = None) -> str:
    key = cache_key(draft or mongo_draft(), env.services.source_context())
    assert key is not None
    return key


def seed(env: PipelineEnv) -> None:
    env.mongo["flows"]["links"].insert_one({"source": "a", "target": "b", "value": 1})


# --------------------------------------------------------------------------- the masked form


@ROTATIONS
def test_the_masked_uri_cannot_tell_these_credentials_apart(rotated: str) -> None:
    """Why the digest is needed: every rotation below masks to the very same string."""
    assert mask_uri(rotated) == mask_uri(TEST_URI)


# --------------------------------------------------------------------------- rotating the password


@ROTATIONS
def test_rotating_only_the_password_changes_the_key(env: PipelineEnv, rotated: str) -> None:
    before = key_of(env)
    env.change_settings(mongo_connections=connections(uri=rotated))
    assert key_of(env) != before


def test_rotating_the_password_back_restores_the_key(env: PipelineEnv) -> None:
    before = key_of(env)
    env.change_settings(mongo_connections=connections(uri=ROTATED))
    env.change_settings(mongo_connections=connections(uri=TEST_URI))
    assert key_of(env) == before


@pytest.mark.parametrize(
    "other",
    [
        TEST_URI.replace("tester", "other"),
        TEST_URI.replace("mongo.invalid", "elsewhere.invalid"),
        TEST_URI.replace("appName=tests", "appName=other"),
    ],
    ids=["user", "host", "option"],
)
def test_any_other_part_of_the_uri_still_changes_the_key(env: PipelineEnv, other: str) -> None:
    before = key_of(env)
    env.change_settings(mongo_connections=connections(uri=other))
    assert key_of(env) != before


def test_the_default_database_and_the_timeout_still_change_the_key(env: PipelineEnv) -> None:
    before = key_of(env)
    env.change_settings(mongo_timeout_ms=20_000)
    after_timeout = key_of(env)
    assert after_timeout != before
    renamed = [{**connections()[0], "default_database": "second"}]
    env.change_settings(mongo_connections=renamed)
    assert key_of(env) not in {before, after_timeout}


# --------------------------------------------------------------------------- what must not move it


def test_the_same_credentials_save_again_keep_the_key(env: PipelineEnv) -> None:
    before = key_of(env)
    env.change_settings(mongo_connections=connections())
    assert key_of(env) == before


@pytest.mark.parametrize(
    "fields",
    [
        {"theme": "dark"},
        {"max_upload_mb": 7},
        {"max_drawn_links": 777},
        {"storage_database": "elsewhere"},
        {"default_style": {"title": "Mine", "orientation": "v"}},
    ],
    ids=["theme", "upload cap", "drawn links cap", "storage database", "default style"],
)
def test_a_change_of_unrelated_settings_keeps_the_key(
    env: PipelineEnv, fields: dict[str, Any]
) -> None:
    before = key_of(env)
    env.change_settings(**fields)
    assert key_of(env) == before


def test_rotating_the_password_of_another_connection_keeps_the_key(env: PipelineEnv) -> None:
    env.change_settings(mongo_connections=connections(("second", SECOND)))
    before = key_of(env)
    env.change_settings(mongo_connections=connections(("second", SECOND_ROTATED)))
    assert key_of(env) == before
    assert key_of(env, mongo_draft(connection="second")) != key_of(
        env, mongo_draft(connection="test")
    )


def test_the_key_of_another_connection_follows_its_own_password(env: PipelineEnv) -> None:
    env.change_settings(mongo_connections=connections(("second", SECOND)))
    before = key_of(env, mongo_draft(connection="second"))
    env.change_settings(mongo_connections=connections(("second", SECOND_ROTATED)))
    assert key_of(env, mongo_draft(connection="second")) != before


# --------------------------------------------------------------------------- the stamp itself


def test_the_stamp_holds_a_digest_and_never_the_secret(env: PipelineEnv) -> None:
    context = env.services.source_context()
    stamp = pipeline._mongo_stamp(SOURCE, context)
    assert set(stamp) == {"uri", "secret_sha256", "database", "timeout_ms"}
    assert re.fullmatch(r"[0-9a-f]{64}", stamp["secret_sha256"])
    assert "hunter2" not in repr(stamp)
    assert stamp["uri"] == mask_uri(TEST_URI)


def test_the_digest_is_stable_and_differs_per_secret(env: PipelineEnv) -> None:
    first = pipeline._mongo_stamp(SOURCE, env.services.source_context())
    again = pipeline._mongo_stamp(SOURCE, env.services.source_context())
    assert first == again
    env.change_settings(mongo_connections=connections(uri=ROTATED))
    rotated = pipeline._mongo_stamp(SOURCE, env.services.source_context())
    assert rotated["secret_sha256"] != first["secret_sha256"]
    assert rotated["uri"] == first["uri"]


# --------------------------------------------------------------------------- the cache end to end


def test_a_graph_loaded_with_the_old_credentials_is_not_served_after_a_rotation(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(env)
    loads = count_loads(monkeypatch)
    first = build_graph_from_draft(env.services, mongo_draft())
    assert build_graph_from_draft(env.services, mongo_draft()) is first
    assert loads.count == 1
    env.change_settings(mongo_connections=connections(uri=ROTATED))
    after = build_graph_from_draft(env.services, mongo_draft())
    assert after is not first
    assert loads.count == 2
    assert cache_for(env.services).size == 2


def test_unrelated_settings_do_not_cost_a_reload(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(env)
    loads = count_loads(monkeypatch)
    first = build_graph_from_draft(env.services, mongo_draft())
    env.change_settings(theme="dark", max_upload_mb=7)
    assert build_graph_from_draft(env.services, mongo_draft()) is first
    assert loads.count == 1
