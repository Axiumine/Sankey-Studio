"""The ``e2e-mongo-rs`` check: the user's replica set. No Docker; the URI is the tests' business.

The check runs ``make e2e-mongo-rs`` like any pytest check (JUnit report, a skipped test fails
it). It never starts or stops a Mongo, never sets ``SANKEY_TEST_MONGO_URI`` and never reads the
dotenv file: the tests find ``SANKEY_TEST_MONGO_RS_URI`` in the environment of the hook or in that
file. All URIs below are made up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.githook_support import Rig, log_of, make_rig, run_check

if TYPE_CHECKING:
    from pathlib import Path

RS_ENV = "SANKEY_TEST_MONGO_RS_URI"
RS_URI = "mongodb://u:p@h1:27017,h2:27017/lab?replicaSet=rs0"
SKIP = "needs SANKEY_TEST_MONGO_RS_URI (a MongoDB replica set: environment or .env)"


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def test_the_check_starts_no_mongo_and_is_stamped_after_a_pass(rig: Rig) -> None:
    assert run_check(rig, "e2e-mongo-rs") == 0
    assert rig.runner.labels == ["e2e-mongo-rs"]  # no ping, mongo-absent, mongo-up or mongo-down
    argv = rig.runner.commands("e2e-mongo-rs")[0].argv
    assert argv[:2] == ("make", "e2e-mongo-rs")
    assert argv[2].startswith("JUNIT=")  # the report that makes a skipped test fail the check
    assert rig.stamped("e2e-mongo-rs", rig.tree())
    assert "gate: mongo:" not in rig.text


def test_the_hook_environment_reaches_the_tests_but_the_project_mongo_uri_does_not(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path, {RS_ENV: RS_URI, "SANKEY_TEST_MONGO_URI": "mongodb://elsewhere:27017"})
    assert run_check(rig, "e2e-mongo-rs") == 0
    env = rig.runner.commands("e2e-mongo-rs")[0].env
    assert env[RS_ENV] == RS_URI
    assert "SANKEY_TEST_MONGO_URI" not in env
    assert env["UV_LOCKED"] == "1"


def test_without_a_replica_set_the_tests_skip_and_the_check_fails_closed(rig: Rig) -> None:
    rig.runner.skips["e2e-mongo-rs"] = (SKIP,)
    assert run_check(rig, "e2e-mongo-rs") == 1
    assert rig.text.count("skipped test") == 1
    assert SKIP in rig.text  # the person sees WHY (no URI) and not only that a test was skipped
    assert not rig.stamped("e2e-mongo-rs", rig.tree())
    assert rig.text.splitlines()[-1] == (
        f"gate: FAILED e2e-mongo-rs (exit 1); log: {log_of(rig, 'e2e-mongo-rs')}"
    )


def test_a_failing_run_is_not_stamped_and_keeps_its_exit_code(rig: Rig) -> None:
    rig.runner.codes["e2e-mongo-rs"] = 4
    assert run_check(rig, "e2e-mongo-rs") == 4
    assert not rig.stamped("e2e-mongo-rs", rig.tree())
