"""``SettingsIn`` / ``MongoConnectionIn``: limits that match ``AppSettings``, and refusals."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from sankey_studio.errors import SettingsError
from sankey_studio.models import AppSettings
from sankey_studio.web.schemas import MongoConnectionIn, SettingsIn, merge_settings
from tests.conftest import build_connection
from tests.web.ids import stable_id
from tests.web.test_schemas_support import Case, check_case, digest

LOW = "greater_than_equal"
HIGH = "less_than_equal"
LONG = "string_too_long"
PATTERN = "string_pattern_mismatch"

SETTINGS = [
    Case("max_links", 100),
    Case("max_links", 99, LOW),
    Case("max_links", 5_000_000),
    Case("max_links", 5_000_001, HIGH),
    Case("max_drawn_links", 50),
    Case("max_drawn_links", 49, LOW),
    Case("max_drawn_links", 20_000),
    Case("max_drawn_links", 20_001, HIGH),
    Case("max_upload_mb", 1),
    Case("max_upload_mb", 0, LOW),
    Case("max_upload_mb", 100),
    Case("max_upload_mb", 101, HIGH),
    Case("mongo_timeout_ms", 500),
    Case("mongo_timeout_ms", 499, LOW),
    Case("mongo_timeout_ms", 300_000),
    Case("mongo_timeout_ms", 300_001, HIGH),
    Case("storage_database", "d" * 64),
    Case("storage_database", "d" * 65, LONG),
    *[Case("theme", name) for name in ("system", "light", "dark")],
    Case("theme", "auto", "literal_error"),
    *[Case("storage_backend", name) for name in ("file", "mongo")],
    Case("storage_backend", "s3", "literal_error"),
]

CONNECTION = [
    Case("name", "a"),
    Case("name", "A_b.c-d"),
    Case("name", "n" * 64),
    Case("name", "n" * 65, PATTERN),
    Case("name", "", PATTERN),
    Case("name", "a b", PATTERN),
    Case("name", "a/b", PATTERN),
    Case("name", "caf" + chr(0xE9), PATTERN),
    Case("previous_name", None),
    Case("previous_name", "old-name"),
    Case("previous_name", "a b", PATTERN),
    Case("previous_name", "n" * 65, PATTERN),
    Case("default_database", None),
    Case("default_database", "d" * 64),
    Case("default_database", "d" * 65, LONG),
]


@pytest.mark.parametrize("case", SETTINGS, ids=repr)
def test_settings_in_limits(case: Case) -> None:
    check_case(SettingsIn, case)


@pytest.mark.parametrize("case", CONNECTION, ids=lambda case: stable_id(repr(case)))
def test_connection_in_limits(case: Case) -> None:
    check_case(MongoConnectionIn, case, {"name": "a"})


def test_twenty_connections_are_allowed_and_a_21st_is_not() -> None:
    twenty = [{"name": f"c{n}"} for n in range(20)]
    assert len(SettingsIn.model_validate({"mongo_connections": twenty}).mongo_connections) == 20
    with pytest.raises(ValidationError) as caught:
        SettingsIn.model_validate({"mongo_connections": [*twenty, {"name": "c20"}]})
    assert digest(caught) == [(("mongo_connections",), "too_long")]


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError) as caught:
        SettingsIn.model_validate({"max_link": 5})
    assert digest(caught) == [(("max_link",), "extra_forbidden")]
    with pytest.raises(ValidationError) as caught:
        MongoConnectionIn.model_validate({"name": "a", "password": "x"})
    assert digest(caught) == [(("password",), "extra_forbidden")]


def test_the_connection_name_is_required() -> None:
    with pytest.raises(ValidationError) as caught:
        MongoConnectionIn.model_validate({"uri": "mongodb://h/"})
    assert digest(caught) == [(("name",), "missing")]


# ------------------------------------------------------------------ same limits as AppSettings

SCALARS = [name for name in AppSettings.model_fields if name != "mongo_connections"]


@pytest.mark.parametrize("name", SCALARS)
def test_each_setting_has_the_type_default_and_limits_of_app_settings(name: str) -> None:
    ours, theirs = SettingsIn.model_fields[name], AppSettings.model_fields[name]
    assert ours.annotation == theirs.annotation
    assert ours.metadata == theirs.metadata
    assert ours.get_default(call_default_factory=True) == theirs.get_default(
        call_default_factory=True
    )


def test_settings_in_has_no_field_that_app_settings_lacks() -> None:
    assert set(SettingsIn.model_fields) == set(AppSettings.model_fields) | {"bootstrap"}


def test_the_connection_list_limit_is_that_of_app_settings() -> None:
    ours = SettingsIn.model_fields["mongo_connections"]
    assert ours.metadata == AppSettings.model_fields["mongo_connections"].metadata


# ------------------------------------------------------------------ what AppSettings refuses


def refused(*connections: dict[str, Any], **fields: Any) -> SettingsError:
    current = AppSettings(mongo_connections=[build_connection("alpha")])
    body = SettingsIn.model_validate({"mongo_connections": list(connections), **fields})
    with pytest.raises(SettingsError) as caught:
        merge_settings(current, body)
    return caught.value


def test_duplicate_connection_names_are_refused() -> None:
    error = refused({"name": "alpha"}, {"name": "alpha"})
    assert error.message == "Settings are invalid"
    assert error.details == ["settings: Value error, mongo connection names must be unique"]


def test_a_mongo_store_needs_a_known_connection() -> None:
    error = refused({"name": "alpha"}, storage_backend="mongo", storage_connection="gone")
    assert error.message == "Settings are invalid"
    expected = "storage_backend 'mongo' needs storage_connection naming a connection"
    assert error.details == [f"settings: Value error, {expected}"]


@pytest.mark.parametrize(
    "uri",
    [
        "http://evil.invalid/",
        "mongodb://h/?tlsCAFile=/etc/passwd",
        "mongodb://h/?authMechanism=GSSAPI",
    ],
)
def test_a_dangerous_uri_is_refused_without_echoing_it(uri: str) -> None:
    error = refused({"name": "fresh", "uri": uri})
    assert error.message == "Settings are invalid"
    assert len(error.details) == 1
    assert error.details[0].startswith("mongo_connections.0.uri: Value error, ")
    assert "evil.invalid" not in error.details[0]
    assert "/etc/passwd" not in error.details[0]


def test_an_over_long_default_database_is_a_request_error_not_a_save_error() -> None:
    with pytest.raises(ValidationError) as caught:
        MongoConnectionIn.model_validate({"name": "a", "default_database": "d" * 65})
    assert digest(caught) == [(("default_database",), LONG)]


def test_an_unsafe_default_database_name_is_refused_by_the_merge() -> None:
    error = refused({"name": "alpha", "default_database": "admin"})
    assert error.details[0].startswith("mongo_connections.0.default_database: Value error, ")
