# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E section C: the write-back flows of ``/edits/plan`` and ``/edits/write`` on a REAL MongoDB.

Skipped unless ``SANKEY_TEST_MONGO_URI`` is set (``make e2e-mongo``). The scenarios are the very
functions the mongomock suite runs (``tests/e2e/http/test_edits_flow.py``): count then write after
the consent, a cleared category, a new document, no consent, a consent for another collection, the
application's own collections, formula-like text and a drag. Everything happens inside the
uniquely named database of ``real_env``; the sample documents are written there and dropped at
teardown. The read-only-user scenario needs the in-memory server and is not run here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_b_edit_flows import EDIT_SCENARIOS

if TYPE_CHECKING:
    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv

pytestmark = pytest.mark.mongo


@pytest.mark.parametrize("scenario", EDIT_SCENARIOS)
def test_source_write_back_on_a_real_server(real_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_env)
