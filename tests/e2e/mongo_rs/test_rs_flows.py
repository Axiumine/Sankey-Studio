"""The real-MongoDB flows of ``tests/e2e/mongo`` on a REPLICA SET (``make e2e-mongo-rs``).

The scenarios are the very functions the standalone suite runs (and the mongomock suite before
them), so a difference in behaviour between one node and a cluster shows up as a failing twin:

* Mongo sources: connection -> databases -> collections -> sample -> fields -> preview, ``find`` and
  ``aggregate``, counting, truncation, an unreachable connection, every unsafe stage refused;
* the graph store and the folders (unique ``(parent_id, name_key)`` index, compare-and-set
  revisions, re-parent on delete) in ``sankey_studio_graphs`` / ``sankey_studio_collections``;
* source write-back (one ``update_many`` by ``_id`` or one ``insert_one`` per edit).

Everything happens in the database named in the URI path (empty when a test starts, its
collections dropped at teardown): see ``tests/e2e/support/rs_world.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_b_edit_flows import EDIT_SCENARIOS
from tests.e2e.support.http_b_folder_flows import MONGO_FLOWS as FOLDER_FLOWS
from tests.e2e.support.http_b_mongo_flows import MONGO_FLOWS, MONGO_QUERIES
from tests.e2e.support.http_b_mongo_guards import MONGO_GUARDS
from tests.e2e.support.http_b_storage_flows import STORAGE_FLOWS

if TYPE_CHECKING:
    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv

pytestmark = pytest.mark.mongo_rs


@pytest.mark.parametrize("scenario", [*MONGO_QUERIES, *MONGO_FLOWS])
def test_mongo_flow_on_a_replica_set(real_rs_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_rs_env)


@pytest.mark.parametrize("scenario", MONGO_GUARDS)
def test_mongo_guard_on_a_replica_set(real_rs_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_rs_env)


@pytest.mark.parametrize("scenario", STORAGE_FLOWS)
def test_storage_flow_on_a_replica_set(real_rs_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_rs_env)


@pytest.mark.parametrize("scenario", FOLDER_FLOWS)
def test_folder_flow_on_a_replica_set(real_rs_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_rs_env)


@pytest.mark.parametrize("scenario", EDIT_SCENARIOS)
def test_source_write_back_on_a_replica_set(real_rs_env: FlowEnv, scenario: Scenario) -> None:
    scenario(real_rs_env)
