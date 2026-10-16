# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The Mongo routes never need the sources directory: a broken one must not take them down."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import StorageError
from tests.web.test_routes_mongo_support import BASE, RigMongo, build_rig, error_of
from tests.web.test_routes_sources_support import BLOCKER_TEXT, block_sources_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sankey_studio.models import AppSettings
    from tests.web.test_routes_mongo_support import Rig


class Route(NamedTuple):
    """A Mongo route and the query string it needs."""

    path: str
    params: dict[str, str]


ROUTES = [
    Route("databases", {}),
    Route("collections", {"database": "flows"}),
    Route("sample", {"database": "flows", "collection": "links"}),
]
IDS = [route.path for route in ROUTES]


@pytest.fixture
def rig(tmp_path: Path, app_settings: AppSettings) -> Iterator[Rig]:
    yield from build_rig(tmp_path, RigMongo(names=["flows"], docs=[{"a": 1}]), app_settings)


def test_the_blocker_really_breaks_the_sources_directory(rig: Rig) -> None:
    block_sources_dir(rig.config)
    with pytest.raises(StorageError, match="The sources directory is not usable"):
        rig.services.sources_dir()


@pytest.mark.parametrize("route", ROUTES, ids=IDS)
def test_a_mongo_route_works_with_an_unusable_sources_directory(rig: Rig, route: Route) -> None:
    blocker = block_sources_dir(rig.config)
    response = rig.client.get(f"{BASE}/test/{route.path}", params=route.params)
    assert response.status_code == 200
    assert blocker.read_bytes() == BLOCKER_TEXT


@pytest.mark.parametrize("route", ROUTES, ids=IDS)
def test_an_unknown_connection_is_a_404_not_a_503_with_an_unusable_directory(
    rig: Rig, route: Route
) -> None:
    block_sources_dir(rig.config)
    response = rig.client.get(f"{BASE}/nope/{route.path}", params=route.params)
    assert response.status_code == 404
    assert error_of(response)["code"] == "source_not_found"


@pytest.mark.parametrize("route", ROUTES, ids=IDS)
def test_a_mongo_route_never_creates_the_sources_directory(rig: Rig, route: Route) -> None:
    assert not rig.config.effective_sources_dir.exists()
    assert rig.client.get(f"{BASE}/test/{route.path}", params=route.params).status_code == 200
    assert not rig.config.effective_sources_dir.exists()
