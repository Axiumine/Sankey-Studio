# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Special checks and the check loop: Mongo lifecycle, release wrapper order, offline, lock."""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from scripts import githook_exec as ex
from scripts import githook_messages as msg
from scripts.githook_flows import head_target
from scripts.githook_runner import GateInterruptedError
from scripts.githook_stamps import GateLock

from tests.githook_support import Case, Rig, case_id, log_of, make_rig, run_check

if TYPE_CHECKING:
    from pathlib import Path

URI = "mongodb://127.0.0.1:27117"
PING = ("uv", "run", "python", "scripts/mongo_wait.py", "--uri", URI, "--timeout")


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


# --------------------------------------------------------------------------- e2e-mongo lifecycle


def test_mongo_is_started_waited_for_and_stopped_by_the_gate(rig: Rig) -> None:
    rig.runner.codes["ping-once"] = 1
    assert run_check(rig, "e2e-mongo") == 0
    assert rig.runner.labels == [
        "ping-once",
        "mongo-absent",
        "mongo-up",
        "ping-wait",
        "e2e-mongo",
        "mongo-down",
    ]
    assert rig.runner.commands("ping-once")[0].argv == (*PING, "0")
    assert rig.runner.commands("ping-wait")[0].argv == (*PING, "60")
    assert rig.runner.commands("mongo-up")[0].argv == ("make", "mongo-up")
    assert rig.runner.commands("mongo-down")[0].argv == ("make", "mongo-down")
    assert rig.stamped("e2e-mongo", rig.tree())
    assert "already running" not in rig.text


def test_a_mongo_that_was_already_running_is_used_and_left_running(rig: Rig) -> None:
    assert run_check(rig, "e2e-mongo") == 0
    assert rig.runner.labels == ["ping-once", "e2e-mongo"]
    line = "gate: mongo: already running on 127.0.0.1:27117, left running"
    assert line in rig.text.splitlines()
    assert rig.stamped("e2e-mongo", rig.tree())


def test_only_the_e2e_mongo_step_gets_the_mongo_variable(rig: Rig) -> None:
    rig.runner.codes["ping-once"] = 1
    run_check(rig, "e2e-mongo")
    with_uri = [
        label
        for label in rig.runner.labels
        if "SANKEY_TEST_MONGO_URI" in rig.runner.commands(label)[0].env
    ]
    assert with_uri == ["e2e-mongo"]
    assert rig.runner.commands("e2e-mongo")[0].env["SANKEY_TEST_MONGO_URI"] == URI
    assert "SANKEY_TEST_MONGO_URI" not in rig.gate.base_env


def test_the_mongo_variable_of_the_hook_environment_never_reaches_a_helper(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, {"PATH": "/usr/bin", "SANKEY_TEST_MONGO_URI": "mongodb://other:27018"})
    rig.runner.codes["ping-once"] = 1
    run_check(rig, "e2e-mongo")
    assert rig.runner.commands("e2e-mongo")[0].env["SANKEY_TEST_MONGO_URI"] == URI
    assert rig.runner.commands("ping-once")[0].env.get("SANKEY_TEST_MONGO_URI") is None


def test_a_mongo_that_never_answers_fails_the_check_and_is_stopped_again(rig: Rig) -> None:
    rig.runner.codes.update({"ping-once": 1, "ping-wait": 1})
    assert run_check(rig, "e2e-mongo") == 1
    assert rig.runner.labels == ["ping-once", "mongo-absent", "mongo-up", "ping-wait", "mongo-down"]
    lines = rig.text.splitlines()
    assert "gate: e2e-mongo: the project MongoDB on 127.0.0.1:27117 did not answer" in lines
    assert lines[-1] == f"gate: FAILED e2e-mongo (exit 1); log: {log_of(rig, 'e2e-mongo')}"
    assert not rig.stamped("e2e-mongo", rig.tree())


def test_mongo_is_stopped_after_a_failing_step(rig: Rig) -> None:
    rig.runner.codes.update({"ping-once": 1, "e2e-mongo": 4})
    assert run_check(rig, "e2e-mongo") == 4
    assert rig.runner.labels[-1] == "mongo-down"


def test_mongo_is_stopped_after_a_junit_failure(rig: Rig) -> None:
    rig.runner.codes["ping-once"] = 1
    rig.runner.skips["e2e-mongo"] = ("no browser",)
    assert run_check(rig, "e2e-mongo") == 1
    assert rig.runner.labels[-1] == "mongo-down"


def test_a_failed_make_mongo_up_fails_the_check_at_once_without_waiting(rig: Rig) -> None:
    rig.runner.codes.update({"ping-once": 1, "mongo-up": 2})
    assert run_check(rig, "e2e-mongo") == 1
    assert rig.runner.labels == ["ping-once", "mongo-absent", "mongo-up", "mongo-down"]
    assert "ping-wait" not in rig.runner.labels
    lines = rig.text.splitlines()
    assert "gate: e2e-mongo: the project MongoDB on 127.0.0.1:27117 did not answer" in lines
    assert lines[-1] == f"gate: FAILED e2e-mongo (exit 1); log: {log_of(rig, 'e2e-mongo')}"
    assert not rig.stamped("e2e-mongo", rig.tree())


def test_mongo_is_stopped_when_a_signal_arrives_during_the_tests(rig: Rig) -> None:
    def interrupt() -> None:
        raise GateInterruptedError(15)

    rig.runner.codes["ping-once"] = 1
    rig.runner.effects["e2e-mongo"] = interrupt
    with pytest.raises(GateInterruptedError):
        run_check(rig, "e2e-mongo")
    assert rig.runner.labels == [
        "ping-once",
        "mongo-absent",
        "mongo-up",
        "ping-wait",
        "e2e-mongo",
        "mongo-down",
    ]
    assert not rig.stamped("e2e-mongo", rig.tree())


def test_mongo_is_stopped_when_a_signal_arrives_while_it_starts(rig: Rig) -> None:
    def interrupt() -> None:
        raise GateInterruptedError(2)

    rig.runner.codes["ping-once"] = 1
    rig.runner.effects["mongo-up"] = interrupt
    with pytest.raises(GateInterruptedError):
        run_check(rig, "e2e-mongo")
    assert rig.runner.labels == ["ping-once", "mongo-absent", "mongo-up", "mongo-down"]


def test_a_mongo_that_was_already_running_is_not_stopped_on_a_signal(rig: Rig) -> None:
    def interrupt() -> None:
        raise GateInterruptedError(15)

    rig.runner.effects["e2e-mongo"] = interrupt
    with pytest.raises(GateInterruptedError):
        run_check(rig, "e2e-mongo")
    assert "mongo-down" not in rig.runner.labels


def test_the_mongo_session_yields_whether_the_server_answers(rig: Rig) -> None:
    log = io.BytesIO()
    with ex.mongo_session(rig.gate, log) as ready:
        assert ready is True
    rig.runner.codes.update({"ping-once": 1, "ping-wait": 1})
    with ex.mongo_session(rig.gate, log) as ready:
        assert ready is False
    assert rig.runner.labels[-3:] == ["mongo-up", "ping-wait", "mongo-down"]


def test_the_mongo_session_does_not_ping_for_60_seconds_after_a_failed_start(rig: Rig) -> None:
    rig.runner.codes.update({"ping-once": 1, "mongo-up": 1})
    with ex.mongo_session(rig.gate, io.BytesIO()) as ready:
        assert ready is False
    assert rig.runner.labels == ["ping-once", "mongo-absent", "mongo-up", "mongo-down"]


def test_ping_argv_is_the_helper_script_with_the_project_uri() -> None:
    assert ex.ping_argv(0) == (*PING, "0")
    assert ex.ping_argv(60) == (*PING, "60")
    assert ex.MONGO_WAIT_SECONDS == 60


# --------------------------------------------------------------------------- release wrapper order


def test_qodana_runs_a_fresh_coverage_before_the_scan(rig: Rig) -> None:
    assert run_check(rig, "qodana") == 0
    assert rig.runner.labels == ["cov", "qodana"]
    assert rig.stamped("qodana", rig.tree())
    assert not rig.stamped("cov", rig.tree())


def test_a_missing_qodana_token_fails_closed_with_the_script_exit_code(rig: Rig) -> None:
    rig.runner.codes["qodana"] = 2
    assert run_check(rig, "qodana") == 2
    assert rig.runner.labels == ["cov", "qodana"]
    assert rig.text.endswith(f"gate: FAILED qodana (exit 2); log: {log_of(rig, 'qodana')}\n")
    assert not rig.stamped("qodana", rig.tree())


def test_qodana_does_not_run_on_stale_coverage_when_the_fresh_run_fails(rig: Rig) -> None:
    rig.runner.codes["cov"] = 1
    assert run_check(rig, "qodana") == 1
    assert rig.runner.labels == ["cov"]


def test_mutation_runs_the_mutants_before_judging_them(rig: Rig) -> None:
    assert run_check(rig, "mutation") == 0
    assert rig.runner.labels == ["mutate", "mutate-gate"]
    assert rig.stamped("mutation", rig.tree())


def test_the_gate_never_judges_mutants_that_failed_to_build(rig: Rig) -> None:
    rig.runner.codes["mutate"] = 1
    assert run_check(rig, "mutation") == 1
    assert rig.runner.labels == ["mutate"]
    assert not rig.stamped("mutation", rig.tree())


def test_a_low_mutation_score_fails_the_whole_check(rig: Rig) -> None:
    rig.runner.codes["mutate-gate"] = 1
    assert run_check(rig, "mutation") == 1
    assert not rig.stamped("mutation", rig.tree())
    stamp_dir = rig.gate.store.base / "mutation"
    assert list(stamp_dir.iterdir()) == []


def test_security_runs_the_three_scans_in_order_and_is_stamped_for_the_day(rig: Rig) -> None:
    assert run_check(rig, "security") == 0
    assert rig.runner.labels == ["semgrep-test", "semgrep", "trivy"]
    tree = rig.tree()
    assert rig.gate.store.path("security", f"{tree}.20261015").is_file()
    assert rig.stamped("security", tree)
    rig.clock.advance(days=1)
    assert not rig.stamped("security", tree)


def test_a_failing_scan_stops_the_remaining_scans(rig: Rig) -> None:
    rig.runner.codes["semgrep"] = 1
    assert run_check(rig, "security") == 1
    assert rig.runner.labels == ["semgrep-test", "semgrep"]


def test_the_security_stamp_uses_the_utc_day_at_the_start_of_the_run(rig: Rig) -> None:
    west = timezone(timedelta(hours=-8))
    rig.clock.now = datetime(2026, 10, 15, 22, 0, tzinfo=west)
    assert run_check(rig, "security") == 0
    assert rig.gate.store.path("security", f"{rig.tree()}.20261016").is_file()


# --------------------------------------------------------------------------- stamps in the log


def test_describe_stamp_gives_the_duration_and_the_finish_time(rig: Rig) -> None:
    stamp = rig.gate.stamp_of("fast", rig.tree())
    assert stamp is None
    rig.stamp("fast", rig.tree())
    found = rig.gate.stamp_of("fast", rig.tree())
    assert found is not None
    assert ex.describe_stamp(found) == "took 1.5s, finished 2026-10-15T12:00:00Z"


# --------------------------------------------------------------------------- offline switches


OFFLINE = [
    Case({"TRIVY_OFFLINE": "1"}, "TRIVY_OFFLINE", "trivy"),
    Case({"SEMGREP_OFFLINE": "1"}, "SEMGREP_OFFLINE", "semgrep"),
    Case({"SEMGREP_OFFLINE": "1", "TRIVY_OFFLINE": "1"}, "SEMGREP_OFFLINE", "sorted, first"),
    Case({"TRIVY_OFFLINE": "true"}, "TRIVY_OFFLINE", "any non-empty value"),
    Case({"TRIVY_OFFLINE": "yes", "A_OFFLINE": "0"}, "TRIVY_OFFLINE", "zero does not count"),
    Case({"X_OFFLINE": "1", "TRIVY_OFFLINE": "1"}, "TRIVY_OFFLINE", "sorted by name"),
    Case({"TRIVY_OFFLINE": "0"}, None, "zero"),
    Case({"TRIVY_OFFLINE": ""}, None, "empty"),
    Case({"TRIVY_OFFLINE_MODE": "1"}, None, "suffix only"),
    Case({"trivy_offline": "1"}, None, "case sensitive"),
    Case({"OFFLINE": "1"}, None, "needs the underscore"),
    Case({}, None, "nothing"),
]


@pytest.mark.parametrize("case", OFFLINE, ids=case_id)
def test_offline_variable_finds_the_first_switched_on_offline_switch(
    case: Case[dict[str, str], str | None],
) -> None:
    assert ex.offline_variable(case.given) == case.expected
    assert ex.OFFLINE_SUFFIX == "_OFFLINE"


def test_the_refusal_names_the_scan_and_the_switch(rig: Rig) -> None:
    rig.gate.environ = {"SEMGREP_OFFLINE": "1"}
    refusal = ex.offline_refusal(rig.gate, ["fast", "security"])
    assert refusal == (
        "gate: refusing to run security: SEMGREP_OFFLINE is set; "
        "offline switches weaken the scans, unset it"
    )
    assert refusal == msg.OFFLINE.format(check="security", name="SEMGREP_OFFLINE")


def test_no_refusal_unless_a_guarded_scan_is_about_to_run(rig: Rig) -> None:
    rig.gate.environ = {"SEMGREP_OFFLINE": "1"}
    assert ex.offline_refusal(rig.gate, ["fast", "cov", "e2e-mongo", "mutation"]) is None
    assert ex.offline_refusal(rig.gate, []) is None
    rig.gate.environ = {}
    assert ex.offline_refusal(rig.gate, ["security"]) is None


def test_a_run_with_an_offline_switch_is_refused_before_anything_runs(rig: Rig) -> None:
    rig.gate.environ = {"TRIVY_OFFLINE": "1"}
    outcome = ex.ensure_checks(rig.gate, ["fast", "security"], head_target(rig.gate))
    assert outcome == ex.Outcome(1, "fast", ran=False)
    assert rig.runner.calls == []
    assert rig.text.splitlines()[-1] == (
        "gate: refusing to run security: TRIVY_OFFLINE is set; "
        "offline switches weaken the scans, unset it"
    )
    assert not rig.gate.lock_path.exists()


def test_an_offline_switch_is_harmless_when_the_scan_is_already_stamped(rig: Rig) -> None:
    rig.gate.environ = {"TRIVY_OFFLINE": "1"}
    rig.stamp("security", rig.tree())
    outcome = ex.ensure_checks(rig.gate, ["fast", "security"], head_target(rig.gate))
    assert outcome == ex.Outcome(0)
    assert rig.runner.labels == ["lint", "typecheck", "caps"]


# --------------------------------------------------------------------------- ensure_checks


def test_nothing_runs_when_every_check_has_a_stamp(rig: Rig) -> None:
    rig.stamp_all(["fast", "cov"], rig.tree())
    outcome = ex.ensure_checks(rig.gate, ["fast", "cov"], head_target(rig.gate))
    assert outcome == ex.Outcome(0)
    assert rig.runner.calls == []
    assert rig.text == (
        "gate: fast: stamp found (took 1.5s, finished 2026-10-15T12:00:00Z)\n"
        "gate: cov: stamp found (took 1.5s, finished 2026-10-15T12:00:00Z)\n"
    )
    assert not rig.gate.lock_path.exists()


def test_only_the_checks_without_a_stamp_run_and_they_run_in_the_given_order(rig: Rig) -> None:
    rig.stamp("cov", rig.tree())
    outcome = ex.ensure_checks(rig.gate, ["fast", "cov", "memray"], head_target(rig.gate))
    assert outcome == ex.Outcome(0)
    assert rig.runner.labels == ["lint", "typecheck", "caps", "memray"]
    assert "gate: cov: stamp found" in rig.text
    assert all(rig.stamped(name, rig.tree()) for name in ("fast", "cov", "memray"))


def test_the_first_failing_check_stops_the_loop_and_is_named(rig: Rig) -> None:
    rig.runner.codes["memray"] = 3
    outcome = ex.ensure_checks(rig.gate, ["fast", "cov", "memray", "e2e"], head_target(rig.gate))
    assert outcome == ex.Outcome(3, "memray")
    assert rig.runner.labels == ["lint", "typecheck", "caps", "cov", "memray"]
    assert rig.stamped("fast", rig.tree())
    assert rig.stamped("cov", rig.tree())
    assert not rig.stamped("memray", rig.tree())
    assert not rig.stamped("e2e", rig.tree())


def test_a_retry_resumes_with_the_check_that_failed(rig: Rig) -> None:
    rig.runner.codes["memray"] = 3
    names = ["fast", "cov", "memray", "e2e"]
    ex.ensure_checks(rig.gate, names, head_target(rig.gate))
    rig.runner.calls.clear()
    rig.runner.codes.clear()
    assert ex.ensure_checks(rig.gate, names, head_target(rig.gate)) == ex.Outcome(0)
    assert rig.runner.labels == ["memray", "e2e"]


def test_force_runs_everything_again_even_with_stamps(rig: Rig) -> None:
    rig.stamp_all(["fast", "cov"], rig.tree())
    target = head_target(rig.gate, force=True)
    assert target.force
    assert ex.ensure_checks(rig.gate, ["fast", "cov"], target) == ex.Outcome(0)
    assert rig.runner.labels == ["lint", "typecheck", "caps", "cov"]
    assert "stamp found" not in rig.text


def test_missing_checks_lists_the_unstamped_ones_or_all_when_forced(rig: Rig) -> None:
    rig.stamp("cov", rig.tree())
    names = ["fast", "cov", "memray"]
    assert ex.missing_checks(rig.gate, names, head_target(rig.gate)) == ["fast", "memray"]
    assert ex.missing_checks(rig.gate, names, head_target(rig.gate, force=True)) == names
    assert ex.missing_checks(rig.gate, [], head_target(rig.gate)) == []


def test_a_stamp_for_another_tree_does_not_count(rig: Rig) -> None:
    rig.stamp("fast", "e" * 40)
    assert ex.missing_checks(rig.gate, ["fast"], head_target(rig.gate)) == ["fast"]


def test_a_second_gate_run_is_refused_and_told_who_holds_the_lock(rig: Rig) -> None:
    with GateLock(rig.gate.lock_path, "pid 99, pre-push, started 2026-10-15T11:00:00Z"):
        outcome = ex.ensure_checks(rig.gate, ["fast", "cov"], head_target(rig.gate))
    assert outcome == ex.Outcome(1, "fast", ran=False)
    assert rig.runner.calls == []
    assert rig.text == (
        f"gate: another gate run holds {rig.gate.lock_path} "
        "(pid 99, pre-push, started 2026-10-15T11:00:00Z); wait for it to finish\n"
    )


def test_a_busy_lock_does_not_matter_when_nothing_has_to_run(rig: Rig) -> None:
    rig.stamp("fast", rig.tree())
    with GateLock(rig.gate.lock_path, "pid 99, run, started x"):
        assert ex.ensure_checks(rig.gate, ["fast"], head_target(rig.gate)) == ex.Outcome(0)


def test_the_lock_is_held_while_checks_run_and_free_afterwards(rig: Rig) -> None:
    seen: list[str] = []
    rig.runner.effects["lint"] = lambda: seen.append(rig.gate.lock_path.read_text(encoding="utf-8"))
    ex.ensure_checks(rig.gate, ["fast"], head_target(rig.gate))
    assert seen == [f"pid {os.getpid()}, gate, started 2026-10-15T12:30:00Z\n"]
    with GateLock(rig.gate.lock_path, "free again"):
        pass


def test_the_lock_is_free_again_after_a_failure_and_after_a_crash(rig: Rig) -> None:
    rig.runner.codes["lint"] = 1
    ex.ensure_checks(rig.gate, ["fast"], head_target(rig.gate))
    with GateLock(rig.gate.lock_path, "after failure"):
        pass

    def crash() -> None:
        raise RuntimeError("runner bug")

    rig.runner.effects["lint"] = crash
    with pytest.raises(RuntimeError, match="runner bug"):
        ex.ensure_checks(rig.gate, ["fast"], head_target(rig.gate))
    with GateLock(rig.gate.lock_path, "after crash"):
        pass


def test_a_check_stamped_while_an_earlier_one_ran_is_skipped(rig: Rig) -> None:
    tree = rig.tree()
    rig.runner.effects["lint"] = lambda: rig.stamp("cov", tree)
    outcome = ex.ensure_checks(rig.gate, ["fast", "cov"], head_target(rig.gate))
    assert outcome == ex.Outcome(0)
    assert rig.runner.labels == ["lint", "typecheck", "caps"]
    assert "gate: cov: stamped meanwhile, skipped" in rig.text.splitlines()


def test_force_does_not_skip_a_check_that_was_stamped_meanwhile(rig: Rig) -> None:
    tree = rig.tree()
    rig.runner.effects["lint"] = lambda: rig.stamp("cov", tree)
    target = head_target(rig.gate, force=True)
    assert ex.run_todo(rig.gate, ["fast", "cov"], target) == ex.Outcome(0)
    assert rig.runner.labels == ["lint", "typecheck", "caps", "cov"]


def test_run_todo_returns_the_failure_with_the_name_of_the_check(rig: Rig) -> None:
    rig.runner.codes["typecheck"] = 9
    outcome = ex.run_todo(rig.gate, ["fast", "cov"], head_target(rig.gate))
    assert outcome == ex.Outcome(9, "fast")
    assert ex.run_todo(rig.gate, [], head_target(rig.gate)) == ex.Outcome(0)


def test_an_outcome_defaults_to_no_failed_check_and_a_check_that_ran() -> None:
    assert ex.Outcome(0) == (0, "", True)
    assert ex.Outcome(0).check == ""
    assert ex.Outcome(0).ran is True


def test_a_failed_check_has_run_and_a_refused_one_has_not(rig: Rig) -> None:
    rig.runner.codes["lint"] = 4
    failed = ex.ensure_checks(rig.gate, ["fast"], head_target(rig.gate))
    assert failed == ex.Outcome(4, "fast")
    assert failed.ran
