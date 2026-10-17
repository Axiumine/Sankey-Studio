# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Fuzz targets for the guards that decide what user text may reach MongoDB or the disk.

Each ``fuzz_*`` function takes the raw bytes of one input. The domain errors the guards raise on
purpose (``UnsafeSourceError``, ``SourceError``, ``ValueError``) are swallowed; any other
exception, a hang, or an ACCEPTED input that breaks what the guard promises is a finding.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from pymongo.uri_parser import parse_uri

from sankey_studio.errors import SourceError, UnsafeSourceError
from sankey_studio.mongo_safety import (
    ALLOWED_AUTH_MECHANISMS,
    ALLOWED_STAGES,
    FORBIDDEN_OPERATORS,
    FORBIDDEN_URI_OPTIONS,
    SYSTEM_DATABASES,
    check_filter,
    check_mongo_uri,
    check_pipeline,
    validate_collection_name,
    validate_db_name,
)
from sankey_studio.render.numfmt import format_value
from sankey_studio.sources.files.names import clean_filename
from sankey_studio.sources.files.paths import ALLOWED_EXTENSIONS
from sankey_studio.util import looks_masked, mask_uri, normalize_category

if TYPE_CHECKING:
    from collections.abc import Callable

#: A password no seed or mutation is likely to contain; a masked URI must never show it.
SECRET = "zq7xkvp"
#: format_value pads to at most 100 characters and prints at most ~330 digits.
OUTPUT_MAX = 1000
UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


def text_of(data: bytes) -> str:
    return data.decode("utf-8", "surrogateescape")


def operators_in(doc: object) -> set[str]:
    """Every forbidden operator used as a key anywhere in ``doc`` (iterative: no recursion)."""
    found: set[str] = set()
    stack = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            found.update(key for key in node if key in FORBIDDEN_OPERATORS)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def guarded(check: Callable[[Any], None], doc: object) -> bool:
    """Run a guard; when it accepts ``doc`` (True), no forbidden operator may be left in it."""
    try:
        check(doc)
    except UnsafeSourceError:
        return False
    assert not operators_in(doc), f"{check.__name__} accepted a forbidden operator"
    return True


def check_stages(pipeline: list[Any]) -> None:
    """An accepted pipeline holds one allow-listed stage per element."""
    for stage in pipeline:
        assert isinstance(stage, dict)
        assert len(stage) == 1
        assert next(iter(stage)) in ALLOWED_STAGES


def fuzz_mongo_guard(data: bytes) -> None:
    """``check_filter`` and ``check_pipeline`` on any JSON document."""
    try:
        doc = json.loads(data.decode("utf-8", "replace"))
    except ValueError, RecursionError:  # not JSON, a number past the digit limit, or too deep
        doc = {}  # the empty filter: every input, the empty one too, reaches the guard
    if isinstance(doc, dict):
        guarded(check_filter, doc)
        guarded(check_pipeline, [doc])
    elif isinstance(doc, list) and guarded(check_pipeline, doc):
        check_stages(doc)


def check_driver_options(raw: str) -> None:
    """What the DRIVER reads from an accepted URI (it folds aliases) must be allowed too."""
    options = dict(parse_uri(raw, validate=True, warn=False)["options"])
    names = {str(name).casefold() for name in options}
    risky = {name for name in names if name in FORBIDDEN_URI_OPTIONS or name.startswith("proxy")}
    assert not risky, f"the guard accepted a URI whose options {sorted(risky)} the driver reads"
    assert options.get("authMechanism") in (None, *ALLOWED_AUTH_MECHANISMS)


def fuzz_mongo_uri(data: bytes) -> None:
    """``check_mongo_uri`` against the driver's own reading, and ``mask_uri`` against leaks."""
    text = text_of(data)
    try:
        check_mongo_uri(text)
    except UnsafeSourceError:
        pass
    else:
        if text.strip().startswith("mongodb://"):
            check_driver_options(text.strip())
    assert isinstance(mask_uri(text), str)
    assert isinstance(looks_masked(text), bool)
    if SECRET not in text:
        assert SECRET not in mask_uri(f"mongodb://user:{SECRET}@{text}")
        assert SECRET not in mask_uri(
            f"mongodb://h/db?tlsCertificateKeyFilePassword={SECRET}&{text}"
        )


def check_db_name(name: str) -> None:
    try:
        assert validate_db_name(name) == name
    except UnsafeSourceError:
        return
    assert name.casefold() not in SYSTEM_DATABASES
    assert 0 < len(name) <= 64
    assert not any(unicodedata.category(char) in UNSAFE_CATEGORIES for char in name)


def check_collection_name(name: str) -> None:
    try:
        assert validate_collection_name(name) == name
    except UnsafeSourceError:
        return
    assert "$" not in name
    assert not name.startswith("system.")
    assert not any(unicodedata.category(char) in UNSAFE_CATEGORIES for char in name)


def check_filename(raw: str) -> None:
    """An accepted upload name is one plain, short, normalised file name with an allowed type."""
    try:
        name = clean_filename(raw)
    except SourceError:
        return
    assert PurePosixPath(name).name == name
    assert "/" not in name
    assert "\\" not in name
    assert not name.startswith(".")
    assert len(name.encode("utf-8")) <= 255
    assert unicodedata.is_normalized("NFC", name)
    assert PurePosixPath(name).suffix.casefold() in ALLOWED_EXTENSIONS


def check_category(raw: str) -> None:
    try:
        once = normalize_category(raw)
    except ValueError:
        return
    assert normalize_category(once) == once, "normalising twice changed the category"


def fuzz_names(data: bytes) -> None:
    """The identifier validators: database, collection, upload file name and category."""
    text = text_of(data)
    database, _, collection = text.partition("\n")
    check_db_name(database)
    check_collection_name(collection)
    check_filename(text)
    check_category(text)


def fuzz_numfmt(data: bytes) -> None:
    """``format_value(number, spec)`` must answer any pair with a short string, never raise."""
    head, _, spec = text_of(data).partition("\n")
    try:
        value = float(head)
    except ValueError:
        value = 0.0  # not a number: still format something, so no input skips the code
    out = format_value(value, spec)
    assert isinstance(out, str)
    assert len(out) <= OUTPUT_MAX, len(out)
