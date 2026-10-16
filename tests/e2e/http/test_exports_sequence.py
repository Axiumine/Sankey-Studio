# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E A.4 (exports, real Chrome): exports in a row and in parallel, and no browser left behind."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import json_of, make_client, seed_graph
from tests.e2e.support.http_a_exports import assert_download, export, need_chrome
from tests.e2e.support.http_a_images import PNG_MAGIC, png_info
from tests.e2e.support.http_a_procs import chrome_descendants, have_proc
from tests.e2e.support.waits import wait_until

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer

pytestmark = pytest.mark.slow

ROUNDS = 10
PARALLEL = 3
SIZE = {"width": 300, "height": 200, "scale": 1}


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: each test saves its own graph."""
    return module_server


@pytest.fixture
def saved(api: httpx.Client) -> dict[str, str]:
    return seed_graph(api, unique_name("Sequence"), graph_draft(BUDGET_CATEGORISED.csv))


def assert_no_new_browser(before: set[int]) -> None:
    """Every Chrome this process started for an export has gone again (bounded wait)."""
    if not have_proc():
        pytest.skip("needs /proc to look for leftover browser processes")
    wait_until(
        lambda: not chrome_descendants() - before,
        timeout=15,
        what="the Chrome of the exports to exit",
    )


def test_ten_exports_in_a_row_all_succeed_and_leave_no_browser_behind(
    api: httpx.Client, saved: dict[str, str]
) -> None:
    before = chrome_descendants()
    oversize = export(api, saved["id"], format="png", width=20_000, height=20_000)
    assert json_of(oversize, 422)["error"]["code"] == "export_too_large"  # a 4xx, not a crash
    for round_number in range(ROUNDS):
        fmt = "png" if round_number % 2 else "svg"
        chart = "donut" if round_number % 4 >= 2 else "sankey"
        answer = need_chrome(export(api, saved["id"], format=fmt, chart=chart, **SIZE))
        assert_download(answer, fmt)
        if fmt == "png":
            assert answer.content.startswith(PNG_MAGIC)
            assert (png_info(answer.content).width, png_info(answer.content).height) == (300, 200)
        else:
            assert answer.text.startswith("<svg")
    assert_no_new_browser(before)


def test_parallel_exports_wait_or_answer_busy_and_never_break_the_server(
    api: httpx.Client, saved: dict[str, str], live_server: LiveServer
) -> None:
    before = chrome_descendants()

    def one(_: int) -> tuple[int, str]:
        with make_client(live_server) as client:
            answer = export(client, saved["id"], format="svg", **SIZE)
            code = "" if answer.status_code == 200 else answer.json()["error"]["code"]
            return answer.status_code, code

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        results = list(pool.map(one, range(PARALLEL)))
    need_chrome_status = {status for status, _ in results}
    if 501 in need_chrome_status:
        pytest.skip("Chrome is not available: the server answers 501 export_unavailable")
    assert (200, "") in results  # at least one export got through
    assert {result for result in results if result != (200, "")} <= {(503, "export_busy")}
    after = export(api, saved["id"], format="png", **SIZE)  # and the next one is fine
    assert_download(after, "png")
    assert_no_new_browser(before)
