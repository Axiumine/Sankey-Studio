# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``mongo_safety``: the connection-string checks (option scanner, SRV hosts, driver call)."""

from __future__ import annotations

from typing import Any

import pytest

from sankey_studio import mongo_safety
from sankey_studio.mongo_safety import check_mongo_uri
from tests.safety_support import message_of


def option_message(name: str) -> str:
    return f"uri option '{name}' is not allowed"


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://h/?tlsCAFile=x&appName=a?b",
        "mongodb://h/?appName=a?b&tlsCAFile=x",
        "mongodb://h/?&tlsCAFile=x",
        "mongodb://h/?&&tlsCAFile=x",
        "mongodb://h/?=1&tlsCAFile=x",
        "mongodb://h/?appName=a;;tlsCAFile=x",
        "mongodb://h/?%20&tlsCAFile=x",
        "mongodb://h/?a=b&TLSCAFILE=x",
    ],
)
def test_forbidden_option_is_found_wherever_it_hides(uri: str) -> None:
    assert message_of(check_mongo_uri, uri) == option_message(
        "tlsCAFile" if "TLS" not in uri else "TLSCAFILE"
    )


@pytest.mark.parametrize(
    "uri", ["mongodb://h/?proxyHost=x", "mongodb://h/?PROXYUSERNAME=x", "mongodb://h/?Proxy=1"]
)
def test_every_proxy_option_is_refused(uri: str) -> None:
    key = uri.partition("?")[2].partition("=")[0]
    assert message_of(check_mongo_uri, uri) == option_message(key)


@pytest.mark.parametrize("mechanism", ["DEFAULT", "SCRAM-SHA-1", "SCRAM-SHA-256"])
def test_plain_password_mechanisms_pass(mechanism: str) -> None:
    check_mongo_uri(f"mongodb://u:p@h/?authMechanism={mechanism}")
    check_mongo_uri(f"mongodb://u:p@h/?AUTHMECHANISM={mechanism}")


@pytest.mark.parametrize(
    "mechanism",
    ["PLAIN", "GSSAPI", "MONGODB-AWS", "MONGODB-OIDC", "MONGODB-X509", "SCRAM-SHA-512", ""],
)
def test_other_mechanisms_are_refused_and_the_key_is_named(mechanism: str) -> None:
    uri = f"mongodb://u:p@h/?authMechanism={mechanism}"
    assert message_of(check_mongo_uri, uri) == option_message("authMechanism")


def test_mechanism_value_is_decoded_before_the_check() -> None:
    assert message_of(check_mongo_uri, "mongodb://h/?authMechanism=MONGODB%2DAWS=x") == (
        option_message("authMechanism")
    )
    assert message_of(check_mongo_uri, "mongodb://h/?authMechanism=PLAIN=x") == (
        option_message("authMechanism")
    )


def test_option_names_are_shown_only_when_they_look_like_plain_keys() -> None:
    assert message_of(check_mongo_uri, "mongodb://h/?proxy-x=1") == option_message("?")
    assert message_of(check_mongo_uri, "mongodb://h/?proxy%0Ax=1") == option_message("?")
    assert message_of(check_mongo_uri, "mongodb://h/?proxy\u00e9=1") == option_message("?")
    forty = "proxy" + "a" * 35
    assert message_of(check_mongo_uri, f"mongodb://h/?{forty}=1") == option_message(forty)
    forty_one = forty + "a"
    assert message_of(check_mongo_uri, f"mongodb://h/?{forty_one}=1") == option_message("?")


def test_scheme_error_is_exact() -> None:
    expected = "uri must start with mongodb:// or mongodb+srv://"
    assert message_of(check_mongo_uri, "http://h/") == expected
    assert message_of(check_mongo_uri, "") == expected
    assert message_of(check_mongo_uri, "MONGODB://h/") == expected


def test_driver_is_asked_for_strict_parsing_without_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def spy(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(mongo_safety, "parse_uri", spy)
    check_mongo_uri("  mongodb://u:p@h/db  ")
    assert calls == [(("mongodb://u:p@h/db",), {"validate": True, "warn": False})]


def test_driver_failures_become_a_generic_message_without_the_uri() -> None:
    generic = "uri is not a valid MongoDB connection string"
    assert message_of(check_mongo_uri, "mongodb://u:hunter2@h:notaport/db") == generic
    assert message_of(check_mongo_uri, "mongodb://") == generic
    assert message_of(check_mongo_uri, "mongodb://h/?unknownOption=1") == generic


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb+srv://h.example.com",
        "mongodb+srv://h.example.com/",
        "mongodb+srv://h.example.com?retryWrites=true",
        "mongodb+srv://u:p@h.example.com?retryWrites=true",
        "mongodb+srv://u:p@h.example.com/db/extra",
        "mongodb+srv://u:p%40x@h.example.com/db",
        "mongodb+srv://a",
        "mongodb+srv://a-b.c-d",
    ],
)
def test_srv_uris_with_one_dns_name_pass(uri: str) -> None:
    check_mongo_uri(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb+srv://",
        "mongodb+srv:///db",
        "mongodb+srv://?x=1",
        "mongodb+srv://h.example.com:27017",
        "mongodb+srv://h1.example.com,h2.example.com",
        "mongodb+srv://-h.example.com",
        "mongodb+srv://h.example.com-",
        "mongodb+srv://u:p@",
        "mongodb+srv://h_x.example.com",
    ],
)
def test_srv_uris_with_anything_else_are_refused(uri: str) -> None:
    assert message_of(check_mongo_uri, uri) == "uri is not a valid MongoDB connection string"


def test_srv_host_label_limits() -> None:
    check_mongo_uri("mongodb+srv://" + "a" * 253)
    assert message_of(check_mongo_uri, "mongodb+srv://" + "a" * 254) == (
        "uri is not a valid MongoDB connection string"
    )


@pytest.mark.parametrize("char", ["\n", "\r", "\t", "\x00", "\x1b", "\x7f", "\x85", "\x9f"])
def test_control_characters_are_refused_with_the_generic_message(char: str) -> None:
    generic = "uri is not a valid MongoDB connection string"
    assert message_of(check_mongo_uri, f"mongodb://h{char}x/db") == generic
    assert message_of(check_mongo_uri, f"mongodb://h/db?w=1{char}x") == generic
