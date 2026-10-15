"""Junit verification, the child environment and the real runner of a check run (githook_exec)."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest
from scripts.githook_plan import CHECKS, Check, Step
from scripts.githook_runner import SubprocessRunner

from tests.githook_support import Case, Rig, case_id, junit_xml, log_of, make_rig, run_check

MONGO_SKIP = "SANKEY_TEST_MONGO_URI is not set"

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


# --------------------------------------------------------------------------- junit


def report_dir(rig: Rig, name: str, step: int = 0) -> Path:
    return rig.gate.log_dir / f"{name}.junit" / f"step{step}"


def test_a_pytest_step_gets_a_report_path_and_the_report_is_checked(rig: Rig) -> None:
    assert run_check(rig, "cov") == 0
    (call,) = rig.runner.calls
    assert call.argv == ("make", "cov", f"JUNIT={report_dir(rig, 'cov')}/report.xml")
    assert (report_dir(rig, "cov") / "report.xml").is_file()
    assert rig.stamped("cov", rig.tree())
    assert f"$ make cov JUNIT={report_dir(rig, 'cov')}/report.xml\n" in rig.text


def test_steps_without_junit_never_get_a_report_argument(rig: Rig) -> None:
    run_check(rig, "fast")
    run_check(rig, "mutation")
    assert all(len(call.argv) == 2 for call in rig.runner.calls)
    assert not (rig.gate.log_dir / "fast.junit").exists()


def test_only_the_cov_step_of_qodana_is_a_pytest_step(rig: Rig) -> None:
    assert run_check(rig, "qodana") == 0
    cov, qodana = rig.runner.calls
    assert cov.argv[-1] == f"JUNIT={report_dir(rig, 'qodana')}/report.xml"
    assert qodana.argv == ("make", "qodana")


def test_stale_reports_are_deleted_before_a_run(rig: Rig) -> None:
    stale = report_dir(rig, "memray") / "report.xml"
    stale.parent.mkdir(parents=True)
    stale.write_text(junit_xml(5), encoding="utf-8")
    nested = report_dir(rig, "memray", 3) / "old-1.xml"
    nested.parent.mkdir(parents=True)
    nested.write_text(junit_xml(5), encoding="utf-8")
    rig.runner.reports["memray"] = None
    assert run_check(rig, "memray") == 1
    assert not stale.exists()
    assert not nested.exists()
    problem = f"gate: memray: junit: no junit report was written to {report_dir(rig, 'memray')}"
    assert problem in rig.text.splitlines()


def test_a_skipped_test_fails_the_check(rig: Rig) -> None:
    rig.runner.skips["e2e"] = ("no browser installed",)
    assert run_check(rig, "e2e") == 1
    lines = rig.text.splitlines()
    junit_line = (
        "gate: e2e: junit: skipped test tests.test_skip::test_skip_0 (no browser installed)"
    )
    assert junit_line in lines
    assert lines[-1] == f"gate: FAILED e2e (exit 1); log: {log_of(rig, 'e2e')}"
    assert not rig.stamped("e2e", rig.tree())


def test_cov_tolerates_only_the_mongo_unit_test_skips(rig: Rig) -> None:
    rig.runner.skips["cov"] = (MONGO_SKIP,) * 8
    assert run_check(rig, "cov") == 0
    assert rig.stamped("cov", rig.tree())


def test_cov_still_fails_on_any_other_skip(rig: Rig) -> None:
    rig.runner.skips["cov"] = (MONGO_SKIP, "kaleido has no chrome")
    assert run_check(rig, "cov") == 1
    assert rig.text.count("junit: skipped test") == 1
    assert "kaleido has no chrome" in rig.text


def test_the_same_mongo_skip_fails_every_other_pytest_check(rig: Rig) -> None:
    for name in ("memray", "e2e", "e2e-mongo"):
        rig.runner.skips[name] = (MONGO_SKIP,)
        assert run_check(rig, name) == 1, name
        assert not rig.stamped(name, rig.tree())


def test_the_cov_step_of_qodana_tolerates_the_same_skips(rig: Rig) -> None:
    rig.runner.skips["cov"] = (MONGO_SKIP,)
    assert run_check(rig, "qodana") == 0


JUNIT_FAILURES = [
    Case(None, "no junit report was written to", "no report"),
    Case(junit_xml(0), "hold no testcase", "nothing ran"),
    Case(junit_xml(4, closed=False), "report is not terminated", "cut off"),
    Case("", "report is not terminated", "empty"),
]


@pytest.mark.parametrize("case", JUNIT_FAILURES, ids=case_id)
def test_a_missing_or_broken_report_fails_even_when_pytest_exited_zero(
    rig: Rig, case: Case[str | None, str]
) -> None:
    rig.runner.reports["cov"] = case.given
    assert run_check(rig, "cov") == 1
    assert "gate: cov: junit: " in rig.text
    assert case.expected in rig.text
    assert not rig.stamped("cov", rig.tree())


def test_a_failing_pytest_step_is_not_second_guessed_by_its_report(rig: Rig) -> None:
    rig.runner.codes["cov"] = 1
    rig.runner.skips["cov"] = ("whatever",)
    assert run_check(rig, "cov") == 1
    assert "junit:" not in rig.text
    assert rig.text.endswith(f"gate: FAILED cov (exit 1); log: {log_of(rig, 'cov')}\n")


# --------------------------------------------------------------------------- the child env


def test_no_command_sees_the_git_or_waiver_variables_of_the_hook(tmp_path: Path) -> None:
    environ = {
        "PATH": "/usr/bin",
        "HOME": "/home/dev",
        "GIT_DIR": "/r/.git",
        "GIT_INDEX_FILE": "/r/.git/index.lock",
        "GIT_WORK_TREE": "/r",
        "PYTEST_ADDOPTS": "--no-cov -x",
        "SANKEY_TEST_MONGO_URI": "mongodb://elsewhere",
        "LANG": "C.UTF-8",
    }
    rig = make_rig(tmp_path, environ)
    for name in ("fast", "cov", "memray", "e2e"):
        assert run_check(rig, name) == 0
    assert len(rig.runner.calls) == 6
    for call in rig.runner.calls:
        assert not {"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"} & set(call.env)
        assert "PYTEST_ADDOPTS" not in call.env
        assert "SANKEY_TEST_MONGO_URI" not in call.env
        assert call.env["LANG"] == "C.UTF-8"
        assert call.env["PATH"].split(os.pathsep)[0] == f"{tmp_path / 'home'}/.local/bin"
    assert environ["GIT_DIR"] == "/r/.git"


def test_the_gate_keeps_its_own_environment_for_its_own_git_calls(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, {"PATH": "/usr/bin", "GIT_DIR": "/does/not/matter"})
    assert rig.gate.environ["GIT_DIR"] == "/does/not/matter"
    assert run_check(rig, "fast") == 0
    assert rig.stamped("fast", rig.tree())


# --------------------------------------------------------------------------- the real runner


def real_step(code: str) -> Check:
    return Check("fast", (Step((sys.executable, "-c", code)),))


def test_a_check_runs_end_to_end_through_the_real_runner(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.gate.runner = SubprocessRunner()
    rig.gate.environ = {"PATH": os.environ["PATH"], "GIT_DIR": "x", "PYTEST_ADDOPTS": "-x"}
    code = (
        "import os; e = os.environ;print(e['UV_LOCKED'], e.get('GIT_DIR'), e.get('PYTEST_ADDOPTS'))"
    )
    monkeypatch.setitem(CHECKS, "fast", real_step(code))
    assert run_check(rig, "fast") == 0
    assert "1 None None\n" in rig.text
    assert "1 None None\n" in log_of(rig, "fast").read_text(encoding="utf-8")
    assert rig.stamped("fast", rig.tree())


def test_a_failing_real_process_fails_the_check_with_its_exit_code(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.gate.runner = SubprocessRunner()
    rig.gate.environ = {"PATH": os.environ["PATH"]}
    monkeypatch.setitem(CHECKS, "fast", real_step("import sys; print('bad'); sys.exit(3)"))
    assert run_check(rig, "fast") == 3
    assert f"gate: FAILED fast (exit 3); log: {log_of(rig, 'fast')}" in rig.text
    assert "bad\n" in log_of(rig, "fast").read_text(encoding="utf-8")
    assert not rig.stamped("fast", rig.tree())
