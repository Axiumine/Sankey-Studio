"""``PUT /settings`` renames a connection once and answers the identical retry the same way.

A rename is ``name`` plus ``previous_name``. After the first save the previous name is gone, so
the retry (a double click, a lost response, a replayed request) must keep the secret that now sits
under ``name`` instead of failing with 422 ``Connection needs a connection string``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import AppSettings
from sankey_studio.util import mask_uri
from tests.conftest import build_connection

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

PATH = "/api/v1/settings"
URI = "mongodb://tester:hunter2@alpha.invalid:27017/?appName=tests"
OTHER = "mongodb://beta-user:s3cret@beta.invalid/?appName=beta"


def renaming(body: dict[str, Any], old: str, new: str) -> dict[str, Any]:
    """The GET answer ``body`` with its connection ``old`` renamed to ``new`` (no URI sent)."""
    sent = [{**c, "name": new, "previous_name": old} for c in body["mongo_connections"]]
    return {**body, "mongo_connections": sent}


def secrets_of(web: WebApp) -> dict[str, str]:
    return {c.name: c.uri.get_secret_value() for c in web.services.settings().mongo_connections}


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    settings = AppSettings(mongo_connections=[build_connection("alpha", URI, "flows")])
    return make_app(settings=settings)


def test_the_identical_rename_can_be_sent_twice(web: WebApp) -> None:
    body = renaming(web.client.get(PATH).json(), "alpha", "beta")
    first = web.client.put(PATH, json=body)
    assert first.status_code == 200
    assert secrets_of(web) == {"beta": URI}
    retry = web.client.put(PATH, json=body)
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert secrets_of(web) == {"beta": URI}


def test_the_retry_is_fine_with_the_masked_uri_of_the_answer_sent_back(web: WebApp) -> None:
    body = renaming(web.client.get(PATH).json(), "alpha", "beta")
    sent = {**body["mongo_connections"][0], "uri": mask_uri(URI)}
    body["mongo_connections"] = [sent]
    assert web.client.put(PATH, json=body).status_code == 200
    assert web.client.put(PATH, json=body).status_code == 200
    assert secrets_of(web) == {"beta": URI}


@pytest.mark.parametrize("stored", ["alpha", "beta"], ids=["before the rename", "after it"])
def test_the_rename_ends_the_same_whichever_state_it_meets(
    make_app: AppFactory, stored: str
) -> None:
    web = make_app(settings=AppSettings(mongo_connections=[build_connection(stored, URI, "flows")]))
    body = renaming(web.client.get(PATH).json(), stored, "beta")
    body["mongo_connections"][0]["previous_name"] = "alpha"
    assert web.client.put(PATH, json=body).status_code == 200
    assert secrets_of(web) == {"beta": URI}


def test_a_retry_with_a_new_uri_still_replaces_the_secret(web: WebApp) -> None:
    body = renaming(web.client.get(PATH).json(), "alpha", "beta")
    assert web.client.put(PATH, json=body).status_code == 200
    body["mongo_connections"][0]["uri"] = OTHER
    assert web.client.put(PATH, json=body).status_code == 200
    assert secrets_of(web) == {"beta": OTHER}


def test_a_rename_of_an_unknown_connection_to_an_unknown_name_is_still_refused(
    web: WebApp,
) -> None:
    body = renaming(web.client.get(PATH).json(), "ghost", "gamma")
    answer = web.client.put(PATH, json=body)
    assert answer.status_code == 422
    assert answer.json()["error"]["code"] == "settings_error"
    assert "hunter2" not in answer.text
    assert secrets_of(web) == {"alpha": URI}
