"""The command line of the gate (scripts/githook_gate.py): parser, dispatch, exit codes, wiring."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from scripts import githook_gate as cli
from scripts.githook_exec import Gate
from scripts.githook_plan import CHECK_ORDER
from scripts.githook_runner import GateInterruptedError, SubprocessRunner

from tests.githook_support import (
    REPO_ROOT,
    ZERO,
    Case,
    Rig,
    case_id,
    commit_file,
    make_rig,
    push_line,
)

if TYPE_CHECKING:
    from pathlib import Path

FAST = ["lint", "typecheck", "caps"]


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def run_main(rig: Rig, *argv: str, stdin: str = "") -> int:
    return cli.main(list(argv), gate=rig.gate, stdin=io.StringIO(stdin))


# --------------------------------------------------------------------------- the parser


def test_the_parser_is_named_after_the_script_and_describes_itself_with_the_module_doc() -> None:
    parser = cli.build_parser()
    assert parser.prog == "githook_gate"
    assert parser.description == cli.__doc__
    assert "pre-push [remote [url]]" in (cli.__doc__ or "")


PARSED = [
    Case(["pre-commit"], {"command": "pre-commit"}, "pre-commit"),
    Case(["pre-merge-commit"], {"command": "pre-merge-commit"}, "pre-merge-commit"),
    Case(["pre-push"], {"command": "pre-push", "remote": "origin", "url": ""}, "default remote"),
    Case(
        ["pre-push", "upstream", "git@host:r.git"],
        {"remote": "upstream", "url": "git@host:r.git"},
        "remote and url",
    ),
    Case(["run", "cov"], {"command": "run", "names": ["cov"], "force": False}, "run"),
    Case(
        ["run", "fast", "cov", "--force"],
        {"names": ["fast", "cov"], "force": True},
        "run several, forced",
    ),
    Case(["run", "--force", "push"], {"names": ["push"], "force": True}, "force first"),
    Case(
        ["plan", "pre-push", "origin"], {"command": "plan", "names": ["pre-push", "origin"]}, "plan"
    ),
    Case(["hooks-check"], {"command": "hooks-check"}, "hooks-check"),
]


@pytest.mark.parametrize("case", PARSED, ids=case_id)
def test_the_parser_reads_every_command(case: Case[list[str], dict[str, object]]) -> None:
    args = vars(cli.build_parser().parse_args(case.given))
    assert {key: args[key] for key in case.expected} == case.expected


USAGE = [
    Case([], 2, "no command"),
    Case(["nope"], 2, "unknown command"),
    Case(["run"], 2, "run without names"),
    Case(["plan"], 2, "plan without names"),
    Case(["run", "--nope", "cov"], 2, "unknown option"),
    Case(["hooks-check", "extra"], 2, "extra argument"),
    Case(["pre-commit", "extra"], 2, "pre-commit takes no argument here"),
    Case(["pre-push", "a", "b", "c"], 2, "too many arguments"),
]


@pytest.mark.parametrize("case", USAGE, ids=case_id)
def test_a_usage_error_exits_with_two_before_anything_else_happens(
    rig: Rig, case: Case[list[str], int]
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(case.given, gate=rig.gate)
    assert caught.value.code == case.expected
    assert rig.runner.calls == []


# --------------------------------------------------------------------------- exit codes


def test_a_passing_hook_exits_zero_and_leaves_a_stamp(rig: Rig) -> None:
    assert run_main(rig, "pre-commit") == 0
    assert rig.runner.labels == FAST
    assert rig.stamped("fast", rig.tree())


def test_a_failing_check_exits_one_whatever_its_own_code(rig: Rig) -> None:
    rig.runner.codes["typecheck"] = 2
    assert run_main(rig, "pre-commit") == 1
    assert "gate: FAILED fast (exit 2)" in rig.text
    assert "gate: commit refused: fast failed (exit 2)" in rig.text


def test_pre_merge_commit_is_the_same_gate_as_pre_commit(rig: Rig) -> None:
    assert run_main(rig, "pre-merge-commit") == 0
    assert rig.runner.labels == FAST


def test_run_executes_the_named_tier_on_head(rig: Rig) -> None:
    assert run_main(rig, "run", "commit") == 0
    assert rig.runner.labels == FAST
    assert run_main(rig, "run", "commit") == 0
    assert rig.runner.labels == FAST
    assert run_main(rig, "run", "commit", "--force") == 0
    assert rig.runner.labels == FAST * 2


def test_pre_push_reads_the_ref_lines_from_stdin(rig: Rig) -> None:
    rig.git("checkout", "-q", "-b", "feature")
    sha = commit_file(rig.root, "f.txt", "f\n", "feat: f")
    text = push_line("refs/heads/feature", sha, "refs/heads/feature")
    assert run_main(rig, "pre-push", "origin", "https://x.invalid/r.git", stdin=text) == 0
    assert rig.runner.labels == [*FAST, "cov", "memray", "e2e"]


def test_pre_push_passes_the_remote_name_to_the_message_check(rig: Rig) -> None:
    rig.git("config", "remote.upstream.url", "https://example.invalid/r.git")
    rig.git("update-ref", "refs/remotes/upstream/main", rig.git("rev-parse", "HEAD"))
    rig.git("checkout", "-q", "-b", "feature")
    sha = commit_file(rig.root, "f.txt", "f\n", "bad subject")
    text = push_line("refs/heads/feature", sha, "refs/heads/feature")
    assert run_main(rig, "pre-push", "upstream", stdin=text) == 1
    assert rig.judge.seen == ["bad subject"]
    assert rig.runner.calls == []


def test_pre_push_without_refs_exits_zero(rig: Rig) -> None:
    assert run_main(rig, "pre-push", stdin="") == 0
    assert rig.text == "gate: nothing to check, no ref is created or updated\n"


def test_the_default_input_is_the_standard_input(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    sha = rig.git("rev-parse", "HEAD")
    line = push_line("refs/heads/main", sha, "refs/heads/main", ZERO)
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"(delete) {ZERO} refs/heads/x {sha}\n" + line))
    rig.stamp_all(CHECK_ORDER, rig.tree())
    assert cli.main(["pre-push"], gate=rig.gate) == 0
    assert "every required check has a stamp" in rig.text


# --------------------------------------------------------------------------- plan and hooks-check


def test_plan_of_checks_and_tiers_prints_and_exits_zero(rig: Rig) -> None:
    assert run_main(rig, "plan", "push") == 0
    tree12 = rig.tree()[:12]
    assert rig.text.splitlines()[0] == f"plan: run push tree={tree12}"
    assert rig.runner.calls == []


@pytest.mark.parametrize("hook", ["pre-commit", "pre-merge-commit"])
def test_plan_of_a_commit_hook_describes_the_index_tree(rig: Rig, hook: str) -> None:
    assert run_main(rig, "plan", hook) == 0
    assert rig.text == f"plan: {hook} tree={rig.tree()[:12]}\nplan:   fast RUN\n"


def test_plan_of_pre_push_reads_stdin_and_always_exits_zero(rig: Rig) -> None:
    rig.git("checkout", "-q", "-b", "feature")
    sha = commit_file(rig.root, "f.txt", "f\n", "feat: f")
    text = push_line("refs/heads/feature", sha, "refs/heads/main")
    assert run_main(rig, "plan", "pre-push", stdin=text) == 0
    assert "tier=release" in rig.text
    assert "gate: dry run" in rig.text
    assert rig.runner.calls == []
    assert rig.judge.seen == ["feat: f", "chore: first commit"]


def test_plan_of_pre_push_reports_a_refused_message_but_still_exits_zero(rig: Rig) -> None:
    rig.git("checkout", "-q", "-b", "feature")
    sha = commit_file(rig.root, "f.txt", "f\n", "bad subject")
    text = push_line("refs/heads/feature", sha, "refs/heads/feature")
    assert run_main(rig, "plan", "pre-push", stdin=text) == 0
    assert f"gate: commit message of {sha[:12]} is refused by .githooks/commit-msg:" in rig.text
    assert "gate: dry run: 4 check(s) would run, nothing was run" in rig.text


def test_plan_of_pre_push_takes_an_optional_remote_name(rig: Rig) -> None:
    rig.git("config", "remote.mirror.url", "https://example.invalid/m.git")
    assert run_main(rig, "plan", "pre-push", "mirror", stdin="") == 0
    assert rig.text == "gate: nothing to check, no ref is created or updated\n"


def test_plan_ignores_the_dry_run_switch_and_still_runs_nothing(rig: Rig) -> None:
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "0"}
    assert run_main(rig, "plan", "fast") == 0
    assert rig.runner.calls == []


def test_a_plan_with_an_unknown_name_is_refused(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(rig, "plan", "nope") == 1
    assert "gate: refusing: unknown check or tier 'nope'" in capsys.readouterr().err


def test_hooks_check_reports_through_the_gate_output(rig: Rig) -> None:
    assert run_main(rig, "hooks-check") == 1
    assert rig.text.startswith("hooks-check: FAIL core.hooksPath is None")


# --------------------------------------------------------------------------- failures of the gate


def test_an_unknown_check_name_is_refused_with_the_valid_names(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(rig, "run", "nope") == 1
    err = capsys.readouterr().err
    assert err == (
        "gate: refusing: unknown check or tier 'nope'; use one of: fast, cov, memray, e2e, "
        "security, e2e-mongo, qodana, mutation, commit, push, main, release\n"
    )
    assert rig.runner.calls == []


def test_a_malformed_push_line_is_refused(rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_main(rig, "pre-push", stdin="only three fields\n") == 1
    assert capsys.readouterr().err.startswith("gate: refusing: malformed pre-push line: ")


def test_a_git_failure_is_refused_and_not_a_traceback(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    line = push_line("refs/heads/x", "1" * 40, "refs/heads/x")
    assert run_main(rig, "pre-push", stdin=line) == 1
    err = capsys.readouterr().err
    assert err.startswith("gate: refusing: git ")
    assert "failed:" in err
    assert "Traceback" not in err


def test_a_signal_ends_the_gate_with_128_plus_the_signal(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    def stop() -> None:
        raise GateInterruptedError(signal.SIGTERM)

    rig.runner.effects["lint"] = stop
    assert run_main(rig, "pre-commit") == 128 + signal.SIGTERM
    assert capsys.readouterr().err == (
        "gate: interrupted (signal 15); no stamp written for the running check\n"
    )
    assert not rig.stamped("fast", rig.tree())


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGHUP, signal.SIGTERM])
def test_every_forwarded_signal_gives_its_own_exit_code(
    rig: Rig, signum: signal.Signals, capsys: pytest.CaptureFixture[str]
) -> None:
    def stop() -> None:
        raise GateInterruptedError(signum)

    rig.runner.effects["lint"] = stop
    assert run_main(rig, "pre-commit") == 128 + signum
    assert f"(signal {int(signum)})" in capsys.readouterr().err


def test_a_crash_of_the_gate_itself_is_never_turned_into_a_pass(rig: Rig) -> None:
    def crash() -> None:
        raise ZeroDivisionError("bug in the gate")

    rig.runner.effects["lint"] = crash
    with pytest.raises(ZeroDivisionError):
        run_main(rig, "pre-commit")
    assert not rig.stamped("fast", rig.tree())


def test_the_dry_run_cannot_be_used_to_get_past_a_hook(rig: Rig) -> None:
    rig.gate.environ = {"SANKEY_GATE_DRY_RUN": "1"}
    assert run_main(rig, "pre-commit") == 1
    assert rig.runner.calls == []
    rig.stamp("fast", rig.tree())
    assert run_main(rig, "pre-commit") == 0


# --------------------------------------------------------------------------- the real gate


def test_make_gate_builds_the_real_gate_for_the_repository_of_the_working_directory(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(rig.root)
    monkeypatch.setenv("SANKEY_GATE_PROBE", "1")
    gate = cli.make_gate("pre-commit")
    assert isinstance(gate, Gate)
    assert isinstance(gate.runner, SubprocessRunner)
    assert gate.repo.root == rig.root
    assert gate.label == "pre-commit"
    assert gate.environ["SANKEY_GATE_PROBE"] == "1"


@pytest.mark.parametrize(
    ("command", "stream"),
    [
        ("plan", "stdout"),
        ("hooks-check", "stdout"),
        ("pre-commit", "stderr"),
        ("pre-merge-commit", "stderr"),
        ("pre-push", "stderr"),
        ("run", "stderr"),
    ],
)
def test_only_plan_and_hooks_check_talk_on_standard_output(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, command: str, stream: str
) -> None:
    monkeypatch.chdir(rig.root)
    assert cli.make_gate(command).out is getattr(sys, stream)


def test_main_builds_the_real_gate_when_none_is_given(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(rig.root)
    assert cli.main(["plan", "fast"]) == 0
    assert capsys.readouterr().out == f"plan: run fast tree={rig.tree()[:12]}\nplan:   fast RUN\n"


def test_a_real_dry_run_of_a_hook_runs_nothing_and_fails_with_work_pending(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(rig.root)
    monkeypatch.setenv("SANKEY_GATE_DRY_RUN", "1")
    assert cli.main(["pre-commit"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "gate: dry run: 1 check(s) would run, nothing was run" in captured.err


def test_outside_a_repository_the_gate_refuses_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    monkeypatch.chdir(folder)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert cli.main(["pre-commit"]) == 1
    assert capsys.readouterr().err.startswith("gate: refusing: git ")


# --------------------------------------------------------------------------- run as a script


def python_in(rig: Rig, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the gate module the way the hook shims do (``python -m``), in the repository."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "SANKEY_"))}
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(  # noqa: S603 - fixed argv, the module only reads the repository
        [sys.executable, *args], cwd=rig.root, env=env, capture_output=True, text=True, check=False
    )


def test_the_module_runs_as_a_script_and_exits_with_the_status_of_main(rig: Rig) -> None:
    done = python_in(rig, "-m", "scripts.githook_gate", "hooks-check")
    assert done.returncode == 1
    assert done.stdout.startswith("hooks-check: FAIL core.hooksPath is None")
    assert done.stderr == ""


def test_the_script_reports_a_usage_error_with_status_two(rig: Rig) -> None:
    done = python_in(rig, "-m", "scripts.githook_gate")
    assert done.returncode == 2
    assert "usage: githook_gate" in done.stderr


def test_the_script_turns_termination_signals_into_the_gate_interrupt(rig: Rig) -> None:
    probe = (
        "import runpy, signal, sys\n"
        "sys.argv = ['githook_gate', 'hooks-check']\n"
        "try:\n"
        "    runpy.run_module('scripts.githook_gate', run_name='__main__')\n"
        "except SystemExit as stop:\n"
        "    print('exit', stop.code)\n"
        "print(signal.getsignal(signal.SIGTERM).__name__)\n"
    )
    done = python_in(rig, "-c", probe)
    assert done.stdout.splitlines()[-2:] == ["exit 1", "raise_interrupt"]
