# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``mongo_safety``: the character classes of the SRV host and URI regexes, edge by edge."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.mongo_safety import check_mongo_uri, validate_db_name
from tests.safety_support import ACCEPTED, outcome_of

GENERIC = "uri is not a valid MongoDB connection string"
DB_INVALID = "invalid MongoDB database name"

LABEL_EDGES = ("a", "A", "z", "Z", "0", "9")
NOT_LABEL = ("`", "{", "[", "_", "!")  # just outside the a-z, A-Z and 0-9 ranges, and more


def srv(host: str) -> str:
    return f"mongodb+srv://{host}"


SRV_HOSTS = {
    **{f"first character {c}": (f"{c}x.example.com", ACCEPTED) for c in LABEL_EDGES},
    **{f"last character {c}": (f"x.example.com{c}", ACCEPTED) for c in LABEL_EDGES},
    **{f"inner character {c}": (f"x{c}x.example.com", ACCEPTED) for c in (*LABEL_EDGES, ".", "-")},
    **{f"single character {c}": (c, ACCEPTED) for c in LABEL_EDGES},
    **{
        f"first character {c!r}": (f"{c}x.example.com", GENERIC)
        for c in (*NOT_LABEL, " ", ".", "-")
    },
    **{f"last character {c!r}": (f"x.example.com{c}", GENERIC) for c in (*NOT_LABEL, ".", "-")},
    **{f"inner character {c!r}": (f"x{c}x.example.com", GENERIC) for c in (*NOT_LABEL, " ")},
}


@pytest.mark.parametrize(("host", "expected"), SRV_HOSTS.values(), ids=SRV_HOSTS)
def test_srv_host_characters(host: str, expected: str) -> None:
    assert outcome_of(check_mongo_uri, srv(host)) == expected


def test_srv_host_length_edges() -> None:
    assert outcome_of(check_mongo_uri, srv("a" * 253)) == ACCEPTED
    assert outcome_of(check_mongo_uri, srv("a" * 254)) == GENERIC
    assert outcome_of(check_mongo_uri, srv("a" + "-" * 251 + "a")) == ACCEPTED
    assert outcome_of(check_mongo_uri, srv("a" + "-" * 252 + "a")) == GENERIC


class Edge(NamedTuple):
    code: int
    rejected: bool


# ``[\x00-\x1f\x7f-\x9f]``: the character sits in the password, where the driver itself is lenient.
URI_EDGES = {
    "NUL": Edge(0x00, rejected=True),
    "SOH": Edge(0x01, rejected=True),
    "record separator": Edge(0x1E, rejected=True),
    "unit separator": Edge(0x1F, rejected=True),
    "space": Edge(0x20, rejected=False),
    "tilde": Edge(0x7E, rejected=False),
    "DEL": Edge(0x7F, rejected=True),
    "first C1 control": Edge(0x80, rejected=True),
    "next to last C1 control": Edge(0x9E, rejected=True),
    "last C1 control": Edge(0x9F, rejected=True),
    "no-break space": Edge(0xA0, rejected=False),
    "inverted exclamation mark": Edge(0xA1, rejected=False),
}


@pytest.mark.parametrize("case", URI_EDGES.values(), ids=URI_EDGES)
def test_uri_control_character_edges(case: Edge) -> None:
    uri = f"mongodb://user:pa{chr(case.code)}ss@db.example.com/flows"
    assert outcome_of(check_mongo_uri, uri) == (GENERIC if case.rejected else ACCEPTED)


FORBIDDEN_DB_CHARS = ["/", "\\", ".", " ", '"', "$", "*", "<", ">", ":", "|", "?"]


@pytest.mark.parametrize("char", FORBIDDEN_DB_CHARS)
def test_each_forbidden_database_character_is_refused(char: str) -> None:
    assert outcome_of(validate_db_name, f"a{char}b") == DB_INVALID
    assert outcome_of(validate_db_name, "ab") == ACCEPTED
