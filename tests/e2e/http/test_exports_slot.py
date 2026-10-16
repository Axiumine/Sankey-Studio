# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E A.4 (exports, real Chrome): one image export at a time, the others are told to come back.

Chrome is heavy, so the server runs ONE image export and answers the next ones with
``503 export_busy`` after a short wait instead of queueing them (API.md: ``export_busy``). The test
makes that visible: a slow export holds the slot, two more arrive while it runs, and only one
browser ever exists.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Final

import pytest

from tests.e2e.support.builders import BUDGET_CATEGORISED, graph_draft, many_links, unique_name
from tests.e2e.support.clients import make_client, seed_graph
from tests.e2e.support.http_a_exports import assert_download, export, need_chrome
from tests.e2e.support.http_a_procs import (
    BrowserWatch,
    browser_roots,
    chrome_descendants,
    have_proc,
)
from tests.e2e.support.waits import wait_until

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not have_proc(), reason="needs /proc to count the browser processes"),
]

SLOW: Final = {
    "format": "png",
    "width": 4000,
    "height": 4000,
    "scale": 1,
}  # about 5 s with 1000 links
QUICK: Final = {"format": "svg", "width": 300, "height": 200, "scale": 1}
BUSY: Final = (503, "export_busy")
DONE: Final = (200, "")


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: each test saves its own graphs."""
    return module_server


def attempt(server: LiveServer, graph_id: str, **query: object) -> tuple[int, str]:
    """One export on a client of its own: ``(status, error code)``."""
    with make_client(server) as client:
        answer = export(client, graph_id, **query)
        if answer.status_code == 200:
            return DONE
        return answer.status_code, str(answer.json()["error"]["code"])


def test_while_one_export_runs_the_next_ones_are_refused_and_one_browser_exists(
    api: httpx.Client, live_server: LiveServer
) -> None:
    slow = seed_graph(api, unique_name("Slow"), graph_draft(many_links(1000).csv))
    quick = seed_graph(api, unique_name("Quick"), graph_draft(BUDGET_CATEGORISED.csv))
    need_chrome(export(api, quick["id"], **QUICK))  # skips where there is no Chrome
    before = chrome_descendants()
    with BrowserWatch(before) as watch, ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(attempt, live_server, slow["id"], **SLOW)
        wait_until(lambda: browser_roots() - before, timeout=30, what="the slow export's browser")
        late = [pool.submit(attempt, live_server, quick["id"], **QUICK) for _ in range(2)]
        refused = [future.result() for future in late]
        still_running = not first.done()
        first_result = first.result()
    assert refused == [BUSY, BUSY]
    assert still_running, "the slow export ended before the others were answered: not a test"
    assert first_result == DONE
    assert watch.peak == 1, f"{watch.peak} browsers at once, expected exactly one at a time"
    assert_download(export(api, quick["id"], **QUICK), "svg")  # the slot is free again
    wait_until(lambda: not chrome_descendants() - before, timeout=15, what="the Chrome to exit")
