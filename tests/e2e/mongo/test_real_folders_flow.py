# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E section C: the library folders ("collections") against a REAL MongoDB.

Skipped unless ``SANKEY_TEST_MONGO_URI`` is set (``make e2e-mongo``). The scenarios are the very
functions the mongomock suite runs (``tests/e2e/http/test_folders_flow.py``), on the Mongo store:
the whole folder API, and what only a real server proves - the unique ``(parent_id, name_key)``
index really rejects a second folder with the same name in the same place (also through a raw
insert), the ``$nin`` / ``None`` query that reads a graph with NO ``folder_id`` field as top level,
the compare-and-set rename (a stale revision is a 409), the re-parent on delete, a bundle that
carries the tree and the storage switch that copies it. Everything happens inside the uniquely
named database of ``real_env``; it is dropped at teardown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_b_folder_flows import MONGO_FLOWS

if TYPE_CHECKING:
    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv

pytestmark = pytest.mark.mongo


@pytest.mark.parametrize("scenario", MONGO_FLOWS)
def test_folder_flow_on_a_real_server(real_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_env)
