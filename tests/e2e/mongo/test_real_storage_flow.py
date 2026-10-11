"""E2E.md section C, part 2: the storage-backend switch of A.7 against a REAL MongoDB.

Skipped unless ``SANKEY_TEST_MONGO_URI`` is set (``make e2e-mongo``). The scenarios are the ones
the mongomock suite runs (``tests/e2e/http/test_storage_switch_flow.py``): file -> Mongo with
``migrate`` (same ids and revisions, the old store untouched), back again, a switch without
``migrate`` that loses nothing, a target that does not answer (the file backend stays active and
``settings.json`` is byte-identical), a damaged graph file, and refused targets. The graph store
is the collection ``sankey_studio_graphs`` of the uniquely named test database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_b_storage_flows import STORAGE_FLOWS

if TYPE_CHECKING:
    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv

pytestmark = pytest.mark.mongo


@pytest.mark.parametrize("scenario", STORAGE_FLOWS)
def test_storage_flow_on_a_real_server(real_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_env)
