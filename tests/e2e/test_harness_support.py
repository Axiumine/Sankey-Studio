"""Self-tests of the pure parts of the harness: waits, builders and the watcher's allow-list.

No server and no browser here: they run in milliseconds and pin the contracts the suites rely on.
"""

from __future__ import annotations

import csv
import io
import time
from typing import TYPE_CHECKING, Any, cast

import pytest
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.support.browser import launch_browser
from tests.e2e.support.builders import (
    BUDGET,
    BUDGET_CATEGORISED,
    MANY_LINKS,
    csv_text,
    graph_create,
    graph_draft,
    many_links,
    unique_name,
)
from tests.e2e.support.http_a_library import newest_first
from tests.e2e.support.stamps import instant
from tests.e2e.support.unavailable import is_image_export
from tests.e2e.support.waits import wait_until
from tests.e2e.support.watch import PageWatch

if TYPE_CHECKING:
    from playwright.sync_api import Playwright

# ------------------------------------------------------------------------------ wait_until


def test_wait_until_returns_the_first_truthy_value() -> None:
    values = iter([0, "", None, "ready", "later"])
    assert wait_until(lambda: next(values), timeout=2, interval=0.001) == "ready"


def test_wait_until_probes_once_even_with_a_zero_timeout() -> None:
    assert wait_until(lambda: "now", timeout=0) == "now"


def test_wait_until_times_out_naming_what_it_waited_for_and_the_last_value() -> None:
    started = time.monotonic()
    with pytest.raises(
        AssertionError, match=r"timed out after 0\.05s waiting for the moon.*last: 0"
    ):
        wait_until(lambda: 0, timeout=0.05, what="the moon", interval=0.01)
    assert time.monotonic() - started < 2


# ------------------------------------------------------------------------------ csv_text


def test_csv_text_picks_the_header_by_row_width() -> None:
    assert csv_text([("a", "b", 1)]) == "source,target,value\na,b,1\n"
    assert csv_text([("a", "b", 1, "x")]) == "source,target,value,category\na,b,1,x\n"
    assert csv_text([]) == "source,target,value\n"


def test_csv_text_header_can_be_given_or_dropped() -> None:
    assert csv_text([("a", "b", 1)], header=("from", "to", "amount")) == "from,to,amount\na,b,1\n"
    assert csv_text([("a", "b", 1)], header=()) == "a,b,1\n"


def test_csv_text_quotes_what_csv_requires() -> None:
    text = csv_text([('R&D, "labs"', "Line\nbreak", 2.5)])
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[1] == ['R&D, "labs"', "Line\nbreak", "2.5"]


# ------------------------------------------------------------------------------ the samples


def test_the_budget_samples_have_the_same_links_and_the_documented_totals() -> None:
    plain = list(csv.reader(io.StringIO(BUDGET.csv)))
    categorised = list(csv.reader(io.StringIO(BUDGET_CATEGORISED.csv)))
    assert plain[0] == ["source", "target", "value"]
    assert categorised[0] == ["source", "target", "value", "category"]
    assert [row[:3] for row in categorised[1:]] == plain[1:]
    assert len(plain) - 1 == BUDGET.links == 9
    assert sum(float(row[2]) for row in plain[1:]) == 8240.0
    assert sum(BUDGET_CATEGORISED.categories.values()) == 8240.0
    assert BUDGET.category_count == 0
    assert BUDGET_CATEGORISED.category_count == 5


def test_many_links_are_distinct_and_counted() -> None:
    rows = list(csv.reader(io.StringIO(MANY_LINKS.csv)))[1:]
    assert len(rows) == MANY_LINKS.links == 300
    assert len({(row[0], row[1]) for row in rows}) == 300
    assert len({row[0] for row in rows} | {row[1] for row in rows}) == MANY_LINKS.nodes == 35
    assert all(1 <= int(row[2]) <= 9 for row in rows)
    assert MANY_LINKS.total == float(sum(int(row[2]) for row in rows))


def test_many_links_scales_down() -> None:
    small = many_links(20)
    assert (small.links, small.nodes) == (20, 2 + 15)


# ------------------------------------------------------------------------------ payloads


def test_graph_draft_merges_the_overrides_onto_an_inline_csv_source() -> None:
    draft = graph_draft(
        "a,b,1\n",
        source={"category_column": "kind", "format": "tsv"},
        transform={"on_cycle": "break"},
        style={"title": "T"},
    )
    assert draft == {
        "source": {
            "type": "text",
            "origin": "inline",
            "format": "tsv",
            "content": "a,b,1\n",
            "category_column": "kind",
        },
        "transform": {"on_cycle": "break"},
        "style": {"title": "T"},
    }
    assert graph_draft()["source"]["content"] == BUDGET.csv


def test_graph_create_adds_the_identity_fields_to_a_draft() -> None:
    body = graph_create("My graph", tags=["a", "b"], description="d")
    assert body["name"] == "My graph"
    assert body["tags"] == ["a", "b"]
    assert body["description"] == "d"
    assert body["source"]["content"] == BUDGET.csv
    custom = graph_create("X", graph_draft("p,q,1\n"))
    assert custom["source"]["content"] == "p,q,1\n"


def test_unique_name_is_unique_and_keeps_its_prefix() -> None:
    names = {unique_name("Budget") for _ in range(50)}
    assert len(names) == 50
    assert all(name.startswith("Budget ") and len(name) == len("Budget ") + 8 for name in names)


# ------------------------------------------------------------------------------ allow-list

HTTP_LINE = "http 409: PUT http://127.0.0.1:41234/api/v1/graphs/abc"
CHROME_LINE = (
    "console.error: Failed to load resource: the server responded with a status of 409 (Conflict)"
    " @ http://127.0.0.1:41234/api/v1/graphs/abc"
)


def watch_with(*lines: str) -> PageWatch:
    watch = PageWatch()
    watch.events.extend(lines)
    return watch


def test_a_line_is_a_problem_until_an_allow_pattern_matches_it() -> None:
    watch = watch_with("pageerror: Error: boom", "console.warning: careful @ http://x/")
    assert watch.problems() == ["pageerror: Error: boom", "console.warning: careful @ http://x/"]
    watch.allow_errors("boom")
    assert watch.problems() == ["console.warning: careful @ http://x/"]
    with pytest.raises(AssertionError, match="careful"):
        watch.assert_clean()
    watch.allow_errors(r"^console\.warning: careful")
    watch.assert_clean()


def test_allow_http_covers_the_response_and_chromes_console_line() -> None:
    watch = watch_with(HTTP_LINE, CHROME_LINE)
    watch.allow_http(409, "/api/v1/graphs/")
    assert watch.problems() == []


@pytest.mark.parametrize(
    ("status", "path"),
    [(404, "/api/v1/graphs/"), (409, "/api/v1/export"), (4090, "")],
    ids=["other-status", "other-path", "status-prefix"],
)
def test_allow_http_is_specific_to_status_and_path(status: int, path: str) -> None:
    watch = watch_with(HTTP_LINE, CHROME_LINE)
    watch.allow_http(status, path)
    assert watch.problems() == [HTTP_LINE, CHROME_LINE]


def test_matching_reports_allowed_lines_too_and_report_marks_them() -> None:
    watch = watch_with(HTTP_LINE, "pageerror: Error: boom")
    watch.allow_http(409)
    assert watch.matching(r"^http 409") == [HTTP_LINE]
    assert watch.report().splitlines() == [f"ALLOWED {HTTP_LINE}", "PROBLEM pageerror: Error: boom"]


def test_a_csp_violation_can_never_be_allowed() -> None:
    watch = PageWatch()
    watch.record_csp("img-src http://evil.example/x.png @ http://127.0.0.1:1/")
    watch.allow_errors(".*", "img-src", "csp")
    assert watch.problems() == ["csp: img-src http://evil.example/x.png @ http://127.0.0.1:1/"]
    with pytest.raises(AssertionError, match="img-src"):
        watch.assert_clean()


# ------------------------------------------------------------------------------ browser launch


class FakeChromium:
    """``pw.chromium`` whose ``launch`` fails for the first ``failures`` calls."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls: list[dict[str, object]] = []

    def launch(self, **options: object) -> str:
        self.calls.append(options)
        if len(self.calls) <= self.failures:
            raise PlaywrightError(f"Executable doesn't exist (call {len(self.calls)})\nmore text")
        return "a browser"


class FakePlaywright:
    def __init__(self, failures: int) -> None:
        self.chromium = FakeChromium(failures)


def test_launch_browser_prefers_system_chrome() -> None:
    pw = FakePlaywright(failures=0)
    browser, reason = launch_browser(cast("Playwright", pw))
    assert (cast("object", browser), reason) == ("a browser", "")
    first = pw.chromium.calls[0]
    assert first["channel"] == "chrome"
    assert first["headless"] is True
    assert first["args"] == ["--no-sandbox", "--disable-dev-shm-usage"]
    assert cast("dict[str, str]", first["env"])["LANG"] == "en_US.UTF-8"


def test_launch_browser_falls_back_to_the_bundled_chromium() -> None:
    pw = FakePlaywright(failures=1)
    browser, reason = launch_browser(cast("Playwright", pw))
    assert (cast("object", browser), reason) == ("a browser", "")
    assert "channel" not in pw.chromium.calls[1]


def test_launch_browser_explains_why_nothing_started() -> None:
    browser, reason = launch_browser(cast("Playwright", FakePlaywright(failures=2)))
    assert browser is None
    assert "system Chrome: Executable doesn't exist (call 1)" in reason
    assert "bundled Chromium: Executable doesn't exist (call 2)" in reason
    assert "more text" not in reason


# ------------------------------------------------------------------------------ forced 501


def scope(method: str, path: str, query: str = "", kind: str = "http") -> dict[str, Any]:
    return {"type": kind, "method": method, "path": path, "query_string": query.encode()}


GRAPH_EXPORT = "/api/v1/graphs/" + "a" * 32 + "/export"


@pytest.mark.parametrize(
    ("request_scope", "expected"),
    [
        (scope("GET", GRAPH_EXPORT), True),
        (scope("GET", GRAPH_EXPORT, "format=svg"), True),
        (scope("GET", GRAPH_EXPORT, "chart=donut&format=png&width=900"), True),
        (scope("POST", "/api/v1/export", "format=png"), True),
        (scope("POST", "/api/v1/export"), True),
        (scope("GET", GRAPH_EXPORT, "format=csv"), False),
        (scope("GET", GRAPH_EXPORT, "format=html"), False),
        (scope("GET", GRAPH_EXPORT, "format=json"), False),
        (scope("POST", GRAPH_EXPORT), False),
        (scope("GET", "/api/v1/export"), False),
        (scope("GET", "/api/v1/graphs/export", "format=png"), False),
        (scope("GET", "/api/v1/graphs/a/b/export"), False),
        (scope("GET", "/api/v1/health"), False),
        (scope("GET", GRAPH_EXPORT, kind="websocket"), False),
        (scope("GET", "/", kind="lifespan"), False),
    ],
)
def test_only_image_exports_are_forced_to_501(
    request_scope: dict[str, Any], expected: bool
) -> None:
    assert is_image_export(request_scope) is expected


# ------------------------------------------------------------------------------ timestamps


def test_stamps_compare_as_instants_because_text_puts_a_zero_millisecond_stamp_last() -> None:
    whole, milli = "2026-10-11T10:00:46Z", "2026-10-11T10:00:46.001Z"
    assert whole > milli  # the trap: as text "Z" sorts after "."
    assert instant(whole) < instant(milli)
    assert instant(milli) < instant("2026-10-11T10:00:47Z")


def test_newest_first_orders_stamps_with_and_without_milliseconds_and_breaks_ties_by_id() -> None:
    graphs = [
        {"id": "a", "updated_at": "2026-10-11T10:00:46Z"},
        {"id": "c", "updated_at": "2026-10-11T10:00:46.001Z"},
        {"id": "b", "updated_at": "2026-10-11T10:00:46.001Z"},
        {"id": "d", "updated_at": "2026-10-11T10:00:45.999Z"},
    ]
    assert newest_first(graphs) == ["b", "c", "a", "d"]


def test_a_stamp_without_the_utc_suffix_is_refused() -> None:
    with pytest.raises(AssertionError, match="not a UTC timestamp"):
        instant("2026-10-11T10:00:46")
