"""Fail-closed reading of JUnit reports (scripts/githook_junit.py): a skip or a gap fails a gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts import githook_junit as junit

from tests.githook_support import junit_xml

MONGO = "SANKEY_TEST_MONGO_URI"


@dataclass(frozen=True)
class Report:
    """Reports to write into a directory and what reading them must give."""

    files: dict[str, str]
    allow: tuple[str, ...] = ()
    tests: int = 0
    problems: tuple[str, ...] = ()
    name: str = ""


def skipped_problem(index: int, reason: str, klass: str = "tests.test_skip") -> str:
    return f"skipped test {klass}::test_skip_{index} ({reason})"


def raw_case(body: str, *, closing: str = "</testsuite></testsuites>") -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}{closing}'


REPORTS = [
    Report({"report.xml": junit_xml(3)}, tests=3, name="three passing tests"),
    Report({"a.xml": junit_xml(2), "b.xml": junit_xml(4)}, tests=6, name="two shards add up"),
    Report({"report.xml": junit_xml(1) + "\n\n  "}, tests=1, name="trailing whitespace is fine"),
    Report(
        {"report.xml": raw_case('<testcase name="t"/>', closing="</testsuite>")},
        tests=1,
        name="a lone closing testsuite counts",
    ),
    Report(
        {"report.xml": junit_xml(2, closed=False)},
        tests=2,
        problems=("report.xml: report is not terminated (pytest was cut off)",),
        name="cut off report",
    ),
    Report(
        {"report.xml": ""},
        problems=(
            "report.xml: report is not terminated (pytest was cut off)",
            "the junit reports hold no testcase (nothing ran)",
        ),
        name="empty file",
    ),
    Report(
        {"report.xml": junit_xml(0)},
        problems=("the junit reports hold no testcase (nothing ran)",),
        name="no testcase at all",
    ),
    Report(
        {"a.xml": junit_xml(0), "b.xml": junit_xml(2)},
        tests=2,
        name="one empty shard is fine when another ran",
    ),
    Report(
        {"a.xml": junit_xml(2), "b.xml": junit_xml(1, closed=False)},
        tests=3,
        problems=("b.xml: report is not terminated (pytest was cut off)",),
        name="one cut off shard fails",
    ),
    Report(
        {"report.xml": junit_xml(2, ["no browser"])},
        tests=3,
        problems=(skipped_problem(0, "no browser"),),
        name="a skip fails",
    ),
    Report(
        {"report.xml": junit_xml(1, ["a", "b"])},
        tests=3,
        problems=(skipped_problem(0, "a"), skipped_problem(1, "b")),
        name="every skip is listed",
    ),
    Report(
        {"report.xml": junit_xml(1, ["x < y & \"z\" > 'q'"])},
        tests=2,
        problems=(skipped_problem(0, "x < y & \"z\" > 'q'"),),
        name="the reason is unescaped",
    ),
    Report(
        {"report.xml": junit_xml(0, [MONGO + " is not set"])},
        allow=(MONGO,),
        tests=1,
        name="an allowed reason passes",
    ),
    Report(
        {"report.xml": junit_xml(0, ["needs " + MONGO + " to run", "no chrome"])},
        allow=(MONGO,),
        tests=2,
        problems=(skipped_problem(1, "no chrome"),),
        name="only the allowed reason passes",
    ),
    Report(
        {"report.xml": junit_xml(0, [MONGO.lower()])},
        allow=(MONGO,),
        tests=1,
        problems=(skipped_problem(0, MONGO.lower()),),
        name="the allowed fragment is case sensitive",
    ),
    Report(
        {"report.xml": junit_xml(0, ["a browser is missing"])},
        allow=("x", MONGO, "browser"),
        tests=1,
        name="any of several fragments allows",
    ),
]


@pytest.mark.parametrize("report", REPORTS, ids=[r.name for r in REPORTS])
def test_reports_are_judged_by_skips_terminators_and_testcases(
    tmp_path: Path, report: Report
) -> None:
    for name, text in report.files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    verdict = junit.check_reports(tmp_path, report.allow)
    assert (verdict.tests, verdict.problems) == (report.tests, report.problems)
    assert verdict.ok is (not report.problems)


def test_a_missing_directory_and_an_empty_one_both_mean_no_report(tmp_path: Path) -> None:
    for folder in (tmp_path / "absent", tmp_path):
        verdict = junit.check_reports(folder)
        assert verdict.tests == 0
        assert verdict.problems == (f"no junit report was written to {folder}",)
        assert not verdict.ok


def test_only_xml_files_directly_in_the_directory_are_read(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("<skipped>", encoding="utf-8")
    (tmp_path / "report.xml.bak").write_text(junit_xml(0, ["old"]), encoding="utf-8")
    nested = tmp_path / "step1"
    nested.mkdir()
    (nested / "report.xml").write_text(junit_xml(0, ["nested"]), encoding="utf-8")
    assert junit.check_reports(tmp_path).problems == (f"no junit report was written to {tmp_path}",)
    (tmp_path / "report.xml").write_text(junit_xml(1), encoding="utf-8")
    assert junit.check_reports(tmp_path).ok


def test_a_skip_is_charged_to_its_own_testcase(tmp_path: Path) -> None:
    body = (
        '<testcase classname="pkg.mod" name="test_first" time="0.1"/>'
        '<testcase classname="pkg.mod" name="test_second" time="0.1">'
        '<skipped type="pytest.skip" message="why not">x</skipped></testcase>'
        '<testcase classname="pkg.other" name="test_third" time="0.1"/>'
    )
    (tmp_path / "report.xml").write_text(raw_case(body), encoding="utf-8")
    verdict = junit.check_reports(tmp_path)
    assert verdict.problems == ("skipped test pkg.mod::test_second (why not)",)
    assert verdict.tests == 3


@pytest.mark.parametrize(
    "tag",
    [
        '<skipped type="pytest.skip">text</skipped>',
        '<skipped type="pytest.skip" message="">text</skipped>',
        '<skipped message=""/>',
        "<skipped/>",
    ],
    ids=["no message", "empty message", "self closing empty", "bare"],
)
def test_a_skip_without_a_reason_is_reported_as_such(tmp_path: Path, tag: str) -> None:
    body = f'<testcase classname="c" name="n">{tag}</testcase>'
    (tmp_path / "report.xml").write_text(raw_case(body), encoding="utf-8")
    assert junit.check_reports(tmp_path).problems == ("skipped test c::n (no reason)",)


def test_a_skipped_testcase_with_missing_attributes_is_still_reported(tmp_path: Path) -> None:
    body = '<testcase><skipped message="m"/></testcase>'
    (tmp_path / "report.xml").write_text(raw_case(body), encoding="utf-8")
    assert junit.check_reports(tmp_path).problems == ("skipped test :: (m)",)


def test_a_reason_is_not_confused_with_attributes_of_other_tags(tmp_path: Path) -> None:
    body = (
        '<testcase classname="c" name="n" message="not this one">'
        '<skipped type="pytest.skip" message="the real reason"/></testcase>'
    )
    (tmp_path / "report.xml").write_text(raw_case(body), encoding="utf-8")
    assert junit.check_reports(tmp_path).problems == ("skipped test c::n (the real reason)",)


def test_bytes_that_are_not_utf8_do_not_crash_the_reader(tmp_path: Path) -> None:
    text = junit_xml(1, ["café"]).replace("café", "caf\xff")
    (tmp_path / "report.xml").write_bytes(text.encode("latin-1"))
    verdict = junit.check_reports(tmp_path)
    assert verdict.tests == 2
    assert len(verdict.problems) == 1


def many_skips(count: int) -> str:
    return junit_xml(1, [f"reason {i}" for i in range(count)])


@pytest.mark.parametrize(
    ("skips", "listed", "more"),
    [(19, 19, 0), (20, 20, 0), (21, 20, 1), (25, 20, 5), (120, 20, 100)],
)
def test_more_than_twenty_problems_are_cut_to_twenty_and_a_count(
    tmp_path: Path, skips: int, listed: int, more: int
) -> None:
    (tmp_path / "report.xml").write_text(many_skips(skips), encoding="utf-8")
    problems = junit.check_reports(tmp_path).problems
    assert len(problems) == listed + (1 if more else 0)
    assert problems[:listed] == tuple(skipped_problem(i, f"reason {i}") for i in range(listed))
    if more:
        assert problems[-1] == f"... and {more} more"
    assert junit.MAX_LISTED == 20


def test_problems_of_several_reports_are_counted_together(tmp_path: Path) -> None:
    for shard in range(3):
        text = junit_xml(1, [f"s{shard}-{i}" for i in range(10)])
        (tmp_path / f"shard-{shard}.xml").write_text(text, encoding="utf-8")
    problems = junit.check_reports(tmp_path).problems
    assert len(problems) == 21
    assert problems[-1] == "... and 10 more"


def test_the_verdict_is_ok_only_without_problems() -> None:
    assert junit.JunitVerdict(5, ()).ok
    assert not junit.JunitVerdict(5, ("x",)).ok


def test_the_reader_imports_no_xml_parser() -> None:
    source = Path(junit.__file__).read_text(encoding="utf-8")
    imports = [ln for ln in source.splitlines() if ln.startswith(("import ", "from "))]
    assert not [ln for ln in imports if "xml" in ln.split()[1]]
