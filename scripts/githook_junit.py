"""Fail-closed reading of the JUnit reports a pytest-based check leaves behind.

The reports are machine-written by pytest, and a skipped test must fail a gate (a skip is how
a missing browser, node or Mongo turns a red check green). No XML parser is imported on purpose:
the semgrep ``use-defused-xml`` rule flags every ``xml.*`` import in ``scripts/``, and pytest's
output makes tags exact, because ``<`` inside attribute values and text is always escaped as
``&lt;``. A literal ``<skipped`` or ``<testcase`` is therefore a real element.

A report problem is any of: no report file, an unterminated report (pytest was killed), no
testcase at all, a skipped testcase whose reason does not contain an allowed fragment.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

MAX_LISTED: Final = 20
SKIPPED_TAG: Final = re.compile(r"<skipped\b([^>]*)>")
NAME_ATTR: Final = re.compile(r'\bname="([^"]*)"')
CLASS_ATTR: Final = re.compile(r'\bclassname="([^"]*)"')
MESSAGE_ATTR: Final = re.compile(r'\bmessage="([^"]*)"')
CLOSING: Final = ("</testsuites>", "</testsuite>")


@dataclass(frozen=True, slots=True)
class JunitVerdict:
    tests: int
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def _attr(pattern: re.Pattern[str], text: str) -> str:
    found = pattern.search(text)
    return found.group(1) if found else ""


def _scan_report(name: str, text: str, allow: tuple[str, ...]) -> tuple[int, list[str]]:
    """Testcase count and the problems of one report."""
    problems = []
    if not text.rstrip().endswith(CLOSING):
        problems.append(f"{name}: report is not terminated (pytest was cut off)")
    cases = text.split("<testcase")[1:]
    for case in cases:
        head = case.partition(">")[0]
        skipped = SKIPPED_TAG.search(case)
        if skipped is None:
            continue
        reason = html.unescape(_attr(MESSAGE_ATTR, skipped.group(1)))
        if not any(fragment in reason for fragment in allow):
            test = f"{_attr(CLASS_ATTR, head)}::{_attr(NAME_ATTR, head)}"
            problems.append(f"skipped test {test} ({reason or 'no reason'})")
    return len(cases), problems


def check_reports(directory: Path, allow: tuple[str, ...] = ()) -> JunitVerdict:
    """Verify every ``*.xml`` report below ``directory`` (one per shard or selection)."""
    reports = sorted(directory.glob("*.xml")) if directory.is_dir() else []
    if not reports:
        return JunitVerdict(0, (f"no junit report was written to {directory}",))
    total = 0
    problems: list[str] = []
    for report in reports:
        text = report.read_text(encoding="utf-8", errors="replace")
        count, found = _scan_report(report.name, text, allow)
        total += count
        problems.extend(found)
    if total == 0:
        problems.append("the junit reports hold no testcase (nothing ran)")
    if len(problems) > MAX_LISTED:
        problems = [*problems[:MAX_LISTED], f"... and {len(problems) - MAX_LISTED} more"]
    return JunitVerdict(total, tuple(problems))
