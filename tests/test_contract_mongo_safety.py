"""Contract tests for ``mongo_safety``: every bypass the security review reproduced must stay shut.

The MONGO agent owns ``mongo_safety.py`` and may harden it further; these tests must keep passing
(add new cases to ``tests/test_mongo_safety.py``, not here).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from sankey_studio.errors import UnsafeSourceError
from sankey_studio.models import AppSettings, MongoConnection, MongoSource
from sankey_studio.mongo_safety import (
    MAX_DEPTH,
    check_filter,
    check_mongo_uri,
    check_pipeline,
    validate_collection_name,
    validate_db_name,
    validate_namespace,
)

# --------------------------------------------------------------------------- pipelines

BYPASSES: dict[str, list[dict[str, Any]]] = {
    "collStats inside $facet/$lookup.pipeline": [
        {
            "$facet": {
                "a": [
                    {
                        "$lookup": {
                            "from": "flows",
                            "pipeline": [{"$collStats": {"storageStats": {}}}],
                            "as": "x",
                        }
                    }
                ]
            }
        }
    ],
    "collStats inside $unionWith.pipeline": [
        {"$unionWith": {"coll": "flows", "pipeline": [{"$collStats": {"count": {}}}]}}
    ],
    "$unionWith with a db key": [{"$unionWith": {"db": "admin", "coll": "users"}}],
    "$unionWith system collection": [{"$unionWith": "system.profile"}],
    "$unionWith dict form system collection": [{"$unionWith": {"coll": "system.users"}}],
    "$lookup.from object form": [
        {"$lookup": {"from": {"db": "admin", "coll": "users"}, "pipeline": [], "as": "x"}}
    ],
    "$lookup system collection": [
        {"$lookup": {"from": "system.users", "localField": "a", "foreignField": "b", "as": "x"}}
    ],
    "$graphLookup top level": [
        {
            "$graphLookup": {
                "from": "x",
                "startWith": "$a",
                "connectFromField": "a",
                "connectToField": "b",
                "as": "o",
            }
        }
    ],
    "$graphLookup nested in $facet": [
        {
            "$facet": {
                "a": [
                    {
                        "$graphLookup": {
                            "from": "x",
                            "startWith": "$a",
                            "connectFromField": "a",
                            "connectToField": "b",
                            "as": "o",
                        }
                    }
                ]
            }
        }
    ],
    "$$USER_ROLES": [{"$project": {"r": "$$USER_ROLES"}}],
    "$$SEARCH_META": [{"$set": {"m": "$$SEARCH_META"}}],
    "$range bomb": [{"$project": {"r": {"$range": [0, 2_000_000_000]}}}, {"$unwind": "$r"}],
    "$function nested in $expr": [
        {"$match": {"$expr": {"$function": {"body": "x", "args": [], "lang": "js"}}}}
    ],
    "$out nested in $facet": [{"$facet": {"a": [{"$out": "stolen"}]}}],
    "NUL in key": [{"$match": {"a\x00b": 1}}],
    "int beyond 64 bits": [{"$match": {"a": 2**70}}],
    "$facet branch not a list": [{"$facet": {"a": {"$match": {}}}}],
    "$lookup unknown key": [{"$lookup": {"from": "flows", "as": "x", "db": "admin"}}],
    "too many $lookup": [
        {"$lookup": {"from": "c", "localField": "a", "foreignField": "b", "as": f"x{i}"}}
        for i in range(4)
    ],
    "too many $unwind": [{"$unwind": "$a"}, {"$unwind": "$b"}, {"$unwind": "$c"}],
    "two $facet": [{"$facet": {"a": []}}, {"$facet": {"b": []}}],
}


@pytest.mark.parametrize("name", list(BYPASSES))
def test_pipeline_bypasses_are_rejected(name: str) -> None:
    with pytest.raises(UnsafeSourceError):
        check_pipeline(BYPASSES[name])


@pytest.mark.parametrize(
    "name", ["$$ROOT", "$$CURRENT.a", "$$NOW", "$$REMOVE", "$$this", "$$value.x", "$$myVar"]
)
def test_benign_variables_are_allowed(name: str) -> None:
    check_pipeline([{"$project": {"x": name}}])


def test_legitimate_pipeline_passes() -> None:
    check_pipeline(
        [
            {"$match": {"year": 2025}},
            {
                "$lookup": {
                    "from": "accounts",
                    "localField": "acc",
                    "foreignField": "_id",
                    "pipeline": [{"$project": {"name": 1}}],
                    "as": "acc",
                }
            },
            {"$unwind": "$acc"},
            {
                "$group": {
                    "_id": {"source": "$acc.name", "target": "$kind"},
                    "value": {"$sum": "$amount"},
                }
            },
            {"$facet": {"top": [{"$sort": {"value": -1}}, {"$limit": 10}]}},
            {"$unionWith": {"coll": "archive", "pipeline": [{"$match": {"year": 2024}}]}},
            {"$project": {"r": {"$range": [0, 1000]}}},
        ]
    )


@pytest.mark.parametrize(
    "stage", ["$out", "$merge", "$collStats", "$currentOp", "$documents", "$indexStats"]
)
def test_non_allow_listed_stages_rejected(stage: str) -> None:
    with pytest.raises(UnsafeSourceError):
        check_pipeline([{stage: {}}])


@pytest.mark.parametrize(
    "flt",
    [
        {"$where": "this.a == 1"},
        {"$or": [{"a": 1}, {"$where": "sleep(1000)"}]},
        {"$expr": {"$function": {"body": "x", "args": [], "lang": "js"}}},
        {"a": {"$in": [2**64]}},
        {"a": "$$USER_ROLES"},
    ],
)
def test_unsafe_filters_rejected(flt: dict[str, Any]) -> None:
    with pytest.raises(UnsafeSourceError):
        check_filter(flt)


def test_normal_filter_passes() -> None:
    check_filter({"year": {"$gte": 2020}, "$or": [{"kind": "a"}, {"kind": {"$regex": "^b"}}]})


def test_model_reports_unsafe_pipeline_as_validation_error() -> None:
    with pytest.raises(ValidationError):
        MongoSource(
            connection="c", collection="flows", mode="aggregate", pipeline=BYPASSES["$$USER_ROLES"]
        )


# --------------------------------------------------------------------------- names


@pytest.mark.parametrize(
    "db", ["admin", "local", "config", "ADMIN", "a.b", "a b", "a$b", "", "x" * 65, "a\x00"]
)
def test_bad_db_names_rejected(db: str) -> None:
    with pytest.raises(UnsafeSourceError):
        validate_db_name(db)


@pytest.mark.parametrize("coll", ["system.users", "a$b", "", "a\x00", "x" * 121])
def test_bad_collection_names_rejected(coll: str) -> None:
    with pytest.raises(UnsafeSourceError):
        validate_collection_name(coll)


def test_good_names_pass() -> None:
    validate_namespace("flows", "bank.transactions")
    with pytest.raises(UnsafeSourceError):
        validate_namespace("admin", "flows")
    with pytest.raises(UnsafeSourceError):
        validate_namespace("flows", "system.users")


@pytest.mark.parametrize("db", ["admin", "local", "config"])
def test_system_databases_cannot_be_a_source_or_a_store(db: str) -> None:
    with pytest.raises(ValidationError):
        MongoSource(connection="c", database=db, collection="flows")
    with pytest.raises(ValidationError):
        AppSettings(storage_database=db)
    with pytest.raises(ValidationError):
        MongoConnection(name="c", uri=SecretStr("mongodb://h/"), default_database=db)


def test_settings_database_names_use_the_same_character_rules() -> None:
    for bad in ("a b$c", "x.y", "a/b"):
        with pytest.raises(ValidationError):
            AppSettings(storage_database=bad)
        with pytest.raises(ValidationError):
            MongoConnection(name="c", uri=SecretStr("mongodb://h/"), default_database=bad)


@pytest.mark.parametrize("field", ["$value", "$$ROOT", "a.$b", "", " ", "a b", ".a"])
def test_field_paths_cannot_be_expressions(field: str) -> None:
    with pytest.raises(ValidationError):
        MongoSource(connection="c", collection="flows", value_field=field)


def test_dotted_field_paths_with_digits_are_fine() -> None:
    source = MongoSource(
        connection="c", collection="flows", source_field="meta.0.from", category_field="a-b.c_d"
    )
    assert (source.source_field, source.category_field) == ("meta.0.from", "a-b.c_d")


# --------------------------------------------------------------------------- URIs

BAD_URIS = [
    "mongodb://h/?tlsCAFile=/etc/passwd",
    "mongodb://h/?TLSCAFILE=/etc/passwd",
    "mongodb://h/?tlsCertificateKeyFile=/home/x/.ssh/id",
    "mongodb://h/?tlsCertificateKeyFilePassword=pw",
    "mongodb://h/?tlsCRLFile=/x",
    "mongodb://h/?sslClientCertificateKeyFile=/x",
    "mongodb://h/?authMechanism=MONGODB-OIDC&authMechanismProperties=ENVIRONMENT:k8s",
    "mongodb://h/?authMechanism=MONGODB-AWS",
    "mongodb://h/?authMechanism=GSSAPI",
    "mongodb://h/?authMechanism=PLAIN",
    "mongodb://h/?authMechanism=MONGODB-X509",
    "mongodb://h/?authMechanismProperties=AWS_SESSION_TOKEN:x",
    "mongodb://h/?authMechanismPropert%69es=ENVIRONMENT:k8s",
    "mongodb://h/?tls%43AFile=/x.pem",
    "mongodb://h/?tlsAllowInvalidCertificates=true",
    "mongodb://h/?tlsInsecure=true",
    "mongodb://h/?proxyHost=evil.example",
    "mongodb://h/?appName=x;tlsCAFile=/etc/passwd",
    "mongodb+srv://h.example.com/?tlsCAFile=/etc/passwd",
    "mongodb+srv://h1.example.com,h2.example.com/",
    "mongodb+srv://h.example.com:27017/",
    "mongodb://h/?unknownOption=1",
    "mongodb://u:p/w@h/db",
    "http://h/",
    "mongodb://",
    # control characters anywhere inside the string (a trailing one is just stripped)
    "mongodb://h\n/db",
    "mongodb://h\r\n/db",
    "mongodb://h\t/db",
    "mongodb://u:pw\x00@h/db",
    "mongodb://h/d\x85b",
    "mongodb://h/db?appName=a\x1bb",
    "mongodb://h/db?w=1\x7f",
    "mongodb://h1,\nh2/",
    "mongodb+srv://h.example.com\n/db",
    "mongodb+srv://h.example.com/\x00",
]


@pytest.mark.parametrize("uri", BAD_URIS)
def test_dangerous_uris_rejected_without_echoing_them(uri: str) -> None:
    with pytest.raises(UnsafeSourceError) as info:
        check_mongo_uri(uri)
    message = info.value.message
    for token in ("/etc/passwd", "/home/x", "evil.example", "pw", "k8s", "AWS_SESSION"):
        assert token not in message


@pytest.mark.parametrize(
    ("uri", "option"),
    [
        ("mongodb://h/?tlsCAFile=/x.pem", "tlsCAFile"),
        ("mongodb://h/?tls%43AFile=/x.pem", "tlsCAFile"),
        ("mongodb://h/?%74lsInsecure=true", "tlsInsecure"),
        (
            "mongodb://h/?appName=a&authMechanismPropert%69es=ENVIRONMENT:k8s",
            "authMechanismProperties",
        ),
        ("mongodb://h/?authMechanism=PLA%49N", "authMechanism"),
    ],
)
def test_forbidden_options_are_named_and_rejected_before_the_driver_parses(
    uri: str, option: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Percent-encoded option keys are decoded for the deny check, and the driver (whose
    parsing of ``tlsCAFile`` touches the file system) is never reached for them."""

    def _driver_must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the driver parsed a URI with a forbidden option")

    monkeypatch.setattr("sankey_studio.mongo_safety.parse_uri", _driver_must_not_run)
    with pytest.raises(UnsafeSourceError, match=f"'{option}' is not allowed"):
        check_mongo_uri(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://localhost:27017",
        "mongodb://u:pw@h1:27017,h2:27017/db?replicaSet=rs0&authSource=admin&tls=true",
        "mongodb://u:pw@h/db?authMechanism=SCRAM-SHA-256&retryWrites=true&w=majority",
        "mongodb://u:p%40ss@h/?authMechanism=DEFAULT",
        "mongodb+srv://u:pw@cluster0.abc.mongodb.net/db?retryWrites=true",
    ],
)
def test_ordinary_uris_pass(uri: str) -> None:
    check_mongo_uri(uri)


def test_connection_model_applies_uri_checks_and_keeps_secret_out_of_errors() -> None:
    with pytest.raises(ValidationError) as info:
        MongoConnection(name="c", uri=SecretStr("mongodb://u:hunter2@h/?tlsCAFile=/etc/passwd"))
    text = str(info.value)
    assert "hunter2" not in text
    assert "/etc/passwd" not in text
    assert "tlsCAFile" in text  # the offending KEY is named


def test_surrounding_whitespace_is_stripped_not_rejected() -> None:
    check_mongo_uri("  mongodb://h/db\n")
    check_mongo_uri("\tmongodb+srv://h.example.com/db\r\n")


# --------------------------------------------------------------------------- hostile shapes


def _nested_dicts(depth: int) -> dict[str, Any]:
    root: dict[str, Any] = {}
    node = root
    for _ in range(depth):
        child: dict[str, Any] = {}
        node["a"] = child
        node = child
    return root


def _nested_lists(depth: int) -> list[Any]:
    root: list[Any] = []
    node = root
    for _ in range(depth):
        child: list[Any] = []
        node.append(child)
        node = child
    return root


@pytest.mark.parametrize("depth", [MAX_DEPTH + 2, 2_000, 100_000])
def test_deep_nesting_is_unsafe_not_a_recursion_error(depth: int) -> None:
    for flt in (_nested_dicts(depth), {"a": _nested_lists(depth)}):
        with pytest.raises(UnsafeSourceError, match="deeply"):
            check_filter(flt)
        with pytest.raises(UnsafeSourceError, match="deeply"):
            check_pipeline([{"$match": flt}])
    facet: dict[str, Any] = {"$match": {}}
    for _ in range(depth):
        facet = {"$facet": {"a": [facet]}}
    with pytest.raises(UnsafeSourceError, match="deeply"):
        check_pipeline([facet])


def test_nesting_up_to_the_limit_still_passes() -> None:
    check_filter(_nested_dicts(MAX_DEPTH - 1))


def test_tuples_are_walked_like_lists() -> None:
    """The driver encodes a tuple as an array, so it cannot be a place to hide an operator."""
    with pytest.raises(UnsafeSourceError):
        check_filter({"$or": ({"$where": "1"},)})
    with pytest.raises(UnsafeSourceError):
        check_pipeline([{"$match": {"$or": ({"$where": "1"},)}}])


def test_connection_model_rejects_a_line_break_in_the_uri() -> None:
    with pytest.raises(ValidationError) as info:
        MongoConnection(name="c", uri=SecretStr("mongodb://u:hunter2@h\n/db"))
    assert "hunter2" not in str(info.value)
