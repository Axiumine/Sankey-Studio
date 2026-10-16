# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The same flows when the saved URI reads from secondaries (``readPreference=secondaryPreferred``).

A replica-set URI may carry any read preference, and the application never overrides it. The writes
still go to the primary, so a read that follows a write must not miss it: a save then a load, a
rename with a stale revision, a folder created then listed, a write-back then the graph. The test
side (``world.client``: seeding, counting) keeps the plain URI and reads the primary; only the
connection the application opens is changed.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_b_edit_flows import EDIT_SCENARIOS
from tests.e2e.support.http_b_folder_flows import MONGO_FLOWS as FOLDER_FLOWS
from tests.e2e.support.http_b_mongo_flows import MONGO_FLOWS
from tests.e2e.support.http_b_storage_flows import STORAGE_FLOWS
from tests.e2e.support.http_b_world import open_env
from tests.e2e.support.rs_world import secondary_reads_uri

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv, MongoWorld
    from tests.e2e.support.server import ServerFactory

pytestmark = pytest.mark.mongo_rs


@pytest.fixture
def secondary_env(make_server: ServerFactory, rs_world: MongoWorld) -> Iterator[FlowEnv]:
    world = replace(rs_world, uri=secondary_reads_uri(rs_world.uri))
    with open_env(make_server, world) as env:
        try:
            yield env
        finally:
            env.server.stop()


@pytest.mark.parametrize("scenario", [*MONGO_FLOWS, *STORAGE_FLOWS, *FOLDER_FLOWS, *EDIT_SCENARIOS])
def test_flow_with_secondary_reads(secondary_env: FlowEnv, scenario: Scenario) -> None:
    scenario(secondary_env)
