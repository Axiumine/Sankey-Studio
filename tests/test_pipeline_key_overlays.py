# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``cache_key``: what the overlays (extra links, categories, node order, consent) do to it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import pytest

from sankey_studio.models import GraphDraft, StyleSpec, TextSource, TransformSpec, WriteBackPref
from sankey_studio.pipeline import cache_key
from tests.test_pipeline_support import (
    CSV,
    PipelineEnv,
    age_files,
    file_draft,
    make_env,
    manual_draft,
    mongo_draft,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

EXTRA = {"source": "x", "target": "y", "value": 2}
PICK = {"source": "a", "target": "b", "category": "Fun"}


@pytest.fixture
def env(
    tmp_path: Path, mongo_client: MongoClient[Any], monkeypatch: pytest.MonkeyPatch
) -> Iterator[PipelineEnv]:
    age_files(monkeypatch)
    with make_env(tmp_path, mongo_client) as value:
        env_dir = value.sources_dir
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "flows.csv").write_text(CSV)
        yield value


def key_of(env: PipelineEnv, draft: GraphDraft) -> str:
    key = cache_key(draft, env.services.source_context())
    assert key is not None
    return key


def with_pref(draft: GraphDraft, mode: Literal["source", "graph"], target: str) -> GraphDraft:
    """``draft`` with a write-back preference on its (text or Mongo) source."""
    pref = WriteBackPref(mode=mode, target=target)
    source = draft.source.model_validate({**draft.source.model_dump(), "write_back": pref})
    return GraphDraft(source=source, transform=draft.transform, style=draft.style)


def with_style(draft: GraphDraft, **fields: Any) -> GraphDraft:
    style = StyleSpec.model_validate({**draft.style.model_dump(), **fields})
    return GraphDraft(source=draft.source, transform=draft.transform, style=style)


def with_transform(draft: GraphDraft, **fields: Any) -> GraphDraft:
    transform = TransformSpec.model_validate({**draft.transform.model_dump(), **fields})
    return GraphDraft(source=draft.source, transform=transform, style=draft.style)


@pytest.mark.parametrize("kind", ["file", "mongo"])
def test_the_consent_preference_does_not_change_the_key(env: PipelineEnv, kind: str) -> None:
    base = file_draft() if kind == "file" else mongo_draft()
    ask = key_of(env, base)
    source = key_of(env, with_pref(base, "source", "file:flows.csv"))
    graph = key_of(env, with_pref(base, "graph", "file:flows.csv"))
    other_target = key_of(env, with_pref(base, "source", "mongo:test/flows/links#abc"))
    assert ask == source == graph == other_target


def test_an_inline_text_ignores_the_preference_too(env: PipelineEnv) -> None:
    plain = GraphDraft(source=TextSource(content=CSV))
    assert key_of(env, plain) == key_of(env, with_pref(plain, "graph", "file:x.csv"))


def test_the_node_order_does_not_change_the_key(env: PipelineEnv) -> None:
    base = manual_draft(("a", "b", 1, None))
    ordered = with_style(base, node_order=["b", "a"])
    assert key_of(env, base) == key_of(env, ordered)
    assert key_of(env, ordered) == key_of(env, with_style(base, node_order=["a"]))


@pytest.mark.parametrize(
    "change",
    [{"extra_links": [EXTRA]}, {"entry_categories": [PICK]}],
    ids=["extra_links", "entry_categories"],
)
def test_extra_links_and_entry_categories_change_the_key(
    env: PipelineEnv, change: dict[str, Any]
) -> None:
    base = manual_draft(("a", "b", 1, None))
    changed = with_transform(base, **change)
    assert key_of(env, changed) != key_of(env, base)
    assert key_of(env, changed) == key_of(env, with_transform(base, **change))


def test_a_different_extra_link_is_a_different_key(env: PipelineEnv) -> None:
    base = manual_draft(("a", "b", 1, None))
    one = with_transform(base, extra_links=[EXTRA])
    other = with_transform(base, extra_links=[{**EXTRA, "value": 3}])
    both = with_transform(base, extra_links=[EXTRA, EXTRA])
    assert len({key_of(env, d) for d in (base, one, other, both)}) == 4
