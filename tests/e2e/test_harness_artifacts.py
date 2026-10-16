# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The failure behaviour of the ``page`` fixture, proved by running real (nested) test sessions.

A nested ``pytest`` process loads ``tests.e2e.conftest`` as a plugin and runs three tests of its
own: one that fails, one that passes but leaves a console error behind, one that is clean. The
outer test checks the verdicts and the artefacts (``E2E_ARTIFACTS_DIR`` points them into
``tmp_path``, so the repository's ``.e2e-artifacts`` is never touched).
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Final

import pytest

from tests.e2e.support.session import ARTIFACTS_ENV

ROOT: Final = Path(__file__).resolve().parents[2]
NESTED_TESTS: Final = """
def test_fails(page, live_server):
    page.goto(live_server.url_for("/"))
    assert page.title() == "never this title"


def test_passes_but_leaves_a_console_error(page, live_server):
    page.goto(live_server.url_for("/"))
    page.evaluate("console.error('left behind')")


def test_is_clean(page, live_server):
    page.goto(live_server.url_for("/"))


def test_polls_the_server_until_it_ends(page, live_server):
    page.goto(live_server.url_for("/"))
    page.evaluate("setInterval(() => fetch('/api/v1/graphs').catch(() => {}), 10)")
"""
RUN_TIMEOUT_S: Final = 180


def run_nested(tmp_path: Path) -> tuple[str, Path]:
    """Run ``NESTED_TESTS`` in a fresh pytest process; return its output and its artefact dir."""
    test_file = tmp_path / "test_nested.py"
    test_file.write_text(NESTED_TESTS)
    artifacts = tmp_path / "artifacts"
    env = {**os.environ, ARTIFACTS_ENV: str(artifacts)}
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(ROOT / "pyproject.toml"),
        "-p",
        "tests.e2e.conftest",
        "-p",
        "no:cacheprovider",
        "-q",
        "-rA",
        str(test_file),
    ]
    done = subprocess.run(  # noqa: S603 - a fixed argv of this interpreter, no shell
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        check=False,
    )
    return done.stdout + done.stderr, artifacts


@pytest.fixture(scope="module")
def nested(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, Path]:
    return run_nested(tmp_path_factory.mktemp("nested"))


def test_the_nested_session_reports_one_failure_one_teardown_error_and_three_passes(
    nested: tuple[str, Path],
) -> None:
    output, _ = nested
    assert "1 failed, 3 passed, 1 error" in output, output
    assert "FAILED" in output
    assert "left behind" in output  # the teardown error names the console line


def test_a_failing_test_leaves_a_screenshot_a_trace_and_the_collected_lines(
    nested: tuple[str, Path],
) -> None:
    _, artifacts = nested
    found = sorted(path.name for path in artifacts.rglob("*") if "test_fails" in str(path))
    folder = next(path for path in artifacts.iterdir() if path.name.endswith("test_fails"))
    assert sorted(path.name for path in folder.iterdir()) == [
        "page-0-0.png",
        "problems-0.txt",
        "trace-0.zip",
    ], found
    assert (folder / "page-0-0.png").read_bytes().startswith(b"\x89PNG")
    with zipfile.ZipFile(folder / "trace-0.zip") as trace:
        assert any(name.endswith(".trace") for name in trace.namelist())


def test_a_passing_test_with_a_dirty_browser_keeps_the_evidence(nested: tuple[str, Path]) -> None:
    _, artifacts = nested
    folder = next(
        path for path in artifacts.iterdir() if path.name.endswith("leaves_a_console_error")
    )
    report = (folder / "problems-0.txt").read_text()
    assert "PROBLEM console.error: left behind" in report
    assert (folder / "trace-0.zip").stat().st_size > 0


def test_a_clean_passing_test_leaves_nothing_behind(nested: tuple[str, Path]) -> None:
    _, artifacts = nested
    names = [path.name for path in artifacts.iterdir()]
    assert len(names) == 2
    assert not [name for name in names if name.endswith("test_is_clean")]


def test_the_page_closes_before_its_server_stops(nested: tuple[str, Path]) -> None:
    """A page that is still polling when the test ends must not see a refused connection.

    ``open_page`` depends on ``make_server``, so pytest tears the page down first. With the order
    the other way round the poll hits the stopped server: ERR_CONNECTION_REFUSED at teardown.
    """
    output, artifacts = nested
    assert "PASSED ::test_polls_the_server_until_it_ends" in output, output
    assert "ERROR ::test_polls_the_server_until_it_ends" not in output, output
    assert "ERR_CONNECTION_REFUSED" not in output
    assert not [path for path in artifacts.iterdir() if path.name.endswith("until_it_ends")]
