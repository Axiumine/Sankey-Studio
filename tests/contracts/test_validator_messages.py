"""Exact messages of the field and model validators that carry their own text.

The UI shows these strings, and a validator whose message nobody compares can be rewritten (or
its guard inverted) without a failing test. Each table also probes the nearest accepted value.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from sankey_studio.models import (
    AppSettings,
    CategoryRule,
    EntryCategory,
    MongoConnection,
    MongoSource,
    TextSource,
    TransformSpec,
)
from tests.validation_support import one_message

# --------------------------------------------------------------------------- MongoConnection

CONNECTION_NAME = "Value error, connection name: 1-64 chars of letters, digits, '_', '.', '-'"
MASKED_PLACEHOLDER = "Value error, uri is a masked placeholder; enter the real connection string"
URI = SecretStr("mongodb://h.invalid/")


@pytest.mark.parametrize("name", ["", "a b", "a/b", "a:b", "é", "x" * 65, "a\nb"])
def test_connection_name_message(name: str) -> None:
    assert one_message(MongoConnection, name=name, uri=URI) == CONNECTION_NAME


@pytest.mark.parametrize("name", ["a", "A_b.c-1", "x" * 64, "  padded  "])
def test_connection_name_accepts_the_documented_alphabet(name: str) -> None:
    assert MongoConnection(name=name, uri=URI).name == name.strip()


@pytest.mark.parametrize("uri", ["***", "**********", "mongodb://***", "mongodb://user:***@host"])
def test_masked_uri_message(uri: str) -> None:
    assert one_message(MongoConnection, name="c", uri=SecretStr(uri)) == MASKED_PLACEHOLDER


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("http://h/", "Value error, uri must start with mongodb:// or mongodb+srv://"),
        ("mongodb://h/?tlsCAFile=/x", "Value error, uri option 'tlsCAFile' is not allowed"),
        ("mongodb+srv://h:1/", "Value error, uri is not a valid MongoDB connection string"),
    ],
)
def test_unsafe_uri_message_is_the_guard_message_without_the_uri(uri: str, message: str) -> None:
    assert one_message(MongoConnection, name="c", uri=SecretStr(uri)) == message


def test_a_valid_uri_is_stored_stripped() -> None:
    conn = MongoConnection(name="c", uri=SecretStr("  mongodb://u:p@h.invalid/db\n"))
    assert conn.uri.get_secret_value() == "mongodb://u:p@h.invalid/db"


# --------------------------------------------------------------------------- AppSettings


def _connection(name: str) -> MongoConnection:
    return MongoConnection(name=name, uri=URI)


def test_duplicate_connection_names_message() -> None:
    message = one_message(AppSettings, mongo_connections=[_connection("a"), _connection("a")])
    assert message == "Value error, mongo connection names must be unique"
    names = [_connection("a"), _connection("A")]  # names are case-sensitive
    assert [c.name for c in AppSettings(mongo_connections=names).mongo_connections] == ["a", "A"]


MONGO_NEEDS_CONNECTION = (
    "Value error, storage_backend 'mongo' needs storage_connection naming a connection"
)


@pytest.mark.parametrize("connection", [None, "missing"])
def test_mongo_backend_needs_a_known_connection(connection: str | None) -> None:
    message = one_message(
        AppSettings,
        storage_backend="mongo",
        storage_connection=connection,
        mongo_connections=[_connection("a")],
    )
    assert message == MONGO_NEEDS_CONNECTION


def test_the_backend_connection_rule_only_binds_the_mongo_backend() -> None:
    assert one_message(AppSettings, storage_backend="mongo") == MONGO_NEEDS_CONNECTION
    mongo = AppSettings(
        storage_backend="mongo", storage_connection="a", mongo_connections=[_connection("a")]
    )
    assert mongo.storage_connection == "a"
    # the file backend never reads the connection, so a dangling name is not an error
    assert AppSettings(storage_backend="file", storage_connection="missing").storage_backend == (
        "file"
    )


@pytest.mark.parametrize(
    ("database", "message"),
    [
        ("admin", "Value error, MongoDB system databases (admin, local, config) are not allowed"),
        ("a.b", "Value error, invalid MongoDB database name"),
    ],
)
def test_storage_database_reports_the_guard_message(database: str, message: str) -> None:
    assert one_message(AppSettings, storage_database=database) == message


AT_MOST_64 = "String should have at most 64 characters"


def test_database_name_length_is_checked_by_the_field_before_the_guard() -> None:
    """65 characters are refused by ``max_length`` (the guard would say 'invalid ... name')."""
    ok, long = "d" * 64, "d" * 65
    assert MongoConnection(name="c", uri=URI, default_database=ok).default_database == ok
    assert AppSettings(storage_database=ok).storage_database == ok
    assert one_message(MongoConnection, name="c", uri=URI, default_database=long) == AT_MOST_64
    assert one_message(AppSettings, storage_database=long) == AT_MOST_64
    assert one_message(MongoSource, connection="c", collection="x", database=long) == AT_MOST_64


def test_collection_name_length_is_checked_by_the_field_before_the_guard() -> None:
    assert MongoSource(connection="c", collection="x" * 120).collection == "x" * 120
    assert one_message(MongoSource, connection="c", collection="x" * 121) == (
        "String should have at most 120 characters"
    )


# --------------------------------------------------------------------------- TextSource

RELATIVE_PATH = "Value error, path must be a relative POSIX path inside the sources directory"
PATH_SEGMENTS = "Value error, path must not contain '.', '..' or empty segments"


def _text(**over: Any) -> dict[str, Any]:
    return {"content": "a,b,1", **over}


@pytest.mark.parametrize("path", ["/abs.csv", "~/x.csv", "dir\\x.csv", "a\0b.csv"])
def test_text_path_must_be_relative_posix(path: str) -> None:
    assert one_message(TextSource, **_text(path=path)) == RELATIVE_PATH


@pytest.mark.parametrize("path", ["a/../b.csv", "..", "./a.csv", "a/./b.csv", "a//b.csv", "a/"])
def test_text_path_refuses_dot_and_empty_segments(path: str) -> None:
    assert one_message(TextSource, **_text(path=path)) == PATH_SEGMENTS


@pytest.mark.parametrize("path", ["a.csv", "d/e/f.csv", "..a/b", "a../b", "a..b", ".hidden"])
def test_text_path_accepts_dotted_names(path: str) -> None:
    assert TextSource(**_text(path=path)).path == path


@pytest.mark.parametrize("delimiter", ['"', "\n", "\r", "\0"])
def test_text_delimiter_message(delimiter: str) -> None:
    expected = "Value error, delimiter must not be a quote, a line break or NUL"
    assert one_message(TextSource, **_text(delimiter=delimiter)) == expected


def test_text_delimiter_length_messages() -> None:
    assert one_message(TextSource, **_text(delimiter="")) == (
        "String should have at least 1 character"
    )
    assert one_message(TextSource, **_text(delimiter=",,")) == (
        "String should have at most 1 character"
    )


@pytest.mark.parametrize("encoding", ["nope", "mbcs", "utf\0", "x" * 32])
def test_text_encoding_unknown_message(encoding: str) -> None:
    assert one_message(TextSource, **_text(encoding=encoding)) == "Value error, unknown encoding"


TEXT_ENCODING = "Value error, encoding must be a text encoding such as 'utf-8' or 'cp1252'"


BYTE_CODECS = ["zlib", "base64", "hex", "rot13", "bz2"]  # not text codecs at all
DENIED_CODECS = ["undefined", "idna", "punycode", "charmap"]  # text codecs, useless for data
ESCAPE_CODECS = ["unicode-escape", "unicode_escape", "raw-unicode-escape", "raw_unicode_escape"]


@pytest.mark.parametrize("encoding", [*BYTE_CODECS, *DENIED_CODECS, *ESCAPE_CODECS])
def test_text_encoding_must_be_a_text_codec_message(encoding: str) -> None:
    assert one_message(TextSource, **_text(encoding=encoding)) == TEXT_ENCODING


@pytest.mark.parametrize(
    ("given", "canonical"),
    [("UTF8", "utf-8"), ("utf_8", "utf-8"), ("latin1", "iso8859-1"), ("cp1252", "cp1252")],
)
def test_text_encoding_is_stored_in_canonical_form(given: str, canonical: str) -> None:
    assert TextSource(**_text(encoding=given)).encoding == canonical


def test_text_encoding_length_limit_comes_before_the_codec_lookup() -> None:
    assert one_message(TextSource, **_text(encoding="x" * 33)) == (
        "String should have at most 32 characters"
    )


# --------------------------------------------------------------------------- MongoSource

FIELD_PATH = "Value error, field must be a dotted path such as 'from' or 'meta.flow'"
FIELDS = ("source_field", "target_field", "value_field", "category_field")


def _mongo(**over: Any) -> dict[str, Any]:
    return {"connection": "c", "collection": "flows", **over}


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("path", ["", "1a", "a..b", "a.", ".a", "a b", "$a", "a.$b", "a/b"])
def test_mongo_field_path_message(field: str, path: str) -> None:
    assert one_message(MongoSource, **_mongo(**{field: path})) == FIELD_PATH


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("path", ["from", "_x", "meta.flow", "a-b.c_d", "a.0.b"])
def test_mongo_field_path_accepts_dotted_names(field: str, path: str) -> None:
    assert getattr(MongoSource(**_mongo(**{field: path})), field) == path


@pytest.mark.parametrize("field", ["value_field", "category_field"])
def test_mongo_optional_fields_accept_none(field: str) -> None:
    assert getattr(MongoSource(**_mongo(**{field: None})), field) is None


def test_mongo_database_and_filter_report_the_guard_messages() -> None:
    assert one_message(MongoSource, **_mongo(database="local")) == (
        "Value error, MongoDB system databases (admin, local, config) are not allowed"
    )
    assert one_message(MongoSource, **_mongo(filter={"$where": "1"})) == (
        "Value error, MongoDB operator $where is not allowed (read-only)"
    )


# --------------------------------------------------------------------------- rules and entries


def test_category_rule_pattern_must_not_contain_nul() -> None:
    message = one_message(CategoryRule, pattern="a\0b", category="x")
    assert message == "Value error, pattern must not contain NUL"
    assert CategoryRule(pattern="a*b?[c]", category="x").pattern == "a*b?[c]"


def test_category_rule_pattern_length_limits() -> None:
    assert CategoryRule(pattern="x" * 200, category="x").pattern == "x" * 200
    assert one_message(CategoryRule, pattern="x" * 201, category="x") == (
        "String should have at most 200 characters"
    )
    assert one_message(CategoryRule, pattern="", category="x") == (
        "String should have at least 1 character"
    )


def _entry(source: str, target: str, category: str | None = "c") -> EntryCategory:
    return EntryCategory(source=source, target=target, category=category)


PAIR_REPEATED = "Value error, entry_categories must not repeat a (source, target) pair"


@pytest.mark.parametrize(
    "entries",
    [
        [_entry("a", "b"), _entry("a", "b")],
        [_entry("a", "b", "x"), _entry("a", "b", "y")],
        [_entry("a", "b", None), _entry("a", "b", "x")],
        [_entry("a", "b"), _entry("c", "d"), _entry(" a ", "b")],
        [_entry("a", "b"), _entry("c", "d"), _entry("e", "f"), _entry("c", "d")],
    ],
)
def test_entry_categories_must_not_repeat_a_pair(entries: list[EntryCategory]) -> None:
    assert one_message(TransformSpec, entry_categories=entries) == PAIR_REPEATED


def test_entry_pairs_are_ordered_and_case_sensitive() -> None:
    entries = [_entry("a", "b"), _entry("b", "a"), _entry("A", "b"), _entry("a", "B")]
    assert TransformSpec(entry_categories=entries).entry_categories == entries
    assert TransformSpec().entry_categories == []
