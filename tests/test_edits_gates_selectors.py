# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``set_category`` stores only the category: a node name that starts like a formula still passes.

The source and target of a ``set_category`` select the pair; they are never written, so the
formula gate must look at the category alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.edits import plan_edit, write_edit
from sankey_studio.edits.reasons import NOTICES
from tests.test_edits_support import consenting, file_source, make_edit_env, mongo_source, request

if TYPE_CHECKING:
    from pathlib import Path

    from pymongo import MongoClient

NAMES = ["+Bonus", "-Refunds", "@home", "=sum"]


def categorise(name: str, category: str | None) -> dict[str, Any]:
    return {"op": "set_category", "source": name, "target": "Budget", "category": category}


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("category", ["Income", None])
def test_a_file_pair_with_a_formula_like_name_can_be_categorised(
    tmp_path: Path, mongo_client: MongoClient[Any], name: str, category: str | None
) -> None:
    with make_edit_env(tmp_path, mongo_client) as env:
        env.write_source("a.csv", f"source,target,value,category\n{name},Budget,3000,Old\n")
        source = consenting(file_source("a.csv"), env)
        body = request(source, categorise(name, category))
        planned = plan_edit(env.services, body, env.cache)
        assert (planned.where, planned.reason) == ("file", None)
        written = write_edit(env.services, body, env.cache)
        assert (written.where, written.written) == ("file", True)
        text = (env.sources_dir / "a.csv").read_text()
        assert f"{name},Budget,3000,{category or ''}" in text


def test_a_mongo_pair_with_a_formula_like_name_can_be_categorised(
    tmp_path: Path, mongo_client: MongoClient[Any]
) -> None:
    with make_edit_env(tmp_path, mongo_client) as env:
        env.mongo["flows"]["events"].insert_one({"source": "-x", "target": "b", "value": 1})
        body = request(consenting(mongo_source(), env), {**categorise("-x", "Fun"), "target": "b"})
        assert plan_edit(env.services, body, env.cache).where == "mongo"
        assert write_edit(env.services, body, env.cache).written
        stored = env.mongo["flows"]["events"].find_one({"source": "-x"})
        assert stored is not None
        assert stored["cat"] == "Fun"


@pytest.mark.parametrize("category", ["=1+1", "+x", "@y"])
def test_a_formula_like_category_is_still_refused_for_a_file(
    tmp_path: Path, mongo_client: MongoClient[Any], category: str
) -> None:
    with make_edit_env(tmp_path, mongo_client) as env:
        text = "source,target,value,category\nBonus,Budget,3000,Old\n"
        env.write_source("a.csv", text)
        body = request(consenting(file_source("a.csv"), env), categorise("Bonus", category))
        planned = plan_edit(env.services, body, env.cache)
        assert (planned.where, planned.reason) == ("graph", "unsafe_value")
        assert planned.notice == NOTICES["unsafe_value"]
        assert write_edit(env.services, body, env.cache).reason == "unsafe_value"
        assert (env.sources_dir / "a.csv").read_text() == text
