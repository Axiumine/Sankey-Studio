# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The module-scoped server recipe of ``conftest.py``: one server for every test of this module.

Overriding ``live_server`` with ``module_server`` makes ``api``, ``foreign``, ``bare`` and ``page``
use the shared server. The tests of such a module must not depend on a clean server: unique names,
no counting of other tests' data. ``make_server`` / ``open_page`` stay per-test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.server import port_is_closed

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.watch import WatchedPage


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.mark.parametrize("round_", [1, 2, 3])
def test_every_client_and_page_of_the_module_uses_the_shared_server(
    round_: int, module_server: LiveServer, api: httpx.Client, page: WatchedPage
) -> None:
    assert str(api.base_url).rstrip("/") == module_server.url
    page.goto("/")
    assert page.url == module_server.url + "/"
    created = seed_graph(api, unique_name(f"shared {round_}"))
    ids = [item["id"] for item in json_of(api.get("/api/v1/graphs"))["items"]]
    assert created["id"] in ids  # others may be there too: the server is shared


def test_the_module_factory_makes_more_servers_that_stop_with_the_module(
    module_make_server: ServerFactory, module_server: LiveServer
) -> None:
    other = module_make_server(remote_mode=True)
    assert other.port != module_server.port
    assert other.read_only
    assert not module_server.read_only
    assert not port_is_closed(other.host, other.port)
