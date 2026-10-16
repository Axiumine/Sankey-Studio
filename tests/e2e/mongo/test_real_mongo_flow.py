# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md section C, part 1: the Mongo flows of A.6 against a REAL MongoDB.

Skipped unless ``SANKEY_TEST_MONGO_URI`` is set (``make e2e-mongo``). The scenarios are the very
functions the mongomock suite runs (``tests/e2e/http/test_mongo_flow.py`` and
``test_mongo_guards_flow.py``): connection -> databases -> collections -> sample -> suggested
fields -> preview; ``find`` and ``aggregate``; counting mode; the truncation warning; a saved
graph; a connection that does not answer (a host name under ``.invalid``); and every unsafe stage
refused with nothing written to the database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_b_mongo_flows import MONGO_FLOWS, MONGO_QUERIES
from tests.e2e.support.http_b_mongo_guards import MONGO_GUARDS

if TYPE_CHECKING:
    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv

pytestmark = pytest.mark.mongo


@pytest.mark.parametrize("scenario", [*MONGO_QUERIES, *MONGO_FLOWS])
def test_mongo_flow_on_a_real_server(real_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_env)


@pytest.mark.parametrize("scenario", MONGO_GUARDS)
def test_mongo_guard_on_a_real_server(real_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_env)
