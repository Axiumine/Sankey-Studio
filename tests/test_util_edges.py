# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``util``: split points, boundaries and messages of the URI masker and the category helpers."""

from __future__ import annotations

import pytest

from sankey_studio.util import (
    MASK,
    MASKED_URI,
    category_key,
    is_reserved_category,
    looks_masked,
    mask_uri,
    normalize_category,
)

HOSTS_MAX = 2000


def hosts_of_length(length: int) -> str:
    """A comma separated host list of exactly ``length`` characters."""
    hosts = ",".join(["a"] * ((length + 1) // 2))
    return hosts[:length] if len(hosts) >= length else hosts + "a" * (length - len(hosts))


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        # no path: the host list is the whole authority
        ("mongodb://host", "mongodb://host"),
        ("mongodb://u:pw@host", "mongodb://u:***@host"),
        ("mongodb://host?w=1", "mongodb://host?w=1"),
        # an empty userinfo (the "@" is the first character) is still a userinfo
        ("mongodb://@host", "mongodb://***@host"),
        ("mongodb://@host/db", "mongodb://***@host/db"),
        # the user is everything before the FIRST colon, the password everything after
        ("mongodb://u:p:w@h/", "mongodb://u:***@h/"),
        ("mongodb://:pw@h/", "mongodb://***@h/"),
        # query items: empty and unreadable ones are dropped, the rest is kept
        ("mongodb://h/?&w=1", "mongodb://h/?w=1"),
        ("mongodb://h/?;;w=1", "mongodb://h/?w=1"),
        ("mongodb://h/?1bad=x&w=1", "mongodb://h/?w=1"),
        ("mongodb://h/?w=1&1bad=x&appName=a", "mongodb://h/?w=1&appName=a"),
        ("mongodb://h/?=x&w=1", "mongodb://h/?w=1"),
        # the value is everything after the FIRST "=": an odd one is masked, not re-split
        ("mongodb://h/?w=a=b", "mongodb://h/?w=***"),
        (
            "mongodb://h/?replicaSet=rs0&authSource=admin",
            "mongodb://h/?replicaSet=rs0&authSource=admin",
        ),
        # only the safe keys show a plain value; the others keep their key and lose the value
        ("mongodb://h/?TLS=true&Foo=bar", "mongodb://h/?TLS=true&Foo=***"),
        # nothing readable is left of the query
        ("mongodb://h/?1=2", "mongodb://h/"),
        ("mongodb://h?1=2", "mongodb://h"),
    ],
)
def test_mask_uri_split_points(uri: str, expected: str) -> None:
    assert mask_uri(uri) == expected


def test_mask_uri_host_list_length_limit() -> None:
    at_limit = hosts_of_length(HOSTS_MAX)
    assert len(at_limit) == HOSTS_MAX
    assert mask_uri(f"mongodb://{at_limit}") == f"mongodb://{at_limit}"
    over = hosts_of_length(HOSTS_MAX + 1)
    assert mask_uri(f"mongodb://{over}") == MASKED_URI


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # the query starts at the FIRST "?" after the last "@", not at a later one
        ("mongodb://h/?a=***&b=c?d", True),
        # a password may hold "?" and "@": the query starts after the LAST "@"
        ("mongodb://u:p?w@x@h/?a=***", True),
        ("mongodb://u:p@w@h/?a=***&b=1", True),
        ("mongodb://h/?a=b&c=x@y&d=***", False),
        ("mongodb://u:pw@h/?a=b@c=***", False),
        # the placeholders mask_uri writes
        ("***", True),
        ("  ***  ", True),
        ("*", True),
        ("mongodb://***", True),
        ("mongodb://u:***@h/db", True),
        ("mongodb://***@h/db", True),
        ("mongodb://h/?w=***", True),
        ("mongodb://h/?w=1&appName=***", True),
        ("mongodb://h/?w=***;appName=1", True),
        # real values that merely contain asterisks
        ("", False),
        ("   ", False),
        ("mongodb://u:abc***@h/db", False),
        ("mongodb://u:***x@h/db", False),
        ("mongodb://h/?w=a***", False),
        ("mongodb://h/?w=***x", False),
        ("mongodb://h/?w=1", False),
        ("*x", False),
    ],
)
def test_looks_masked_positions(value: str, expected: bool) -> None:
    assert looks_masked(value) is expected


CONTROL = "category must not contain control characters"


@pytest.mark.parametrize("func", [normalize_category, category_key, is_reserved_category])
@pytest.mark.parametrize("bad", ["a\x00b", "a\x1bb", "a\x7fb", "a\x9fb", "a\ud800b"])
def test_control_characters_raise_with_one_message(func: object, bad: str) -> None:
    with pytest.raises(ValueError, match=f"^{CONTROL}$"):
        func(bad)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Food  ", "Food"),
        ("a \t\n b", "a b"),
        ("a\u00a0\u2003b", "a b"),
        ("\u0344", "\u0308\u0301"),
        ("e\u0301", "\u00e9"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_category_table(raw: str, expected: str) -> None:
    assert normalize_category(raw) == expected


def test_category_key_and_reserved_names() -> None:
    assert category_key("  FOOD \t x") == category_key("food x") == "food x"
    assert category_key("Stra\u00dfe") == "strasse"
    assert category_key("") == ""
    for name in ("Other", "OTHER", " other ", "Uncategorized", "uNcAtEgOrIzEd"):
        assert is_reserved_category(name) is True
    for name in ("Others", "Un categorized", "", "Uncategorised", "Another"):
        assert is_reserved_category(name) is False
    assert MASK == "***"
