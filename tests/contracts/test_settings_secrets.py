# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests: ``AppSettings`` limits and the secret handling of ``MongoConnection``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr, ValidationError

from sankey_studio.models import AppSettings, GraphDraft, MongoConnection, TextSource
from sankey_studio.util import mask_uri

if TYPE_CHECKING:
    from collections.abc import Callable


SECRET_URI = "mongodb://tester:hunter2@mongo.invalid:27017/?appName=tests"


def _conn(uri: str = SECRET_URI, name: str = "c") -> MongoConnection:
    return MongoConnection(name=name, uri=SecretStr(uri))


def test_settings_have_no_web_editable_paths() -> None:
    assert "sources_dir" not in AppSettings.model_fields
    with pytest.raises(ValidationError):
        AppSettings.model_validate({"sources_dir": "/"})


def test_settings_limits() -> None:
    assert AppSettings().max_drawn_links == 3000
    assert AppSettings(max_drawn_links=50).max_drawn_links == 50
    assert AppSettings(max_drawn_links=20_000).max_drawn_links == 20_000
    for bad in (49, 20_001):
        with pytest.raises(ValidationError):
            AppSettings(max_drawn_links=bad)
    assert AppSettings(max_upload_mb=100).max_upload_mb == 100
    with pytest.raises(ValidationError):
        AppSettings(max_upload_mb=101)


def test_settings_cross_field_rules() -> None:
    with pytest.raises(ValidationError, match="unique"):
        AppSettings(mongo_connections=[_conn(name="a"), _conn(name="a")])
    with pytest.raises(ValidationError, match="storage_connection"):
        AppSettings(storage_backend="mongo", storage_connection="missing")
    ok = AppSettings(
        storage_backend="mongo", storage_connection="a", mongo_connections=[_conn(name="a")]
    )
    assert ok.connection("a") is not None
    assert ok.connection("zzz") is None


def test_default_serialisers_never_reveal_a_real_uri() -> None:
    settings = AppSettings(mongo_connections=[_conn()])
    conn = settings.mongo_connections[0]
    leaks = [
        repr(settings),
        str(settings),
        repr(conn),
        settings.model_dump_json(),
        json.dumps(settings.model_dump(mode="json")),
        str(settings.model_dump()),
        str(conn.uri),
        repr(conn.uri),
    ]
    for text in leaks:
        assert "hunter2" not in text, text
        assert "mongo.invalid" not in text, text
    assert conn.uri.get_secret_value() == SECRET_URI


def test_default_json_form_cannot_be_loaded_back_over_the_secret() -> None:
    """``model_dump_json`` -> save -> load must fail loudly instead of wiping the secrets."""
    settings = AppSettings(mongo_connections=[_conn()])
    dumped = json.loads(settings.model_dump_json())
    assert dumped["mongo_connections"][0]["uri"] == "**********"
    with pytest.raises(ValidationError, match="masked placeholder"):
        AppSettings.model_validate(dumped)


@pytest.mark.parametrize(
    "placeholder",
    [
        "***",
        "**********",
        "mongodb://u:***@h/db",
        "mongodb://***@h/db",
        "mongodb://***",
        "mongodb://h/db?authSource=***",
        mask_uri(SECRET_URI),
        mask_uri("mongodb://u:pw@h/db?authMechanismProperties=X:Y"),
    ],
)
def test_masked_placeholders_are_rejected_as_uris(placeholder: str) -> None:
    with pytest.raises(ValidationError):
        _conn(placeholder)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://u:abc***@h/",
        "mongodb://u:***abc@h/",
        "mongodb://u:a***b@h/?appName=x***",
        "mongodb://u:p%2A%2A%2A@h/",
    ],
)
def test_a_real_password_with_asterisks_is_not_mistaken_for_a_placeholder(uri: str) -> None:
    assert _conn(uri).uri.get_secret_value() == uri


def test_only_an_exact_triple_asterisk_password_needs_percent_encoding() -> None:
    with pytest.raises(ValidationError, match="masked placeholder"):
        _conn("mongodb://u:***@h/")
    assert _conn("mongodb://u:%2A%2A%2A@h/").uri.get_secret_value() == "mongodb://u:%2A%2A%2A@h/"


def test_connection_requires_a_uri_and_a_scheme() -> None:
    with pytest.raises(ValidationError):
        MongoConnection.model_validate({"name": "c", "uri": None})
    with pytest.raises(ValidationError):
        MongoConnection.model_validate({"name": "c"})
    with pytest.raises(ValidationError):
        _conn("http://u:pw@h/")
    with pytest.raises(ValidationError):
        _conn("")
    with pytest.raises(ValidationError):
        _conn(name="bad name!")


def test_validation_errors_never_echo_the_input() -> None:
    secret = "mongodb://u:hunter2@h/?tlsCAFile=/home/gio/secret.pem"
    with pytest.raises(ValidationError) as info:
        _conn(secret)
    assert "hunter2" not in str(info.value)
    assert "secret.pem" not in str(info.value)
    # the API's 422 envelope uses these flags
    for item in info.value.errors(include_input=False, include_context=False, include_url=False):
        assert set(item) == {"type", "loc", "msg"}
        assert "hunter2" not in json.dumps(item, default=str)
    with pytest.raises(ValidationError) as big:
        TextSource(content="x" * 100, encoding="zlib")
    assert "x" * 50 not in str(big.value)


def _hidden_input_cases() -> list[tuple[str, Callable[[], object], tuple[str, ...]]]:
    """``(label, build, secrets)``: each build must raise a ``ValidationError``."""
    big = "A" * 100 + "SECRET"
    bad_uri = SecretStr("mongodb://u:hunter2@h/?tlsCAFile=/x")
    return [
        ("text", lambda: TextSource(content=big, encoding="zlib"), ("SECRET", "A" * 50)),
        ("uri", lambda: MongoConnection(name="c", uri=bad_uri), ("hunter2", "tlsCAFile=/x")),
        (
            "nested draft",
            lambda: GraphDraft.model_validate(
                {"source": {"type": "text", "content": big, "encoding": "zlib"}}
            ),
            ("SECRET", "A" * 50),
        ),
        (
            "nested settings",
            lambda: AppSettings.model_validate(
                {"mongo_connections": [{"name": "c", "uri": bad_uri.get_secret_value()}]}
            ),
            ("hunter2", "tlsCAFile=/x"),
        ),
    ]


@pytest.mark.parametrize("case", _hidden_input_cases(), ids=lambda c: c[0])
def test_model_errors_hide_input_in_str(
    case: tuple[str, Callable[[], object], tuple[str, ...]],
) -> None:
    """``_Model`` sets ``hide_input_in_errors``: no ``input_value`` / secret in ``str(exc)``."""
    _label, build, secrets = case
    with pytest.raises(ValidationError) as info:
        build()
    text = str(info.value)
    assert "input_value" not in text
    for secret in secrets:
        assert secret not in text
    # the structured form must also drop input when asked (the API's 422 envelope does)
    for item in info.value.errors(include_input=False, include_context=False, include_url=False):
        assert set(item) == {"type", "loc", "msg"}


def test_make_connection_fixture_builds_typed_secret_connections(
    make_connection: Callable[..., MongoConnection],
) -> None:
    """The recipe for strict mypy (``init_typed``): SecretStr(...) or this fixture, no ignore."""
    conn = make_connection("x", "mongodb://u:hunter2@h/", None)
    assert (conn.name, conn.default_database) == ("x", None)
    assert conn.uri.get_secret_value() == "mongodb://u:hunter2@h/"
    assert "hunter2" not in repr(conn)
    default = make_connection()
    assert (default.name, default.default_database) == ("test", "flows")


def test_connection_uri_is_stripped_but_otherwise_kept_verbatim() -> None:
    assert _conn("  " + SECRET_URI + "\n").uri.get_secret_value() == SECRET_URI
