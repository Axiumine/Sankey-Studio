"""The hook shims and the Makefile targets the gate relies on. Nothing here runs a hook or a check.

The shims are only read (and syntax-checked with ``bash -n``); the Makefile is only asked what it
*would* run (``make -n``), so no test starts lint, pytest, docker or the gate.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from typing import TYPE_CHECKING

import pytest
from scripts.githook_flows import HOOK_NAMES
from scripts.githook_plan import CHECKS, Tier

from tests.githook_support import REPO_ROOT, Case, case_id

if TYPE_CHECKING:
    from pathlib import Path

HOOKS = REPO_ROOT / ".githooks"
MAKEFILE = REPO_ROOT / "Makefile"
MAKE = shutil.which("make") or "make"
BASH = shutil.which("bash") or "bash"
SHIMS = ("pre-commit", "pre-merge-commit", "pre-push")
GATE = "uv run --no-project --python 3.14 python -m scripts.githook_gate"

pytestmark = pytest.mark.skipif(
    shutil.which("make") is None or shutil.which("bash") is None,
    reason="make and bash are needed to read the wiring",
)


def make_dry_run(*args: str) -> str:
    """What ``make -n ARGS`` prints: the commands it would run, none of them executed."""
    env = {**os.environ, "LC_ALL": "C", "MAKEFLAGS": ""}
    done = subprocess.run(  # noqa: S603 - fixed argv, `-n` only prints the recipes
        [MAKE, "-n", "--no-print-directory", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def makefile_text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def make_targets() -> set[str]:
    return set(re.findall(r"^([A-Za-z0-9_%-]+):", makefile_text(), flags=re.MULTILINE))


def phony_targets() -> set[str]:
    text = makefile_text().replace("\\\n", " ")
    line = next(ln for ln in text.splitlines() if ln.startswith(".PHONY:"))
    return set(line.removeprefix(".PHONY:").split())


# --------------------------------------------------------------------------- the shims


@pytest.mark.parametrize("hook", SHIMS)
def test_each_gate_shim_exists_and_is_executable(hook: str) -> None:
    path = HOOKS / hook
    assert path.is_file()
    mode = path.stat().st_mode
    assert mode & stat.S_IXUSR
    assert os.access(path, os.X_OK)


@pytest.mark.parametrize("hook", SHIMS)
def test_each_shim_is_three_lines_that_call_the_runner_with_its_own_name(hook: str) -> None:
    lines = (HOOKS / hook).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0] == "#!/usr/bin/env bash"
    assert lines[1].startswith('export PATH="$HOME/.local/bin:$PATH"')
    assert lines[2] == f'cd "$(git rev-parse --show-toplevel)" && exec {GATE} {hook} "$@"'


@pytest.mark.parametrize("hook", [*SHIMS, "commit-msg"])
def test_every_hook_is_valid_bash(hook: str) -> None:
    done = subprocess.run(  # noqa: S603 - fixed argv; `bash -n` parses and never runs the hook
        [BASH, "-n", str(HOOKS / hook)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_a_failed_cd_or_a_missing_uv_cannot_let_a_hook_pass() -> None:
    for hook in SHIMS:
        line = (HOOKS / hook).read_text(encoding="utf-8").splitlines()[2]
        assert " && exec " in line
        assert "|| true" not in line
        assert not line.rstrip().endswith("&")


def test_the_hook_folder_holds_exactly_the_four_known_hooks() -> None:
    assert sorted(p.name for p in HOOKS.iterdir()) == sorted(HOOK_NAMES)
    assert set(SHIMS) | {"commit-msg"} == set(HOOK_NAMES)


def test_commit_msg_stays_a_plain_script_that_the_gate_reuses() -> None:
    text = (HOOKS / "commit-msg").read_text(encoding="utf-8")
    assert "githook_gate" not in text
    assert os.access(HOOKS / "commit-msg", os.X_OK)


def test_the_gate_files_the_shims_point_to_exist() -> None:
    scripts = REPO_ROOT / "scripts"
    for name in ("githook_gate", "githook_plan", "githook_exec", "githook_push", "mongo_wait"):
        assert (scripts / f"{name}.py").is_file(), name
    assert (scripts / "__init__.py").is_file()


# --------------------------------------------------------------------------- Makefile targets


GATE_TARGETS = [
    Case("gate-commit", "run commit"),
    Case("gate-push", "run push"),
    Case("gate-main", "run main"),
    Case("gate-release", "run release"),
    Case("hooks-check", "hooks-check"),
]


@pytest.mark.parametrize("case", GATE_TARGETS, ids=case_id)
def test_each_gate_target_exists_is_phony_and_calls_the_runner(case: Case[str, str]) -> None:
    assert case.given in make_targets()
    assert case.given in phony_targets()
    assert make_dry_run(case.given).strip() == f"{GATE} {case.expected}"


def test_the_gate_targets_cover_every_tier_by_name() -> None:
    wrapped = {t.removeprefix("gate-") for t in make_targets() if t.startswith("gate-")}
    assert wrapped == {tier.value for tier in Tier}


def test_make_sync_enables_the_hooks_first() -> None:
    printed = make_dry_run("sync").splitlines()
    assert printed[0] == "git config core.hooksPath .githooks"
    assert printed[-1] == "uv sync --all-extras"


def test_make_hooks_only_sets_the_hooks_path() -> None:
    assert make_dry_run("hooks").strip() == "git config core.hooksPath .githooks"


def test_every_make_target_the_gate_calls_exists() -> None:
    called = {step.argv[1] for check in CHECKS.values() for step in check.steps}
    called |= {"mongo-up", "mongo-down", "mongo-absent"}
    assert called <= make_targets()
    assert called <= phony_targets()


FAKE_DOCKER = """#!/bin/sh
case "$FAKE_DOCKER" in
  fail) exit 1 ;;
  running) echo 0123456789ab ;;
esac
"""
MONGO_ABSENT = [
    Case("none", 0, "docker answers and lists no container"),
    Case("running", 2, "docker lists the project container"),
    Case("fail", 2, "docker does not answer"),
]


@pytest.mark.parametrize("case", MONGO_ABSENT, ids=case_id)
def test_mongo_absent_succeeds_only_when_docker_says_no_container_is_running(
    case: Case[str, int], tmp_path: Path
) -> None:
    fake = tmp_path / "bin" / "docker"
    fake.parent.mkdir()
    fake.write_text(FAKE_DOCKER, encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}", "MAKEFLAGS": ""}
    env["FAKE_DOCKER"] = case.given
    done = subprocess.run(  # noqa: S603 - fixed argv; `docker` is the stand-in script above
        [MAKE, "--no-print-directory", "-C", str(REPO_ROOT), "mongo-absent"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert done.returncode == case.expected


def test_the_gate_helper_script_for_mongo_exists_where_the_gate_expects_it() -> None:
    assert (REPO_ROOT / "scripts" / "mongo_wait.py").is_file()


def test_the_caps_step_of_the_fast_check_runs_the_caps_script() -> None:
    assert ("make", "caps") in [step.argv for step in CHECKS["fast"].steps]
    assert "scripts/check_code_caps.py" in make_dry_run("caps")


# --------------------------------------------------------------------------- the JUNIT macro


JUNIT_TARGETS = [
    Case("test", ["/r/report.xml"], "test"),
    Case("cov", ["/r/report.xml"], "cov"),
    Case("memray", ["/r/report.xml"], "memray"),
    Case("e2e-mongo", ["/r/report-1.xml", "/r/report-2.xml"], "e2e-mongo"),
    Case("e2e-shard-1", ["/r/report-1.xml"], "one shard"),
    Case("e2e-shard-5", ["/r/report-5.xml"], "last shard"),
]


@pytest.mark.parametrize("case", JUNIT_TARGETS, ids=case_id)
def test_a_pytest_target_writes_the_report_the_gate_asks_for(
    case: Case[str, list[str]],
) -> None:
    printed = make_dry_run("JUNIT=/r/report.xml", case.given)
    assert re.findall(r'--junitxml="([^"]+)"', printed) == case.expected


@pytest.mark.parametrize("target", ["test", "cov", "memray", "e2e-mongo", "e2e-shard-2"])
def test_without_a_junit_variable_no_report_option_is_added(target: str) -> None:
    assert "--junitxml" not in make_dry_run(target)


def test_the_e2e_target_gives_each_of_its_five_shards_its_own_report() -> None:
    printed = make_dry_run("JUNIT=/r/report.xml", "e2e")
    assert re.findall(r'--junitxml="([^"]+)"', printed) == [
        f"/r/report-{shard}.xml" for shard in range(1, 6)
    ]


def test_a_path_with_spaces_stays_one_argument() -> None:
    printed = make_dry_run("JUNIT=/my reports/report.xml", "memray")
    assert '--junitxml="/my reports/report.xml"' in printed


def test_every_pytest_step_of_the_gate_has_a_target_that_takes_junit() -> None:
    for check in CHECKS.values():
        for step in check.steps:
            printed = make_dry_run("JUNIT=/r/report.xml", step.argv[1])
            assert ("--junitxml=" in printed) is step.junit, (check.name, step.argv)


def test_the_two_mongo_selections_run_in_separate_processes() -> None:
    printed = make_dry_run("e2e-mongo").splitlines()
    pytest_lines = [line for line in printed if "pytest" in line]
    assert len(pytest_lines) == 2
    assert '-m "e2e and mongo"' in pytest_lines[0]
    assert '-m "mongo and not e2e"' in pytest_lines[1]


def test_the_makefile_documents_the_gate_variable_once() -> None:
    assert len(re.findall(r"^GATE := ", makefile_text(), flags=re.MULTILINE)) == 1
    assert f"GATE := {GATE}" in makefile_text()


def test_the_gate_wrapper_targets_need_no_other_target_first() -> None:
    for target in ("gate-commit", "gate-push", "gate-main", "gate-release", "hooks-check"):
        assert re.search(rf"^{target}:\s*$", makefile_text(), flags=re.MULTILINE), target
