# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The preflight probes: quick prerequisite checks before the first long check of a run.

A push of ``main`` or a tag needs Docker, the Qodana token and the user's replica set. Finding
that out after 25 minutes of ``cov`` and ``e2e`` is too late, so the gate probes them first (each
probe is a ``make`` target, run unstamped) and refuses the push when one fails.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts import githook_messages as msg
from scripts import githook_push as push
from scripts.githook_exec import ensure_checks, preflight_names
from scripts.githook_flows import head_target
from scripts.githook_plan import CHECK_ORDER, CHECKS, PREFLIGHT_ORDER, PREFLIGHTS

from tests.githook_support import Case, Rig, case_id, log_of, make_rig, push_line

if TYPE_CHECKING:
    from pathlib import Path

PROBES = ["preflight-docker", "preflight-qodana", "preflight-rs"]
RELEASE_BODY = ["lint", "typecheck", "caps", "cov", "memray", "e2e"]
SKIP = "needs SANKEY_TEST_MONGO_RS_URI (a MongoDB replica set: environment or .env)"


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def main_push(rig: Rig) -> str:
    sha = rig.git("rev-parse", "HEAD")
    return push_line("refs/heads/main", sha, "refs/heads/main")


def go(rig: Rig, text: str, *, dry_run: bool | None = None) -> int:
    return push.pre_push(rig.gate, "origin", text, dry_run=dry_run)


NEEDS = [
    Case("fast", (), "lint, typecheck and caps need nothing"),
    Case("cov", (), "cov"),
    Case("memray", (), "memray"),
    Case("e2e", (), "e2e"),
    Case("security", ("preflight-docker",), "the scanners run in Docker"),
    Case("e2e-mongo", ("preflight-docker",), "the project Mongo is a container"),
    Case("e2e-mongo-rs", ("preflight-rs",), "the user's replica set, no Docker"),
    Case("qodana", ("preflight-docker", "preflight-qodana"), "Docker and the token"),
    Case("mutation", (), "mutation needs nothing from the machine"),
]


@pytest.mark.parametrize("case", NEEDS, ids=case_id)
def test_each_check_names_the_probes_it_needs(case: Case[str, tuple[str, ...]]) -> None:
    assert CHECKS[case.given].needs == case.expected


def test_every_check_is_listed_here() -> None:
    assert [case.given for case in NEEDS] == list(CHECK_ORDER)


def test_a_probe_is_a_make_target_that_is_no_check_and_is_never_stamped() -> None:
    assert list(PREFLIGHTS) == PROBES == list(PREFLIGHT_ORDER)
    assert not set(PREFLIGHTS) & set(CHECKS)
    for name, probe in PREFLIGHTS.items():
        assert [step.argv for step in probe.steps] == [("make", name)]
        assert probe.needs == ()
        assert (name == "preflight-rs") == probe.steps[0].junit  # a skipped test fails that one
    assert {need for check in CHECKS.values() for need in check.needs} == set(PROBES)


NAMES = [
    Case([], [], "no check"),
    Case(["fast", "cov", "memray", "e2e", "mutation"], [], "checks that need nothing"),
    Case(["security"], ["preflight-docker"], "security"),
    Case(["e2e-mongo-rs"], ["preflight-rs"], "the replica set"),
    Case(["qodana", "security"], ["preflight-docker", "preflight-qodana"], "once, in order"),
    Case(list(CHECK_ORDER), PROBES, "everything"),
    Case(["qodana", "e2e-mongo-rs"], PROBES, "the fixed order, not the order of the checks"),
]


@pytest.mark.parametrize("case", NAMES, ids=case_id)
def test_the_probes_of_a_run_are_listed_once_in_a_fixed_order(
    case: Case[list[str], list[str]],
) -> None:
    assert preflight_names(case.given) == case.expected


def test_a_release_push_probes_the_machine_before_its_first_long_check(rig: Rig) -> None:
    assert go(rig, main_push(rig)) == 0
    assert rig.runner.labels[:4] == [*PROBES, "lint"]
    assert "gate: preflight: preflight-docker, preflight-qodana, preflight-rs" in rig.text
    assert rig.text.count("not stamped: a probe of this machine") == len(PROBES)
    stamps = rig.gate.repo.common_dir / "hook-stamps"
    assert not [p for p in stamps.iterdir() if p.name.startswith("preflight")]
    assert all(rig.stamped(name, rig.tree()) for name in CHECK_ORDER)


FAILING = [
    Case("preflight-docker", ["preflight-docker"], "Docker does not answer"),
    Case("preflight-qodana", ["preflight-docker", "preflight-qodana"], "no token"),
    Case("preflight-rs", PROBES, "the replica set does not answer"),
]


@pytest.mark.parametrize("case", FAILING, ids=case_id)
def test_a_failing_probe_refuses_the_push_before_any_check_starts(
    rig: Rig, case: Case[str, list[str]]
) -> None:
    rig.runner.codes[case.given] = 2
    assert go(rig, main_push(rig)) == 1
    assert rig.runner.labels == case.expected
    assert f"gate: FAILED {case.given} (exit 2); log: {log_of(rig, case.given)}" in rig.text
    assert rig.text.splitlines()[-1] == msg.PREFLIGHT_REFUSED.format(probe=case.given, code=2)
    assert not rig.stamped("fast", rig.tree())


def test_a_skipped_replica_set_test_fails_the_probe_and_says_why(rig: Rig) -> None:
    rig.runner.skips["preflight-rs"] = (SKIP,)
    assert go(rig, main_push(rig)) == 1
    assert rig.runner.labels == PROBES
    assert rig.text.count("skipped test") == 1
    assert SKIP in rig.text


MISSING = [
    Case("mutation", ["mutate", "mutate-gate"], "no probe for mutation"),
    Case("e2e-mongo-rs", ["preflight-rs", "e2e-mongo-rs"], "only the replica set"),
    Case("qodana", ["preflight-docker", "preflight-qodana", "cov", "qodana"], "docker, token"),
    Case("e2e-mongo", ["preflight-docker", "ping-once", "e2e-mongo"], "docker only"),
]


@pytest.mark.parametrize("case", MISSING, ids=case_id)
def test_only_the_checks_still_to_run_are_probed(rig: Rig, case: Case[str, list[str]]) -> None:
    rig.stamp_all([name for name in CHECK_ORDER if name != case.given], rig.tree())
    assert go(rig, main_push(rig)) == 0
    assert rig.runner.labels == case.expected


def test_a_push_of_a_feature_branch_probes_nothing(rig: Rig) -> None:
    rig.git("checkout", "-q", "-b", "feature")
    sha = rig.git("rev-parse", "HEAD")
    assert go(rig, push_line("refs/heads/feature", sha, "refs/heads/feature")) == 0
    assert not [label for label in rig.runner.labels if label.startswith("preflight")]


def test_a_dry_run_lists_the_probes_and_runs_nothing(rig: Rig) -> None:
    assert go(rig, main_push(rig), dry_run=True) == 1  # checks would run
    assert "plan: preflight preflight-docker, preflight-qodana, preflight-rs (before" in rig.text
    assert rig.runner.calls == []


def test_a_by_hand_run_of_the_release_checks_probes_first_too(rig: Rig) -> None:
    outcome = ensure_checks(rig.gate, ["qodana"], head_target(rig.gate))
    assert outcome.code == 0
    assert rig.runner.labels == ["preflight-docker", "preflight-qodana", "cov", "qodana"]


def test_a_failing_probe_of_a_by_hand_run_is_the_failed_check(rig: Rig) -> None:
    rig.runner.codes["preflight-docker"] = 3
    outcome = ensure_checks(rig.gate, ["security", "qodana"], head_target(rig.gate))
    assert (outcome.code, outcome.check, outcome.ran) == (3, "preflight-docker", True)
    assert rig.runner.labels == ["preflight-docker"]
