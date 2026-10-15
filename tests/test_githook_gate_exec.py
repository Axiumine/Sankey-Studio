"""The Gate context and one check run (scripts/githook_exec.py): commands, env, junit, stamps."""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from scripts import githook_exec as ex
from scripts.githook_git import Snapshot

from tests.githook_support import Case, Rig, case_id, log_of, make_rig, run_check

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


# --------------------------------------------------------------------------- Gate


def test_stamps_logs_and_the_lock_live_in_the_git_common_dir(rig: Rig) -> None:
    common = rig.repo.common_dir
    assert rig.gate.store.base == common / "hook-stamps"
    assert rig.gate.log_dir == common / "hook-logs"
    assert rig.gate.lock_path == common / "hook-gate.lock"


DRY_RUN = [
    Case({"SANKEY_GATE_DRY_RUN": "1"}, True),
    Case({"SANKEY_GATE_DRY_RUN": "0"}, False),
    Case({"SANKEY_GATE_DRY_RUN": ""}, False),
    Case({"SANKEY_GATE_DRY_RUN": "true"}, False),
    Case({"SANKEY_GATE_DRY_RUN": "11"}, False),
    Case({"OTHER": "1"}, False),
    Case({}, False),
]


@pytest.mark.parametrize("case", DRY_RUN, ids=case_id)
def test_only_the_value_one_switches_the_dry_run_on(
    rig: Rig, case: Case[dict[str, str], bool]
) -> None:
    rig.gate.environ = case.given
    assert rig.gate.dry_run is case.expected
    assert ex.DRY_RUN_ENV == "SANKEY_GATE_DRY_RUN"


def test_the_base_env_is_computed_once_and_child_env_adds_to_a_copy(tmp_path: Path) -> None:
    rig = make_rig(
        tmp_path, {"PATH": "/usr/bin", "KEEP": "1", "GIT_DIR": "/x", "PYTEST_ADDOPTS": "-x"}
    )
    first = rig.gate.base_env
    assert rig.gate.base_env is first
    assert "GIT_DIR" not in first
    assert "PYTEST_ADDOPTS" not in first
    assert rig.gate.child_env() == first
    merged = rig.gate.child_env({"EXTRA": "2", "KEEP": "changed"})
    assert (merged["EXTRA"], merged["KEEP"]) == ("2", "changed")
    assert "EXTRA" not in first
    assert first["KEEP"] == "1"
    assert first["PATH"] == f"{rig.gate.home}/.local/bin:/usr/bin"


class FlushCounter(io.StringIO):
    flushes = 0

    def flush(self) -> None:
        self.flushes += 1
        super().flush()


def test_say_writes_one_line_at_a_time_and_flushes_each(rig: Rig) -> None:
    rig.gate.out = counter = FlushCounter()
    rig.gate.say("one")
    rig.gate.say("two")
    assert counter.getvalue() == "one\ntwo\n"
    assert counter.flushes == 2


def test_today_is_the_utc_date_whatever_the_zone_of_the_clock(rig: Rig) -> None:
    late_in_new_york = datetime(2026, 10, 15, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    rig.clock.now = late_in_new_york
    assert rig.gate.today().isoformat() == "2026-10-16"
    rig.clock.now = datetime(2026, 10, 15, 0, 10, tzinfo=timezone(timedelta(hours=2)))
    assert rig.gate.today().isoformat() == "2026-10-14"


def test_the_key_of_a_stamp_carries_the_utc_day_only_for_the_security_check(rig: Rig) -> None:
    tree = rig.tree()
    assert rig.gate.key_for("fast", tree) == tree
    assert rig.gate.key_for("cov", tree) == tree
    assert rig.gate.key_for("security", tree) == f"{tree}.20261015"
    rig.clock.advance(days=1)
    assert rig.gate.key_for("security", tree) == f"{tree}.20261016"
    assert rig.gate.key_for("fast", tree) == tree


def test_stamp_of_finds_the_stamp_for_the_tree_and_for_the_day(rig: Rig) -> None:
    tree = rig.tree()
    assert rig.gate.stamp_of("security", tree) is None
    rig.stamp("security", tree)
    rig.stamp("fast", tree)
    found = rig.gate.stamp_of("security", tree)
    assert found is not None
    assert (found.check, found.key) == ("security", f"{tree}.20261015")
    assert rig.gate.stamp_of("fast", tree) is not None
    assert rig.gate.stamp_of("cov", tree) is None
    assert rig.gate.stamp_of("fast", "f" * 40) is None
    rig.clock.advance(hours=12)
    assert rig.gate.stamp_of("security", tree) is None
    assert rig.gate.stamp_of("fast", tree) is not None


def test_the_lock_names_its_holder(rig: Rig) -> None:
    lock = rig.gate.lock()
    assert lock.path == rig.gate.lock_path
    assert lock.holder == f"pid {os.getpid()}, gate, started 2026-10-15T12:30:00Z"
    rig.gate.label = "pre-push"
    assert rig.gate.lock().holder == f"pid {os.getpid()}, pre-push, started 2026-10-15T12:30:00Z"


def test_the_lock_holder_time_is_in_utc_whatever_the_zone_of_the_clock(rig: Rig) -> None:
    rig.clock.now = datetime(2026, 10, 15, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert rig.gate.lock().holder.endswith("started 2026-10-16T04:30:00Z")


def test_run_tool_runs_a_helper_in_the_repo_root_with_the_child_env(rig: Rig) -> None:
    rig.runner.codes["ping-once"] = 7
    code = rig.gate.run_tool(
        ("uv", "run", "python", "scripts/mongo_wait.py", "--timeout", "0"), io.BytesIO()
    )
    assert code == 7
    (call,) = rig.runner.calls
    assert call.argv == ("uv", "run", "python", "scripts/mongo_wait.py", "--timeout", "0")
    assert call.cwd == rig.repo.root
    assert call.env == rig.gate.child_env()


def test_helper_output_reaches_the_log_and_the_gate_output(rig: Rig) -> None:
    log = io.BytesIO()
    rig.gate.run_tool(["make", "mongo-up"], log)
    assert log.getvalue() == b"fake output of mongo-up\n"
    assert rig.text == "fake output of mongo-up\n"


@pytest.mark.parametrize(
    ("value", "text"),
    [(0, "0.0s"), (12.34, "12.3s"), (59.96, "60.0s"), (1234.56, "1234.6s"), (0.04, "0.0s")],
)
def test_seconds_has_one_decimal(value: float, text: str) -> None:
    assert ex.seconds(value) == text


def test_utc_now_is_aware_and_in_utc() -> None:
    now = ex.utc_now()
    assert now.tzinfo == UTC
    assert abs((datetime.now(UTC) - now).total_seconds()) < 60


# --------------------------------------------------------------------------- one passing check


def test_fast_runs_lint_typecheck_and_caps_from_the_repo_root(rig: Rig) -> None:
    assert run_check(rig, "fast") == 0
    assert rig.runner.labels == ["lint", "typecheck", "caps"]
    assert [c.argv for c in rig.runner.calls] == [
        ("make", "lint"),
        ("make", "typecheck"),
        ("make", "caps"),
    ]
    assert {c.cwd for c in rig.runner.calls} == {rig.repo.root}


def test_only_caps_runs_without_a_locked_uv(rig: Rig) -> None:
    run_check(rig, "fast")
    locked = {
        label: "UV_LOCKED" in rig.runner.commands(label)[0].env for label in rig.runner.labels
    }
    assert locked == {"lint": True, "typecheck": True, "caps": False}
    assert rig.runner.commands("lint")[0].env["UV_LOCKED"] == "1"
    assert rig.gate.base_env["UV_LOCKED"] == "1"


def test_a_passing_check_prints_its_progress_and_the_stamp_path(rig: Rig) -> None:
    run_check(rig, "fast")
    stamp = rig.gate.store.path("fast", rig.tree())
    assert rig.text == (
        "gate: fast: running\n"
        "$ make lint\nfake output of lint\n"
        "$ make typecheck\nfake output of typecheck\n"
        "$ make caps\nfake output of caps\n"
        f"gate: fast: ok in 14.0s (stamp {stamp})\n"
    )


def test_the_stamp_records_the_tree_the_time_and_every_step(rig: Rig) -> None:
    run_check(rig, "fast")
    tree = rig.tree()
    stamp = rig.gate.stamp_of("fast", tree)
    assert stamp is not None
    assert (stamp.check, stamp.key, stamp.tree) == ("fast", tree, tree)
    assert stamp.finished_utc == "2026-10-15T12:30:00Z"
    assert stamp.duration_s == 14.0
    assert [(s.argv, s.exit_code, s.duration_s) for s in stamp.steps] == [
        (("make", "lint"), 0, 2.0),
        (("make", "typecheck"), 0, 2.0),
        (("make", "caps"), 0, 2.0),
    ]


def test_the_log_holds_the_step_headers_and_the_output_and_is_rewritten_each_run(rig: Rig) -> None:
    run_check(rig, "fast")
    expected = "$ make lint\nfake output of lint\n$ make typecheck\nfake output of typecheck\n"
    assert log_of(rig, "fast").read_text(encoding="utf-8").startswith(expected)
    run_check(rig, "fast")
    text = log_of(rig, "fast").read_text(encoding="utf-8")
    assert text.count("$ make lint") == 1
    assert text.endswith("$ make caps\nfake output of caps\n")


def test_a_stamp_is_written_for_the_tree_that_was_tested(rig: Rig) -> None:
    other = rig.tree()
    rig.git("commit", "-q", "--allow-empty", "-m", "chore: empty")
    run_check(rig, "fast")
    assert rig.stamped("fast", rig.tree())
    assert rig.tree() == other


# --------------------------------------------------------------------------- failures


def test_the_first_failing_step_ends_the_check_with_its_code(rig: Rig) -> None:
    rig.runner.codes["typecheck"] = 2
    assert run_check(rig, "fast") == 2
    assert rig.runner.labels == ["lint", "typecheck"]
    assert not rig.stamped("fast", rig.tree())
    assert rig.text.endswith(f"gate: FAILED fast (exit 2); log: {log_of(rig, 'fast')}\n")
    assert "ok in" not in rig.text


def test_a_failed_check_leaves_an_earlier_stamp_alone(rig: Rig) -> None:
    run_check(rig, "fast")
    before = rig.gate.store.path("fast", rig.tree()).read_text(encoding="utf-8")
    rig.runner.codes["lint"] = 1
    assert run_check(rig, "fast") == 1
    assert rig.gate.store.path("fast", rig.tree()).read_text(encoding="utf-8") == before


@pytest.mark.parametrize("code", [1, 2, 127, 130, 255])
def test_the_exit_code_of_the_failing_step_is_what_comes_back(rig: Rig, code: int) -> None:
    rig.runner.codes["lint"] = code
    assert run_check(rig, "fast") == code
    assert f"(exit {code})" in rig.text


# --------------------------------------------------------------------------- the tree must not move


def test_a_file_created_during_the_run_voids_the_stamp(rig: Rig) -> None:
    def litter() -> None:
        (rig.root / "generated.txt").write_text("x\n", encoding="utf-8")

    rig.runner.effects["caps"] = litter
    assert run_check(rig, "fast") == 1
    assert not rig.stamped("fast", rig.tree())
    expected = (
        "gate: FAILED fast: the working tree changed while it ran, no stamp written; "
        f"log: {log_of(rig, 'fast')}"
    )
    assert rig.text.splitlines()[-1] == expected


def test_a_tracked_file_edited_during_the_run_voids_the_stamp(rig: Rig) -> None:
    rig.runner.effects["lint"] = lambda: (rig.root / "a.txt").write_text(
        "edited\n", encoding="utf-8"
    )
    assert run_check(rig, "fast") == 1
    assert not rig.stamped("fast", rig.tree())


def test_a_commit_that_moves_the_tree_during_the_run_voids_the_stamp(rig: Rig) -> None:
    before = rig.tree()

    def commit_a_file() -> None:
        (rig.root / "b.txt").write_text("b\n", encoding="utf-8")
        rig.git("add", "b.txt")
        rig.git("commit", "-q", "-m", "feat: b")

    rig.runner.effects["typecheck"] = commit_a_file
    assert run_check(rig, "fast") == 1
    assert not rig.stamped("fast", before)
    assert not rig.stamped("fast", rig.tree())
    assert "the working tree changed while it ran" in rig.text


def test_a_commit_that_keeps_the_tree_does_not_void_the_stamp(rig: Rig) -> None:
    tree = rig.tree()
    rig.runner.effects["lint"] = lambda: rig.git("commit", "-q", "--allow-empty", "-m", "chore: x")
    assert run_check(rig, "fast") == 0
    assert rig.stamped("fast", tree)


def test_a_change_that_is_undone_before_the_end_does_not_void_the_stamp(rig: Rig) -> None:
    path = rig.root / "scratch.txt"
    rig.runner.effects["lint"] = lambda: path.write_text("tmp\n", encoding="utf-8")
    rig.runner.effects["caps"] = path.unlink
    assert run_check(rig, "fast") == 0
    assert rig.stamped("fast", rig.tree())


def test_a_target_that_may_not_be_stamped_runs_and_passes_without_a_stamp(rig: Rig) -> None:
    target = ex.Target(rig.tree(), lambda: Snapshot(rig.tree(), ()), False, "because I said so")
    assert run_check(rig, "fast", target) == 0
    assert not rig.stamped("fast", rig.tree())
    assert rig.text.endswith("gate: fast: ok in 14.0s (not stamped: because I said so)\n")
    assert not rig.gate.store.base.exists()


def test_the_run_is_judged_against_what_the_target_saw_before_it_started(rig: Rig) -> None:
    states = iter([Snapshot("a", ()), Snapshot("a", ())])
    target = ex.Target(rig.tree(), lambda: next(states))
    assert run_check(rig, "fast", target) == 0
    states = iter([Snapshot("a", ()), Snapshot("b", ())])
    target = ex.Target(rig.tree(), lambda: next(states))
    assert run_check(rig, "fast", target) == 1
