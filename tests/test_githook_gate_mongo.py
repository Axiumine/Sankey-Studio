# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The project Mongo of the ``e2e-mongo`` check: the gate stops only a Mongo it started itself."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest
from scripts import githook_exec as ex
from scripts.githook_runner import GateInterruptedError

from tests.githook_support import Rig, log_of, make_rig, run_check

if TYPE_CHECKING:
    from pathlib import Path

NOT_OURS = (
    "gate: mongo: a project Mongo container may already exist (make mongo-absent failed) but does "
    "not answer yet; waiting 60 s for it, it is never stopped by the gate"
)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    rig = make_rig(tmp_path)
    rig.runner.codes.update({"ping-once": 1, "mongo-absent": 2})
    return rig


def test_a_container_that_is_up_but_not_answering_yet_is_waited_for_and_left_running(
    rig: Rig,
) -> None:
    assert run_check(rig, "e2e-mongo") == 0
    assert rig.runner.labels == ["ping-once", "mongo-absent", "ping-wait", "e2e-mongo"]
    assert rig.runner.commands("mongo-absent")[0].argv == ("make", "mongo-absent")
    assert rig.runner.commands("ping-wait")[0].argv[-1] == "60"
    assert NOT_OURS in rig.text.splitlines()
    assert rig.stamped("e2e-mongo", rig.tree())


def test_the_mongo_variable_reaches_only_the_tests_even_for_a_container_that_is_not_ours(
    rig: Rig,
) -> None:
    run_check(rig, "e2e-mongo")
    assert rig.runner.commands("e2e-mongo")[0].env["SANKEY_TEST_MONGO_URI"].endswith(":27117")
    assert "SANKEY_TEST_MONGO_URI" not in rig.runner.commands("ping-wait")[0].env


def test_a_container_that_never_answers_fails_the_check_and_is_not_stopped(rig: Rig) -> None:
    rig.runner.codes["ping-wait"] = 1
    assert run_check(rig, "e2e-mongo") == 1
    assert rig.runner.labels == ["ping-once", "mongo-absent", "ping-wait"]
    lines = rig.text.splitlines()
    assert "gate: e2e-mongo: the project MongoDB on 127.0.0.1:27117 did not answer" in lines
    assert lines[-1] == f"gate: FAILED e2e-mongo (exit 1); log: {log_of(rig, 'e2e-mongo')}"
    assert not rig.stamped("e2e-mongo", rig.tree())


def test_a_failing_step_does_not_stop_a_container_that_is_not_ours(rig: Rig) -> None:
    rig.runner.codes["e2e-mongo"] = 4
    assert run_check(rig, "e2e-mongo") == 4
    assert "mongo-down" not in rig.runner.labels
    assert "mongo-up" not in rig.runner.labels


def test_a_signal_does_not_stop_a_container_that_is_not_ours(rig: Rig) -> None:
    def interrupt() -> None:
        raise GateInterruptedError(15)

    rig.runner.effects["e2e-mongo"] = interrupt
    with pytest.raises(GateInterruptedError):
        run_check(rig, "e2e-mongo")
    assert rig.runner.labels == ["ping-once", "mongo-absent", "ping-wait", "e2e-mongo"]


def test_the_session_of_a_container_that_is_not_ours_yields_the_wait_result(rig: Rig) -> None:
    with ex.mongo_session(rig.gate, io.BytesIO()) as ready:
        assert ready is True
    rig.runner.codes["ping-wait"] = 1
    with ex.mongo_session(rig.gate, io.BytesIO()) as ready:
        assert ready is False
    assert "mongo-up" not in rig.runner.labels
    assert "mongo-down" not in rig.runner.labels


def test_only_an_absent_container_lets_the_gate_start_and_stop_the_mongo(rig: Rig) -> None:
    rig.runner.codes["mongo-absent"] = 0
    assert run_check(rig, "e2e-mongo") == 0
    assert rig.runner.labels == [
        "ping-once",
        "mongo-absent",
        "mongo-up",
        "ping-wait",
        "e2e-mongo",
        "mongo-down",
    ]
    assert NOT_OURS not in rig.text
