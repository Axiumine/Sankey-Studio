# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Two ``PUT /settings`` at once: the later one merges against the earlier one's result."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.services import Services
from sankey_studio.web.routers import settings as settings_module
from sankey_studio.web.routers.settings import router
from sankey_studio.web.schemas import merge_settings
from tests.web.test_routes_settings_support import BASE, put_body, stored_uri

if TYPE_CHECKING:
    from httpx2 import Response

    from sankey_studio.models import AppSettings
    from sankey_studio.services import UpdateResult
    from sankey_studio.web.schemas import SettingsIn
    from tests.web.conftest import AppFactory, WebApp

ROTATED_URI: Final = "mongodb://tester:rotated-s3cret@mongo.invalid:27017/?appName=tests"
#: How long a writer waits for the other one at a meeting point. Under the lock the other writer
#: cannot arrive, so a correct run waits this long once; without the lock it arrives at once.
RENDEZVOUS_S: Final = 0.5
PATIENCE_S: Final = 10.0


@pytest.fixture
def web(make_app: AppFactory, app_settings: AppSettings) -> WebApp:
    return make_app([router], settings=app_settings)


def rotates(incoming: SettingsIn) -> bool:
    return incoming.mongo_connections[0].uri is not None


def choreograph(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the interleaving that loses a rotated secret when nothing serialises the writers.

    Writer A rotates the secret, writer B sends none. Both merge against the SAME stored
    snapshot, then B waits until A has saved and only then saves its own (stale) merge. With the
    settings lock the second writer cannot even start its merge before the first one has saved,
    so each wait just times out once and the later merge sees the earlier save.
    """
    b_merged, a_saved = threading.Event(), threading.Event()
    update = Services.update_settings

    def merging(stored: AppSettings, incoming: SettingsIn) -> AppSettings:
        merged = merge_settings(stored, incoming)
        if rotates(incoming):
            b_merged.wait(RENDEZVOUS_S)  # A saves only after B has merged
        else:
            b_merged.set()
            a_saved.wait(RENDEZVOUS_S)  # B saves only after A has saved
        return merged

    def updating(self: Services, new: AppSettings, *, migrate: bool = False) -> UpdateResult:
        result = update(self, new, migrate=migrate)
        connection = new.connection("test")
        if connection is not None and connection.uri.get_secret_value() == ROTATED_URI:
            a_saved.set()
        return result

    monkeypatch.setattr(settings_module, "merge_settings", merging)
    monkeypatch.setattr(Services, "update_settings", updating)


def put_both(web: WebApp, bodies: tuple[dict[str, Any], dict[str, Any]]) -> list[Response]:
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(web.client.put, BASE, json=body) for body in bodies]
        return [future.result(timeout=PATIENCE_S) for future in futures]


def writers(web: WebApp) -> tuple[dict[str, Any], dict[str, Any]]:
    """A rotates the secret of ``test``; B is the same page saving with no secret in it."""
    keep = put_body(web.client)
    rotate = put_body(web.client)
    rotate["mongo_connections"][0]["uri"] = ROTATED_URI
    return rotate, keep


@pytest.mark.parametrize("swapped", [False, True], ids=["A-first", "B-first"])
def test_a_rotated_secret_is_not_overwritten_by_a_writer_that_sent_none(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, swapped: bool
) -> None:
    rotate, keep = writers(web)
    choreograph(monkeypatch)
    answers = put_both(web, (keep, rotate) if swapped else (rotate, keep))
    assert [r.status_code for r in answers] == [200, 200]
    assert stored_uri(web) == ROTATED_URI
    assert ROTATED_URI in web.config.settings_file.read_text()


def test_the_answers_never_show_the_secret(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> None:
    choreograph(monkeypatch)
    answers = put_both(web, writers(web))
    assert all("rotated-s3cret" not in r.text for r in answers)
    assert all(r.json()["settings"]["mongo_connections"][0]["has_secret"] for r in answers)


def test_without_the_choreography_a_sequence_of_saves_merges_against_the_latest(
    web: WebApp,
) -> None:
    rotate, keep = writers(web)
    assert web.client.put(BASE, json=rotate).status_code == 200
    assert web.client.put(BASE, json=keep).status_code == 200
    assert stored_uri(web) == ROTATED_URI
