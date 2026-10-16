# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Control for the "no leftover Chrome" checks of the export tests: the detector can see one."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.http_a_procs import (
    browser_roots,
    chrome_descendants,
    descendants,
    have_proc,
    roots_among,
)
from tests.e2e.support.waits import wait_until

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(not have_proc(), reason="needs /proc to inspect processes")


def start(directory: Path, name: str) -> subprocess.Popen[bytes]:
    """A child process (``sleep`` under the program name ``name``) that runs until killed."""
    program = directory / name
    program.symlink_to(shutil.which("sleep") or "/bin/sleep")
    return subprocess.Popen([str(program), "60"])  # noqa: S603 - fixed arguments, a symlink to sleep


def test_a_child_named_like_chrome_is_found_while_it_runs_and_gone_afterwards(
    tmp_path: Path,
) -> None:
    chrome = start(tmp_path, "google-chrome")
    other = start(tmp_path, "not-a-browser")
    try:
        assert chrome.pid in wait_until(chrome_descendants, what="the fake Chrome to be listed")
        assert other.pid in descendants(os.getpid())
        assert other.pid not in chrome_descendants()
        assert chrome.pid in browser_roots()  # started by us, no browser above it
        assert other.pid not in browser_roots()
    finally:
        for child in (chrome, other):
            child.kill()
            child.wait(timeout=10)
    assert chrome.pid not in chrome_descendants()


def test_a_browser_is_the_root_of_its_tree_of_processes() -> None:
    parents = {10: 1, 11: 10, 12: 11, 13: 10, 20: 1, 21: 20}  # two browsers of 4 and 2 processes
    assert roots_among(set(parents), parents.get) == {10, 20}
    assert roots_among({11, 12, 13}, parents.get) == {11, 13}
    assert roots_among(set(), parents.get) == set()


def test_a_scan_that_straddles_the_end_of_a_browser_counts_no_second_browser() -> None:
    """Pid 21 went to init and pid 22 ended while the scan ran: neither is a browser of ours."""
    parents = {10: 5, 11: 10, 21: 1}  # 5 is this process; 22 has no parent any more
    seen = {10, 11, 21, 22}
    assert roots_among(seen, parents.get) == {10, 21, 22}  # without `below`: the old count
    assert roots_among(seen, parents.get, below={5, 10, 11}) == {10}
    assert roots_among({21}, parents.get, below={5, 10, 11}) == set()
