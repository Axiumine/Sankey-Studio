# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md A.6, second half: what must be refused, and the proof that nothing was written.

Shared with the real-Mongo suite (``tests/e2e/mongo``, section C). Every case is a source with a
stage or operator that could run code or write (``$out``, ``$merge``, ``$where``, ``$function``,
``$accumulator``, a nested ``$facet``, a cross-database ``$lookup`` ...): the API answers 422 with
the reason, never echoes the pipeline, and the collections of the database are exactly as before.
mongomock really executes ``$out`` / ``$merge``, so a guard that failed would show as a new
collection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_b_mongo_guards import MONGO_GUARDS
from tests.e2e.support.http_b_world import DATA_COLLECTION, mongomock_world, open_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv
    from tests.e2e.support.server import ServerFactory


@pytest.fixture(scope="module")
def env(module_make_server: ServerFactory) -> Iterator[FlowEnv]:
    """One server and one world for all cases: a refused request leaves no trace to carry over."""
    with open_env(module_make_server, mongomock_world()) as flow_env:
        yield flow_env


@pytest.mark.parametrize("scenario", MONGO_GUARDS)
def test_mongo_guard(env: FlowEnv, scenario: Scenario) -> None:
    scenario(env)


def test_the_write_detector_itself_sees_a_write(env: FlowEnv) -> None:
    """The proof behind "nothing was written": if the guard let ``$out`` through, it would show."""
    env.world.seed()
    before = env.world.counts()
    pipeline: list[dict[str, object]] = [{"$out": "written_by_the_detector_test"}]
    list(env.world.client[env.world.database][DATA_COLLECTION].aggregate(pipeline))
    assert env.world.counts() != before
    env.world.client[env.world.database].drop_collection("written_by_the_detector_test")
    assert env.world.counts() == before
