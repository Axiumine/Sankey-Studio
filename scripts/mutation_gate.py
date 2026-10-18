# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Quality gate for mutmut: fail when the mutation score is below a threshold.

``mutmut run`` stores one ``<module>.py.meta`` JSON file per mutated module under ``mutants/``.
Each holds ``exit_code_by_key`` (mutant name -> exit code of the test run that judged it). The
codes are folded into four buckets the same way ``mutmut.stats.status_by_exit_code`` names them
(``tests/test_mutation_gate.py`` compares both tables, so a mutmut upgrade that renumbers a
code fails a test instead of silently skewing the score):

* **killed**: a test failed (1, 3), the run timed out (36, 24, -24, 152, 255), crashed the
  interpreter (-11, -9) or the type checker caught the mutant (37). The mutant was detected.
* **survived**: all tests passed (0), no test reaches the mutated code (5, 33) or the code is
  unknown / "suspicious" (35 and any other). An untested line is a hole, so it counts here.
* **skipped**: excluded by mutmut itself (34). Not part of the score.
* **unchecked**: never judged (``null``) or interrupted (2). The run is incomplete: the gate
  fails whatever the score, because the missing mutants could be the surviving ones.

Score = killed / (killed + survived). Exit codes: 0 pass, 1 score below the minimum,
2 nothing to judge (no ``mutants/`` dir, no ``.meta`` file, unreadable file), 3 unchecked mutants.

    uv run python scripts/mutation_gate.py --min-score 95 [--by-module]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

KILLED = frozenset({1, 3, 36, 24, -24, 152, 255, -11, -9, 37})
SURVIVED = frozenset({0, 5, 33, 35})
SKIPPED = frozenset({34})
UNCHECKED = frozenset({None, 2})

DEFAULT_MIN_SCORE = 95.0

EXIT_PASS = 0
EXIT_LOW_SCORE = 1
EXIT_NO_DATA = 2
EXIT_UNCHECKED = 3


@dataclass(slots=True)
class Tally:
    """Mutant counts of one module (or of the whole run)."""

    killed: int = 0
    survived: int = 0
    skipped: int = 0
    unchecked: int = 0

    def add(self, code: int | None) -> None:
        """Count one mutant by its exit code; an unknown code is a survivor (fail closed)."""
        if code in KILLED:
            self.killed += 1
        elif code in SKIPPED:
            self.skipped += 1
        elif code in UNCHECKED:
            self.unchecked += 1
        else:
            self.survived += 1

    def merge(self, other: Tally) -> None:
        self.killed += other.killed
        self.survived += other.survived
        self.skipped += other.skipped
        self.unchecked += other.unchecked

    @property
    def count(self) -> int:
        return self.judged + self.skipped + self.unchecked

    @property
    def judged(self) -> int:
        return self.killed + self.survived

    @property
    def score(self) -> float:
        """Percent of judged mutants that were killed (100.0 when none was judged)."""
        return 100.0 if self.judged == 0 else 100.0 * self.killed / self.judged

    def describe(self) -> str:
        return (
            f"killed={self.killed} survived={self.survived} skipped={self.skipped} "
            f"unchecked={self.unchecked} score={self.score:.1f}%"
        )


def read_meta(meta_file: Path) -> Tally:
    """Tally one ``*.meta`` file. Raises ``ValueError`` when it is not a mutmut meta file."""
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        codes = data["exit_code_by_key"].values()
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"{meta_file}: not a mutmut meta file ({type(exc).__name__})") from None
    tally = Tally()
    for code in codes:
        tally.add(code)
    return tally


def collect(meta_dir: Path) -> dict[str, Tally]:
    """``{mutated source file: Tally}`` for every ``*.meta`` file under ``meta_dir``."""
    out: dict[str, Tally] = {}
    for meta_file in sorted(meta_dir.rglob("*.meta")):
        name = meta_file.relative_to(meta_dir).as_posix().removesuffix(".meta")
        out[name] = read_meta(meta_file)
    return out


def total(per_module: dict[str, Tally]) -> Tally:
    overall = Tally()
    for tally in per_module.values():
        overall.merge(tally)
    return overall


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--meta-dir", type=Path, default=Path("mutants"))
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--by-module", action="store_true", help="print one line per module")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.meta_dir.is_dir():
        print(f"{args.meta_dir} not found: run `make mutate` first", file=sys.stderr)
        return EXIT_NO_DATA
    try:
        per_module = collect(args.meta_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return EXIT_NO_DATA
    overall = total(per_module)
    if args.by_module:
        for name, tally in per_module.items():
            if tally.count:  # modules without a single mutant would only add noise
                print(f"{name}: {tally.describe()}")
    if overall.judged == 0 and overall.unchecked == 0:
        print(f"no mutants found under {args.meta_dir}: run `make mutate` first", file=sys.stderr)
        return EXIT_NO_DATA
    print(f"mutants: {overall.describe()} (min {args.min_score:.1f}%)")
    if overall.unchecked:
        print(
            f"{overall.unchecked} mutants were never judged: rerun `make mutate`", file=sys.stderr
        )
        return EXIT_UNCHECKED
    return EXIT_PASS if overall.score >= args.min_score else EXIT_LOW_SCORE


if __name__ == "__main__":
    sys.exit(main())
