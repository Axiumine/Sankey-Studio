# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Edges of the CSRF helpers that the full stack cannot reach: a host is never matched by prefix."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.web.middleware import host_allowed, origin_of


class HostCase(NamedTuple):
    host: str
    allowed: list[str]
    expected: bool


HOSTS = [
    HostCase("localhost.evil.com", ["localhost"], False),
    HostCase("localhost2", ["localhost"], False),
    HostCase("evil.localhost", ["localhost"], False),
    HostCase("127.0.0.1.evil.com", ["127.0.0.1"], False),
    HostCase("localhost", ["localhost.evil.com"], False),
    HostCase("a.example.com.evil.com", ["*.example.com"], False),
    HostCase("x.example.com", ["*.example.com", "other"], True),
    HostCase("other", ["*.example.com", "other"], True),
]


@pytest.mark.parametrize("case", HOSTS, ids=lambda c: f"{c.host}-{c.allowed}")
def test_a_host_matches_exactly_or_by_suffix_wildcard_only(case: HostCase) -> None:
    assert host_allowed(case.host, case.allowed) is case.expected


class SchemeCase(NamedTuple):
    value: str
    parsed: tuple[str, str, int] | None


SCHEMES = [
    SchemeCase("http://localhost", ("http", "localhost", 80)),
    SchemeCase("https://localhost", ("https", "localhost", 443)),
    SchemeCase("ws://localhost", None),
    SchemeCase("wss://localhost", None),
    SchemeCase("file://localhost", None),
    SchemeCase("chrome-extension://localhost", None),
    SchemeCase("blob:http://localhost", None),
    SchemeCase("data:text/plain,localhost", None),
    SchemeCase("HTTP://localhost", ("http", "localhost", 80)),
    SchemeCase("javascript://localhost", None),
]


@pytest.mark.parametrize("case", SCHEMES, ids=lambda c: c.value)
def test_only_http_and_https_origins_parse(case: SchemeCase) -> None:
    assert origin_of(case.value) == case.parsed
