# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``mongo_safety`` / ``util``: the allow- and deny-lists are pinned, member by member."""

from __future__ import annotations

from typing import Any

import pytest

from sankey_studio import mongo_safety, util
from sankey_studio.errors import UnsafeSourceError
from sankey_studio.mongo_safety import (
    ALLOWED_AUTH_MECHANISMS,
    ALLOWED_STAGES,
    ALLOWED_SYSTEM_VARIABLES,
    FORBIDDEN_OPERATORS,
    FORBIDDEN_URI_OPTIONS,
    SYSTEM_DATABASES,
    check_mongo_uri,
    check_pipeline,
    validate_db_name,
)
from sankey_studio.util import MASKED_URI, SAFE_URI_OPTIONS, mask_uri

STAGE_BODIES: dict[str, Any] = {
    "$match": {"a": 1},
    "$project": {"a": 1},
    "$addFields": {"b": "$a"},
    "$set": {"b": "$a"},
    "$unset": "a",
    "$group": {"_id": "$a", "n": {"$sum": 1}},
    "$sort": {"a": -1},
    "$limit": 10,
    "$skip": 1,
    "$unwind": "$a",
    "$lookup": {"from": "c", "localField": "a", "foreignField": "b", "as": "x"},
    "$count": "n",
    "$replaceRoot": {"newRoot": "$a"},
    "$replaceWith": "$a",
    "$bucket": {"groupBy": "$a", "boundaries": [0, 10], "default": "other"},
    "$bucketAuto": {"groupBy": "$a", "buckets": 3},
    "$sortByCount": "$a",
    "$sample": {"size": 5},
    "$facet": {"a": [{"$match": {}}]},
    "$unionWith": "c",
}


def test_the_stage_allow_list_is_exactly_this() -> None:
    assert set(STAGE_BODIES) == ALLOWED_STAGES


@pytest.mark.parametrize("stage", sorted(STAGE_BODIES))
def test_every_allowed_stage_passes_alone_and_in_a_facet(stage: str) -> None:
    check_pipeline([{stage: STAGE_BODIES[stage]}])
    if stage != "$facet":
        check_pipeline([{"$facet": {"a": [{stage: STAGE_BODIES[stage]}]}}])


@pytest.mark.parametrize(
    "stage",
    [
        "$collStats",
        "$indexStats",
        "$planCacheStats",
        "$currentOp",
        "$listSessions",
        "$listLocalSessions",
        "$documents",
        "$graphLookup",
        "$geoNear",
        "$redact",
        "$search",
        "$changeStream",
        "$fill",
        "$densify",
        "$setWindowFields",
        "$match ",
        "match",
        "",
    ],
)
def test_other_stages_are_refused_by_name(stage: str) -> None:
    with pytest.raises(UnsafeSourceError) as info:
        check_pipeline([{stage: {}}])
    assert info.value.message == f"pipeline stage {stage} is not allowed (read-only)"


def test_the_deny_and_allow_lists_have_these_members() -> None:
    assert {"$where", "$function", "$accumulator", "$out", "$merge"} == FORBIDDEN_OPERATORS
    assert {"admin", "local", "config"} == SYSTEM_DATABASES
    assert {"ROOT", "CURRENT", "NOW", "REMOVE", "DESCEND", "PRUNE", "KEEP"} == (
        ALLOWED_SYSTEM_VARIABLES
    )
    assert {"DEFAULT", "SCRAM-SHA-1", "SCRAM-SHA-256"} == ALLOWED_AUTH_MECHANISMS


def test_numeric_limits_are_pinned() -> None:
    assert (mongo_safety.MAX_DEPTH, mongo_safety.MAX_JSON_BYTES) == (24, 65_536)
    assert (mongo_safety.MAX_LOOKUPS, mongo_safety.MAX_UNWINDS, mongo_safety.MAX_FACETS) == (
        3,
        2,
        1,
    )
    assert mongo_safety.MAX_RANGE_SPAN == 100_000
    assert (mongo_safety.INT64_MIN, mongo_safety.INT64_MAX) == (-(2**63), 2**63 - 1)
    assert (mongo_safety.DB_NAME_MAX, mongo_safety.COLLECTION_NAME_MAX) == (64, 120)


@pytest.mark.parametrize("name", sorted(SYSTEM_DATABASES))
def test_system_databases_are_refused_in_every_spelling(name: str) -> None:
    for spelling in (name, name.upper(), name.title()):
        with pytest.raises(UnsafeSourceError, match="system databases"):
            validate_db_name(spelling)


# --------------------------------------------------------------------------- URI options


def test_forbidden_uri_options_cover_files_credentials_proxies_and_weak_tls() -> None:
    assert {
        "tlscafile",
        "tlscertificatekeyfile",
        "tlscertificatekeyfilepassword",
        "tlscrlfile",
        "tlsinsecure",
        "tlsallowinvalidcertificates",
        "tlsallowinvalidhostnames",
        "sslcafile",
        "sslclientcertificatekeyfile",
        "sslclientcertificatekeypassword",
        "sslcrlfile",
        "sslpemkeyfile",
        "sslpempassphrase",
        "sslallowinvalidcertificates",
        "sslallowinvalidhostnames",
        "authmechanismproperties",
        "gssapiservicename",
    } == FORBIDDEN_URI_OPTIONS


@pytest.mark.parametrize("option", sorted(FORBIDDEN_URI_OPTIONS))
def test_every_forbidden_option_is_refused_in_any_case_and_position(option: str) -> None:
    for spelling in (option, option.upper()):
        for uri in (f"mongodb://h/?{spelling}=x", f"mongodb://h/?w=1&{spelling}=x"):
            with pytest.raises(UnsafeSourceError, match="is not allowed"):
                check_mongo_uri(uri)


def test_uri_option_allow_list_for_display_is_pinned() -> None:
    assert {
        "replicaset",
        "authsource",
        "authmechanism",
        "tls",
        "ssl",
        "retrywrites",
        "retryreads",
        "w",
        "readpreference",
        "appname",
        "directconnection",
        "loadbalanced",
    } == SAFE_URI_OPTIONS
    assert not SAFE_URI_OPTIONS & FORBIDDEN_URI_OPTIONS


@pytest.mark.parametrize("option", sorted(FORBIDDEN_URI_OPTIONS))
def test_no_forbidden_option_value_is_ever_shown_masked(option: str) -> None:
    assert mask_uri(f"mongodb://h/?{option}=secret1") == f"mongodb://h/?{option}=***"


@pytest.mark.parametrize("option", sorted(SAFE_URI_OPTIONS))
def test_safe_options_show_plain_values_only(option: str) -> None:
    assert mask_uri(f"mongodb://h/?{option}=abc") == f"mongodb://h/?{option}=abc"
    assert mask_uri(f"mongodb://h/?{option}=a b") == f"mongodb://h/?{option}=***"
    assert mask_uri(f"mongodb://h/?{option}={'a' * 64}") == f"mongodb://h/?{option}={'a' * 64}"
    assert mask_uri(f"mongodb://h/?{option}={'a' * 65}") == f"mongodb://h/?{option}=***"


def test_mask_uri_never_raises_whatever_it_is_given() -> None:
    for junk in (None, 5, b"mongodb://u:pw@h", ["mongodb://u:pw@h"]):
        assert mask_uri(junk) == MASKED_URI  # type: ignore[arg-type]
    assert util.MASK == "***"
    assert util.MASKED_URI == "mongodb://***"
