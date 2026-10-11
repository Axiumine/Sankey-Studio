"""``merge_settings``: when an incoming URI replaces the stored secret and when it never does."""

from __future__ import annotations

from typing import Any

import pytest

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings
from sankey_studio.storage import dump_settings
from sankey_studio.util import mask_uri
from sankey_studio.web.schemas import SettingsIn, merge_settings
from tests.conftest import build_connection

ALPHA = "mongodb://tester:hunter2@alpha.invalid:27017/?appName=tests"
BETA = "mongodb://beta-user:s3cret@beta.invalid/?appName=beta"
PLAIN = "mongodb://plain.invalid/?"  # mask_uri drops the bare '?': masked != stored, yet no stars
NEW = "mongodb://new-user:n3w-pass@elsewhere.invalid:27018/"


def stored(*extra: tuple[str, str]) -> AppSettings:
    connections = [build_connection("alpha", ALPHA, "flows"), build_connection("beta", BETA, None)]
    connections += [build_connection(name, uri, None) for name, uri in extra]
    return AppSettings(mongo_connections=connections)


def connection(name: str, **fields: Any) -> dict[str, Any]:
    return {"name": name, **fields}


def incoming(*connections: dict[str, Any], **fields: Any) -> SettingsIn:
    return SettingsIn.model_validate({"mongo_connections": list(connections), **fields})


def uris(settings: AppSettings) -> dict[str, str]:
    return {conn.name: conn.uri.get_secret_value() for conn in settings.mongo_connections}


# --------------------------------------------------------------------------- keeping the secret


@pytest.mark.parametrize(
    "sent",
    [
        None,
        "",
        "   ",
        "\n",
        mask_uri(ALPHA),
        f"  {mask_uri(ALPHA)}  ",
        "mongodb://tester:***@alpha.invalid:27017/?appName=tests",
        "mongodb://***",
        "**********",
        "***",
        "mongodb://alpha.invalid/?authSource=***",
    ],
)
def test_a_missing_empty_or_masked_uri_keeps_the_stored_secret(sent: str | None) -> None:
    fields = {} if sent is None else {"uri": sent}
    merged = merge_settings(stored(), incoming(connection("alpha", **fields), connection("beta")))
    assert uris(merged) == {"alpha": ALPHA, "beta": BETA}


def test_the_masked_form_of_a_uri_without_stars_also_keeps_the_stored_one() -> None:
    assert mask_uri(PLAIN) == "mongodb://plain.invalid/"
    current = stored(("plain", PLAIN))
    merged = merge_settings(current, incoming(connection("plain", uri=mask_uri(PLAIN))))
    assert uris(merged) == {"plain": PLAIN}


def test_a_real_uri_replaces_only_its_own_connection() -> None:
    merged = merge_settings(
        stored(), incoming(connection("alpha", uri=NEW), connection("beta", uri=None))
    )
    assert uris(merged) == {"alpha": NEW, "beta": BETA}


def test_a_new_uri_is_trimmed() -> None:
    merged = merge_settings(stored(), incoming(connection("alpha", uri=f"  {NEW}\n")))
    assert uris(merged) == {"alpha": NEW}


def test_the_same_uri_again_changes_nothing() -> None:
    merged = merge_settings(stored(), incoming(connection("alpha", uri=ALPHA)))
    assert uris(merged) == {"alpha": ALPHA}


def test_connections_missing_from_the_request_are_removed() -> None:
    merged = merge_settings(stored(), incoming(connection("beta")))
    assert uris(merged) == {"beta": BETA}
    assert uris(merge_settings(stored(), incoming())) == {}


def test_the_default_database_comes_from_the_request() -> None:
    merged = merge_settings(
        stored(), incoming(connection("alpha", default_database="other"), connection("beta"))
    )
    assert [c.default_database for c in merged.mongo_connections] == ["other", None]


# --------------------------------------------------------------------------- renames


def test_a_rename_keeps_the_secret_of_the_previous_name() -> None:
    merged = merge_settings(
        stored(), incoming(connection("gamma", previous_name="alpha"), connection("beta"))
    )
    assert uris(merged) == {"gamma": ALPHA, "beta": BETA}


def test_a_rename_with_a_new_uri_uses_the_new_uri() -> None:
    merged = merge_settings(stored(), incoming(connection("gamma", previous_name="alpha", uri=NEW)))
    assert uris(merged) == {"gamma": NEW}


def test_a_masked_uri_after_a_rename_keeps_the_secret_of_the_previous_name() -> None:
    sent = connection("gamma", previous_name="alpha", uri=mask_uri(ALPHA))
    assert uris(merge_settings(stored(), incoming(sent))) == {"gamma": ALPHA}


def test_the_previous_name_wins_over_the_name_for_the_lookup() -> None:
    merged = merge_settings(stored(), incoming(connection("alpha", previous_name="beta")))
    assert uris(merged) == {"alpha": BETA}


def test_swapped_names_follow_the_stored_secrets_not_the_request_order() -> None:
    sent = [connection("beta", previous_name="alpha"), connection("alpha", previous_name="beta")]
    assert uris(merge_settings(stored(), incoming(*sent))) == {"beta": ALPHA, "alpha": BETA}


def test_two_connections_may_start_from_the_same_secret() -> None:
    sent = [connection("alpha"), connection("copy", previous_name="alpha")]
    assert uris(merge_settings(stored(), incoming(*sent))) == {"alpha": ALPHA, "copy": ALPHA}


# --------------------------------------------------------------------------- retried renames


RENAME = [connection("gamma", previous_name="alpha"), connection("beta")]


@pytest.mark.parametrize(
    "sent",
    [None, "", mask_uri(ALPHA), "**********", ALPHA],
    ids=["no uri", "empty", "masked", "stars", "the real uri again"],
)
def test_a_retried_rename_is_idempotent(sent: str | None) -> None:
    first = merge_settings(stored(), incoming(*RENAME))
    fields = {} if sent is None else {"uri": sent}
    retry = [connection("gamma", previous_name="alpha", **fields), connection("beta")]
    again = merge_settings(first, incoming(*retry))
    assert uris(first) == {"gamma": ALPHA, "beta": BETA}
    assert dump_settings(again) == dump_settings(first)
    assert dump_settings(merge_settings(again, incoming(*retry))) == dump_settings(first)


def test_a_retried_rename_with_a_new_uri_uses_the_new_uri() -> None:
    first = merge_settings(stored(), incoming(*RENAME))
    retry = connection("gamma", previous_name="alpha", uri=NEW)
    assert uris(merge_settings(first, incoming(retry, connection("beta")))) == {
        "gamma": NEW,
        "beta": BETA,
    }


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        (connection("gamma", previous_name="alpha"), ALPHA),
        (connection("beta", previous_name="ghost"), BETA),
        (connection("alpha", previous_name="beta"), BETA),
        (connection("alpha", previous_name="alpha"), ALPHA),
        (connection("beta"), BETA),
    ],
    ids=[
        "renamed now",
        "renamed before (previous gone, name stored)",
        "both stored: the previous name wins",
        "same name twice",
        "no previous name",
    ],
)
def test_the_secret_is_found_by_the_previous_name_then_by_the_name(
    sent: dict[str, Any], expected: str
) -> None:
    assert uris(merge_settings(stored(), incoming(sent)))[sent["name"]] == expected


def test_a_retry_never_borrows_the_secret_of_another_connection() -> None:
    renamed = merge_settings(stored(), incoming(*RENAME))
    with pytest.raises(SettingsError) as caught:
        merge_settings(renamed, incoming(connection("delta", previous_name="alpha")))
    assert caught.value.message == "Connection 'delta' needs a connection string"
    assert "hunter2" not in str(caught.value)
    assert "s3cret" not in str(caught.value)


# --------------------------------------------------------------------------- no secret at all


@pytest.mark.parametrize(
    "sent",
    [
        connection("brand-new"),
        connection("brand-new", uri=""),
        connection("brand-new", uri="**********"),
        connection("brand-new", uri=mask_uri(ALPHA)),
        connection("brand-new", previous_name="ghost"),
    ],
    ids=["none", "empty", "stars", "masked", "unknown previous name"],
)
def test_a_connection_without_any_secret_is_refused(sent: dict[str, Any]) -> None:
    with pytest.raises(SettingsError) as caught:
        merge_settings(stored(), incoming(sent))
    assert caught.value.message == "Connection 'brand-new' needs a connection string"
    assert caught.value.details == []
    assert "hunter2" not in str(caught.value)


def test_a_connection_without_a_secret_is_fine_when_it_brings_a_real_uri() -> None:
    merged = merge_settings(stored(), incoming(connection("brand-new", uri=NEW)))
    assert uris(merged) == {"brand-new": NEW}


# --------------------------------------------------------------------------- the other fields


def test_every_scalar_setting_comes_from_the_request() -> None:
    fields: dict[str, Any] = {
        "storage_backend": "mongo",
        "storage_connection": "beta",
        "storage_database": "graphs_db",
        "theme": "dark",
        "default_style": {"title": "Mine", "orientation": "v"},
        "max_links": 1234,
        "max_drawn_links": 777,
        "max_upload_mb": 7,
        "mongo_timeout_ms": 4000,
    }
    merged = merge_settings(stored(), incoming(connection("beta"), **fields))
    doc = dump_settings(merged)
    for name, value in fields.items():
        if name != "default_style":
            assert doc[name] == value
    assert merged.default_style.title == "Mine"
    assert merged.default_style.orientation == "v"
    assert uris(merged) == {"beta": BETA}


def test_a_request_without_fields_resets_to_the_defaults_but_keeps_the_secrets() -> None:
    current = AppSettings.model_validate(
        {**dump_settings(stored()), "theme": "dark", "max_links": 1000}
    )
    merged = merge_settings(current, incoming(connection("alpha"), connection("beta")))
    assert merged.theme == "system"
    assert merged.max_links == 200_000
    assert uris(merged) == {"alpha": ALPHA, "beta": BETA}


def test_the_read_only_echo_of_a_get_is_accepted_and_ignored() -> None:
    echo = {"uri_masked": "mongodb://evil.invalid", "has_secret": False}
    body = {
        "mongo_connections": [connection("alpha", **echo)],
        "bootstrap": {"sources_dir": "/x", "remote_mode": True, "writes_allowed": False},
    }
    merged = merge_settings(stored(), SettingsIn.model_validate(body))
    assert uris(merged) == {"alpha": ALPHA}


def test_the_stored_settings_are_not_touched() -> None:
    current = stored()
    before = dump_settings(current)
    merged = merge_settings(current, incoming(connection("gamma", previous_name="alpha", uri=NEW)))
    assert dump_settings(current) == before
    assert merged is not current


def test_secrets_stay_out_of_the_repr_of_a_request() -> None:
    request = incoming(connection("alpha", uri=ALPHA))
    assert "hunter2" not in repr(request)
    assert "hunter2" not in request.model_dump_json()
    assert request.model_dump(mode="json")["mongo_connections"][0]["uri"] == "**********"
