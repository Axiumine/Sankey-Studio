# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md A.9, part 3: the limits themselves are validated, and a refused value changes nothing.

``max_links``, ``max_drawn_links``, ``max_upload_mb`` and ``mongo_timeout_ms`` accept exactly their
documented range (both ends included); a value outside it is a 422 that names the field and the
bound, and neither the answer of ``GET /settings`` nor ``settings.json`` moves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.http_b_limits import API, change_settings

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

#: ``(field, lowest, highest, default)``
BOUNDS: Final = (
    ("max_links", 100, 5_000_000, 200_000),
    ("max_drawn_links", 50, 20_000, 3_000),
    ("max_upload_mb", 1, 100, 25),
    ("mongo_timeout_ms", 500, 300_000, 15_000),
)
CASES = [pytest.param(bounds, id=bounds[0]) for bounds in BOUNDS]


def stored(server: LiveServer) -> bytes | None:
    """The bytes of ``settings.json`` (``None`` while no settings were ever saved)."""
    return server.settings_file.read_bytes() if server.settings_file.exists() else None


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the tests that only send refused values (it never changes)."""
    return module_server


@pytest.mark.parametrize("bounds", CASES)
def test_each_limit_accepts_its_range_and_refuses_what_is_outside_it(
    make_server: ServerFactory, bounds: tuple[str, int, int, int]
) -> None:
    live_server = make_server()  # accepted values are saved: a server of its own
    with make_client(live_server) as api:
        check_bounds(live_server, api, bounds)


def check_bounds(
    live_server: LiveServer, api: httpx.Client, bounds: tuple[str, int, int, int]
) -> None:
    field, low, high, default = bounds
    assert json_of(api.get(f"{API}/settings"))[field] == default
    before = stored(live_server)
    below = change_settings(api, **{field: low - 1})
    assert below.status_code == 422
    assert below.json()["error"]["details"] == [
        f"body.{field}: Input should be greater than or equal to {low}"
    ]
    assert stored(live_server) == before  # a refused value changes nothing
    assert json_of(api.get(f"{API}/settings"))[field] == default
    for accepted in (low, high):
        assert change_settings(api, **{field: accepted}).status_code == 200
        assert json_of(api.get(f"{API}/settings"))[field] == accepted
    kept = stored(live_server)
    above = change_settings(api, **{field: high + 1})
    assert above.status_code == 422
    assert above.json()["error"]["details"] == [
        f"body.{field}: Input should be less than or equal to {high}"
    ]
    assert stored(live_server) == kept
    assert json_of(api.get(f"{API}/settings"))[field] == high


@pytest.mark.parametrize("value", ["abc", None, 100.5, True, [100]])
def test_a_limit_of_the_wrong_type_is_refused(
    live_server: LiveServer, api: httpx.Client, value: object
) -> None:
    before = stored(live_server)
    response = change_settings(api, max_links=value)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0].startswith("body.max_links:")
    assert stored(live_server) == before


def test_one_bad_limit_among_good_ones_saves_none_of_them(
    live_server: LiveServer, api: httpx.Client
) -> None:
    before = stored(live_server)
    response = change_settings(api, max_links=500, max_drawn_links=49, theme="dark")
    assert response.status_code == 422
    assert stored(live_server) == before
    settings = json_of(api.get(f"{API}/settings"))
    assert (settings["max_links"], settings["theme"]) == (200_000, "system")
