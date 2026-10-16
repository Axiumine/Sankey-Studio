# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Tests for the mutation-score gate (scripts/mutation_gate.py).

The meta files are written with mutmut's own ``SourceFileMutationData.save()`` and the exit-code
table is compared with ``mutmut.stats.status_by_exit_code``, so the gate cannot drift from the
tool it reads.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from mutmut.mutation.data import SourceFileMutationData
from mutmut.stats import status_by_exit_code
from scripts import mutation_gate as gate

if TYPE_CHECKING:
    from collections.abc import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent

BUCKET_OF_STATUS = {
    "killed": "killed",
    "timeout": "killed",
    "segfault": "killed",
    "caught by type check": "killed",
    "survived": "survived",
    "no tests": "survived",
    "suspicious": "survived",
    "skipped": "skipped",
    "not checked": "unchecked",
    "check was interrupted by user": "unchecked",
}


def bucket_of(code: int | None) -> str:
    tally = gate.Tally()
    tally.add(code)
    return next(
        name for name in ("killed", "survived", "skipped", "unchecked") if getattr(tally, name)
    )


def write_meta(root: Path, module: str, codes: Sequence[int | None]) -> None:
    """Write ``mutants/<module>.meta`` exactly as mutmut does, with one mutant per code."""
    (root / "mutants" / Path(module).parent).mkdir(parents=True, exist_ok=True)
    data = SourceFileMutationData(path=module)
    stem = module.removesuffix(".py").replace("/", ".")
    data.exit_code_by_key = {f"{stem}.x_f__mutmut_{i}": code for i, code in enumerate(codes, 1)}
    data.durations_by_key = dict.fromkeys(data.exit_code_by_key, 0.01)
    data.estimated_time_of_tests_by_mutant = dict.fromkeys(data.exit_code_by_key, 0.01)
    data.save()


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty project dir that is the cwd (mutmut writes to ``./mutants``)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- classification


@pytest.mark.parametrize("code", sorted(status_by_exit_code, key=lambda c: (c is None, c or 0)))
def test_every_code_is_bucketed_like_mutmut_names_it(code: int | None) -> None:
    assert bucket_of(code) == BUCKET_OF_STATUS[status_by_exit_code[code]]


def test_the_status_names_are_all_known() -> None:
    assert set(status_by_exit_code.values()) <= set(BUCKET_OF_STATUS)


@pytest.mark.parametrize("code", [-1, 4, 6, 7, 32, 38, 42, 100, 127, 128, 130, 139, 999, -15])
def test_unknown_codes_fail_closed_as_survivors(code: int) -> None:
    assert status_by_exit_code[code] == "suspicious"
    assert bucket_of(code) == "survived"


def test_the_code_sets_do_not_overlap() -> None:
    sets = [gate.KILLED, gate.SURVIVED, gate.SKIPPED, gate.UNCHECKED]
    union = set().union(*sets)
    assert sum(len(s) for s in sets) == len(union)


def test_tally_arithmetic() -> None:
    empty = gate.Tally()
    assert (empty.judged, empty.count, empty.score) == (0, 0, 100.0)
    tally = gate.Tally(killed=9, survived=1, skipped=5, unchecked=2)
    assert (tally.judged, tally.count, tally.score) == (10, 17, 90.0)
    tally.merge(gate.Tally(killed=1, survived=1, skipped=1, unchecked=1))
    assert tally == gate.Tally(killed=10, survived=2, skipped=6, unchecked=3)
    assert tally.describe() == "killed=10 survived=2 skipped=6 unchecked=3 score=83.3%"
    assert gate.Tally(survived=3).score == 0.0


# --------------------------------------------------------------------------- reading meta files


def test_collect_reads_what_mutmut_writes(workdir: Path) -> None:
    write_meta(workdir, "src/pkg/a.py", [1, 1, 0, 34])
    write_meta(workdir, "src/pkg/sub/b.py", [3, 36, 5, None])
    per_module = gate.collect(workdir / "mutants")
    assert per_module == {
        "src/pkg/a.py": gate.Tally(killed=2, survived=1, skipped=1),
        "src/pkg/sub/b.py": gate.Tally(killed=2, survived=1, unchecked=1),
    }
    assert gate.total(per_module) == gate.Tally(killed=4, survived=2, skipped=1, unchecked=1)


def test_mutmut_can_read_back_what_the_gate_counts(workdir: Path) -> None:
    write_meta(workdir, "src/pkg/a.py", [1, 0, 2])
    data = SourceFileMutationData(path="src/pkg/a.py")
    data.load()
    assert list(data.exit_code_by_key.values()) == [1, 0, 2]
    assert gate.read_meta(workdir / "mutants/src/pkg/a.py.meta") == gate.Tally(
        killed=1, survived=1, unchecked=1
    )


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[]", "{}", '{"exit_code_by_key": null}', '{"exit_code_by_key": [1]}'],
)
def test_a_file_that_is_not_a_meta_file_is_refused(workdir: Path, text: str) -> None:
    meta = workdir / "x.py.meta"
    meta.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=r"x\.py\.meta: not a mutmut meta file"):
        gate.read_meta(meta)


def test_a_missing_file_is_refused(workdir: Path) -> None:
    with pytest.raises(ValueError, match="not a mutmut meta file"):
        gate.read_meta(workdir / "nope.meta")


# --------------------------------------------------------------------------- main


def run_main(*args: str) -> int:
    return gate.main(list(args))


def test_the_default_threshold_is_ninety_percent() -> None:
    assert gate.DEFAULT_MIN_SCORE == 90.0
    assert gate.build_parser().parse_args([]).min_score == 90.0
    assert gate.build_parser().parse_args([]).meta_dir == Path("mutants")


def test_main_passes_at_exactly_the_minimum(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_meta(workdir, "src/a.py", [1] * 9 + [0])
    assert run_main() == gate.EXIT_PASS
    assert capsys.readouterr().out == (
        "mutants: killed=9 survived=1 skipped=0 unchecked=0 score=90.0% (min 90.0%)\n"
    )


def test_main_fails_below_the_minimum(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_meta(workdir, "src/a.py", [1] * 89 + [0] * 11)
    assert run_main() == gate.EXIT_LOW_SCORE
    assert "score=89.0%" in capsys.readouterr().out


def test_main_min_score_option(workdir: Path) -> None:
    write_meta(workdir, "src/a.py", [1, 0])
    assert run_main("--min-score", "50") == gate.EXIT_PASS
    assert run_main("--min-score", "50.1") == gate.EXIT_LOW_SCORE
    assert run_main("--min-score", "0") == gate.EXIT_PASS


def test_timeouts_and_type_check_catches_count_as_killed(workdir: Path) -> None:
    write_meta(workdir, "src/a.py", [1, 3, 36, -24, 24, 152, 255, -11, -9, 37])
    assert gate.total(gate.collect(workdir / "mutants")) == gate.Tally(killed=10)
    assert run_main("--min-score", "100") == gate.EXIT_PASS


def test_untested_and_suspicious_mutants_count_as_survivors(workdir: Path) -> None:
    write_meta(workdir, "src/a.py", [1, 5, 33, 35, 77])
    assert gate.total(gate.collect(workdir / "mutants")) == gate.Tally(killed=1, survived=4)
    assert run_main("--min-score", "20") == gate.EXIT_PASS
    assert run_main("--min-score", "21") == gate.EXIT_LOW_SCORE


def test_skipped_mutants_are_not_part_of_the_score(workdir: Path) -> None:
    write_meta(workdir, "src/a.py", [1, 34, 34, 34])
    assert run_main("--min-score", "100") == gate.EXIT_PASS


def test_unchecked_mutants_fail_the_gate_whatever_the_score(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_meta(workdir, "src/a.py", [1] * 50)
    write_meta(workdir, "src/b.py", [None])
    assert run_main("--min-score", "0") == gate.EXIT_UNCHECKED
    captured = capsys.readouterr()
    assert "unchecked=1" in captured.out
    assert "1 mutants were never judged" in captured.err


def test_an_interrupted_run_is_unchecked(workdir: Path) -> None:
    write_meta(workdir, "src/a.py", [1, 2])
    assert run_main() == gate.EXIT_UNCHECKED


def test_only_unchecked_mutants_is_still_an_incomplete_run(workdir: Path) -> None:
    write_meta(workdir, "src/a.py", [None, None])
    assert run_main() == gate.EXIT_UNCHECKED


def test_missing_mutants_dir_is_reported(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_main() == gate.EXIT_NO_DATA
    assert "mutants not found: run `make mutate` first" in capsys.readouterr().err
    assert run_main("--meta-dir", str(workdir / "elsewhere")) == gate.EXIT_NO_DATA


def test_a_dir_without_mutants_is_not_a_pass(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (workdir / "mutants").mkdir()
    assert run_main() == gate.EXIT_NO_DATA
    assert "no mutants found under mutants" in capsys.readouterr().err
    write_meta(workdir, "src/a.py", [])
    assert run_main() == gate.EXIT_NO_DATA
    write_meta(workdir, "src/a.py", [34])
    assert run_main() == gate.EXIT_NO_DATA


def test_a_corrupt_meta_file_is_reported_not_raised(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_meta(workdir, "src/a.py", [1])
    (workdir / "mutants/src/b.py.meta").write_text("{", encoding="utf-8")
    assert run_main() == gate.EXIT_NO_DATA
    assert "b.py.meta: not a mutmut meta file (JSONDecodeError)" in capsys.readouterr().err


def test_by_module_prints_one_line_per_file(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_meta(workdir, "src/pkg/a.py", [1, 1, 0])
    write_meta(workdir, "src/pkg/b.py", [1])
    write_meta(workdir, "src/pkg/empty.py", [])
    assert run_main("--by-module", "--min-score", "0") == gate.EXIT_PASS
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "src/pkg/a.py: killed=2 survived=1 skipped=0 unchecked=0 score=66.7%",
        "src/pkg/b.py: killed=1 survived=0 skipped=0 unchecked=0 score=100.0%",
        "mutants: killed=3 survived=1 skipped=0 unchecked=0 score=75.0% (min 0.0%)",
    ]


def test_meta_files_in_nested_directories_are_found(workdir: Path) -> None:
    write_meta(workdir, "src/a/b/c/d.py", [1, 1])
    assert run_main("--min-score", "100") == gate.EXIT_PASS


def test_the_script_runs_as_a_program(workdir: Path) -> None:
    write_meta(workdir, "src/a.py", [1, 0])
    command = [sys.executable, str(REPO_ROOT / "scripts" / "mutation_gate.py")]
    failing = subprocess.run(  # noqa: S603 - fixed argv
        [*command, "--min-score", "90"], cwd=workdir, capture_output=True, text=True, check=False
    )
    assert failing.returncode == gate.EXIT_LOW_SCORE
    assert "score=50.0%" in failing.stdout
    passing = subprocess.run(  # noqa: S603 - fixed argv
        [*command, "--min-score", "50"], cwd=workdir, capture_output=True, text=True, check=False
    )
    assert passing.returncode == gate.EXIT_PASS
