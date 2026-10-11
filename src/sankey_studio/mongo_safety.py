"""Read-only guard for user-supplied MongoDB filters, pipelines, names and connection URIs.

Contract (v2): pure functions; imports only ``errors`` from this package (``models`` imports this
module, so it must stay dependency-free) plus ``pymongo.uri_parser`` for URI structure.

* Operators that run server-side code or write data are rejected anywhere in the tree.
* Pipelines are validated RECURSIVELY: the top level, every ``$facet`` branch, and every
  ``$lookup.pipeline`` / ``$unionWith.pipeline`` may only use allow-listed read-only stages.
* ``$lookup.from`` / ``$unionWith.coll`` must be plain same-database collection names that pass
  ``validate_collection_name`` (no ``system.*``, no ``{db, coll}`` object form).
* ``$$`` variables: only the benign system variables and user variables (lower-case first
  letter; every privileged system variable such as ``USER_ROLES`` is upper-case).
* Cheap resource caps: nesting depth, JSON size, number of ``$lookup``/``$unionWith``/``$unwind``/
  ``$facet``, literal ``$range`` spans, int64 range.
* Names: ``validate_db_name`` / ``validate_collection_name`` / ``validate_namespace`` are shared by
  ``MongoSource``, the settings models and every inspect endpoint. ``admin``, ``local`` and
  ``config`` are never readable. Control, format (bidi) and surrogate characters are refused in
  names: the inspect endpoints pass raw query parameters straight through.
* The tree walk follows every ``collections.abc.Mapping`` (the driver encodes any mapping as a
  document), not only ``dict``.
* ``check_mongo_uri`` is applied when a connection is saved: it refuses options that read local
  files or credentials (``tlsCAFile``, OIDC/AWS/GSSAPI mechanisms, proxies, ...).

Edit this file in a scratch copy and move it in only after
``python -c "import sankey_studio.models"`` passes: every other module imports it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from typing import TYPE_CHECKING
from urllib.parse import unquote

from pymongo.uri_parser import parse_uri

from sankey_studio.errors import UnsafeSourceError

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Anywhere in a filter or pipeline tree. ``$expr`` itself is read-only and allowed; code
#: operators nested inside it are caught by the tree walk.
FORBIDDEN_OPERATORS = frozenset({"$where", "$function", "$accumulator", "$out", "$merge"})

ALLOWED_STAGES = frozenset(
    {
        "$match",
        "$project",
        "$addFields",
        "$set",
        "$unset",
        "$group",
        "$sort",
        "$limit",
        "$skip",
        "$unwind",
        "$lookup",
        "$count",
        "$replaceRoot",
        "$replaceWith",
        "$bucket",
        "$bucketAuto",
        "$sortByCount",
        "$sample",
        "$facet",
        "$unionWith",
    }
)

SYSTEM_DATABASES = frozenset({"admin", "local", "config"})
#: ``$$NAME`` variables that are safe to use. User variables start with a lower-case letter.
ALLOWED_SYSTEM_VARIABLES = frozenset(
    {"ROOT", "CURRENT", "NOW", "REMOVE", "DESCEND", "PRUNE", "KEEP"}
)

MAX_DEPTH = 24
MAX_JSON_BYTES = 64 * 1024
MAX_LOOKUPS = 3  # $lookup + $unionWith together
MAX_UNWINDS = 2
MAX_FACETS = 1
MAX_RANGE_SPAN = 100_000
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
DB_NAME_MAX = 64
COLLECTION_NAME_MAX = 120

_DB_NAME_FORBIDDEN = frozenset('/\\. "$*<>:|?\0')
#: Unicode categories refused in database and collection names: control (Cc), format such as the
#: bidi overrides (Cf) and lone surrogates (Cs, which cannot be encoded to UTF-8 at all).
_UNSAFE_NAME_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})
_LOOKUP_KEYS = frozenset({"from", "localField", "foreignField", "let", "pipeline", "as"})
_UNION_KEYS = frozenset({"coll", "pipeline"})

# --------------------------------------------------------------------------- names


def _has_unsafe_characters(name: str) -> bool:
    return any(unicodedata.category(char) in _UNSAFE_NAME_CATEGORIES for char in name)


def validate_db_name(name: str) -> str:
    """Return ``name`` if it is a readable/writable database, else raise ``UnsafeSourceError``."""
    if (
        not name
        or len(name) > DB_NAME_MAX
        or any(c in _DB_NAME_FORBIDDEN for c in name)
        or _has_unsafe_characters(name)
    ):
        raise UnsafeSourceError("invalid MongoDB database name")
    if name.casefold() in SYSTEM_DATABASES:
        raise UnsafeSourceError("MongoDB system databases (admin, local, config) are not allowed")
    return name


def validate_collection_name(name: str) -> str:
    """Return ``name`` if it is a plain user collection name; else ``UnsafeSourceError``."""
    if (
        not name
        or len(name) > COLLECTION_NAME_MAX
        or "$" in name
        or _has_unsafe_characters(name)  # includes NUL
    ):
        raise UnsafeSourceError("invalid MongoDB collection name")
    if name.startswith("system."):
        raise UnsafeSourceError("MongoDB system collections are not allowed")
    return name


def validate_namespace(database: str, collection: str) -> None:
    """Validate a ``database.collection`` pair (used by every source and inspect call)."""
    validate_db_name(database)
    validate_collection_name(collection)


# --------------------------------------------------------------------------- tree walk


class _State:
    """Counters shared by one ``check_pipeline`` / ``check_filter`` call."""

    __slots__ = ("facets", "lookups", "unwinds")

    def __init__(self) -> None:
        self.lookups = 0
        self.unwinds = 0
        self.facets = 0


def _check_value(value: object) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int) and not INT64_MIN <= value <= INT64_MAX:
        raise UnsafeSourceError("filter/pipeline integers must fit in 64 bits")
    if isinstance(value, str) and value.startswith("$$"):
        name = value[2:].partition(".")[0]
        if name not in ALLOWED_SYSTEM_VARIABLES and not (name[:1].isascii() and name[:1].islower()):
            raise UnsafeSourceError("MongoDB variable reference is not allowed")


def _check_range(args: object) -> None:
    """Reject ``$range`` with literal bounds that would materialise a huge array."""
    if not isinstance(args, list) or len(args) < 2:  # noqa: PLR2004 - $range is [start, end]
        return
    nums = [a for a in args if isinstance(a, int | float) and not isinstance(a, bool)]
    if len(nums) != len(args):
        return  # non-literal bounds cannot be judged here
    step = abs(nums[2]) if len(nums) > 2 and nums[2] else 1  # noqa: PLR2004 - [start, end, step]
    if abs(nums[1] - nums[0]) / step > MAX_RANGE_SPAN:
        raise UnsafeSourceError(f"$range spans more than {MAX_RANGE_SPAN} elements")


def _walk(node: object, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise UnsafeSourceError("filter/pipeline is nested too deeply")
    if isinstance(node, Mapping):
        for key, value in node.items():
            if not isinstance(key, str):
                raise UnsafeSourceError("filter/pipeline keys must be strings")
            if "\0" in key:
                raise UnsafeSourceError("filter/pipeline keys must not contain NUL")
            if key in FORBIDDEN_OPERATORS:
                raise UnsafeSourceError(f"MongoDB operator {key} is not allowed (read-only)")
            if key == "$range":
                _check_range(value)
            _walk(value, depth + 1)
    elif isinstance(node, list | tuple):  # the driver encodes a tuple as an array
        for item in node:
            _walk(item, depth + 1)
    else:
        _check_value(node)


def _check_size(obj: object) -> None:
    """Callers run ``_walk`` first: it bounds the nesting that ``json.dumps`` would recurse into."""
    try:
        size = len(json.dumps(obj, default=str))
    except RecursionError as exc:
        raise UnsafeSourceError("filter/pipeline is nested too deeply") from exc
    except (TypeError, ValueError) as exc:
        raise UnsafeSourceError("filter/pipeline must be plain JSON") from exc
    if size > MAX_JSON_BYTES:
        raise UnsafeSourceError("filter/pipeline is too large")


# --------------------------------------------------------------------------- stages


def _check_lookup(spec: object, state: _State) -> None:
    state.lookups += 1
    if not isinstance(spec, dict) or not set(spec) <= _LOOKUP_KEYS:
        raise UnsafeSourceError(
            "$lookup must be an object using only from/localField/foreignField/let/pipeline/as"
        )
    source = spec.get("from")
    if not isinstance(source, str):
        raise UnsafeSourceError("$lookup.from must be a collection name string")
    validate_collection_name(source)
    if "pipeline" in spec:
        _check_stage_list(spec["pipeline"], state)


def _check_union(spec: object, state: _State) -> None:
    state.lookups += 1
    if isinstance(spec, str):
        validate_collection_name(spec)
        return
    if not isinstance(spec, dict) or not set(spec) <= _UNION_KEYS:
        raise UnsafeSourceError("$unionWith must be a collection name or {coll, pipeline}")
    coll = spec.get("coll")
    if not isinstance(coll, str):
        raise UnsafeSourceError("$unionWith.coll must be a collection name string")
    validate_collection_name(coll)
    if "pipeline" in spec:
        _check_stage_list(spec["pipeline"], state)


def _check_facet(spec: object, state: _State) -> None:
    state.facets += 1
    if not isinstance(spec, dict):
        raise UnsafeSourceError("$facet must be an object of named pipelines")
    for branch in spec.values():
        _check_stage_list(branch, state)


def _check_stage(stage: object, index: int, state: _State) -> None:
    if not isinstance(stage, dict) or len(stage) != 1:
        raise UnsafeSourceError(f"pipeline stage {index} must be an object with one key")
    ((name, spec),) = stage.items()
    if name not in ALLOWED_STAGES:
        raise UnsafeSourceError(f"pipeline stage {name} is not allowed (read-only)")
    if name == "$lookup":
        _check_lookup(spec, state)
    elif name == "$unionWith":
        _check_union(spec, state)
    elif name == "$facet":
        _check_facet(spec, state)
    elif name == "$unwind":
        state.unwinds += 1


def _check_stage_list(stages: object, state: _State) -> None:
    """Callers run ``_walk`` first, which already caps the nesting this recurses through."""
    if not isinstance(stages, list):
        raise UnsafeSourceError("a pipeline must be a list of stages")
    for index, stage in enumerate(stages):
        _check_stage(stage, index, state)


def _check_counts(state: _State) -> None:
    if state.lookups > MAX_LOOKUPS:
        raise UnsafeSourceError(f"at most {MAX_LOOKUPS} $lookup/$unionWith stages are allowed")
    if state.unwinds > MAX_UNWINDS:
        raise UnsafeSourceError(f"at most {MAX_UNWINDS} $unwind stages are allowed")
    if state.facets > MAX_FACETS:
        raise UnsafeSourceError(f"at most {MAX_FACETS} $facet stage is allowed")


# --------------------------------------------------------------------------- public API


def check_filter(flt: Mapping[str, object]) -> None:
    """Raise ``UnsafeSourceError`` if the ``find`` filter could run code or write."""
    _walk(flt, 0)  # first: it caps the depth, so a 100000-deep dict never reaches json.dumps
    _check_size(flt)


def check_pipeline(pipeline: Sequence[object]) -> None:
    """Raise ``UnsafeSourceError`` unless every stage (recursively) is an allow-listed read."""
    _walk(pipeline, 0)  # first: it caps the depth, so deep nesting never reaches json.dumps
    _check_size(pipeline)
    state = _State()
    _check_stage_list(list(pipeline), state)
    _check_counts(state)


# --------------------------------------------------------------------------- URIs

#: Lower-case option names that make the driver read local files, load credentials from the
#: environment, tunnel through a proxy, or switch certificate validation off.
FORBIDDEN_URI_OPTIONS = frozenset(
    {
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
    }
)
ALLOWED_AUTH_MECHANISMS = frozenset({"DEFAULT", "SCRAM-SHA-1", "SCRAM-SHA-256"})
_URI_PREFIXES = ("mongodb://", "mongodb+srv://")
_GENERIC_URI_ERROR = "uri is not a valid MongoDB connection string"
# \Z, not "$": "$" also matches before a trailing newline.
_SRV_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z")
#: Control characters (Cc) are never part of a connection string; a line break would otherwise
#: survive into logs and masked output.
_URI_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _option_error(key: str) -> UnsafeSourceError:
    """Name the offending option, never its value (and never an odd-looking key)."""
    safe = key if key.isalnum() and key.isascii() and len(key) <= 40 else "?"  # noqa: PLR2004 - longest key echoed
    return UnsafeSourceError(f"uri option '{safe}' is not allowed")


def _scan_uri_options(raw: str) -> None:
    _, _, query = raw.partition("?")
    for item in query.replace(";", "&").split("&"):
        key, _eq, value = item.partition("=")
        name = unquote(key).strip().casefold()
        if not name:
            continue
        if name in FORBIDDEN_URI_OPTIONS or name.startswith("proxy"):
            raise _option_error(unquote(key).strip())
        if (
            name == "authmechanism"
            and unquote(value).strip().upper() not in ALLOWED_AUTH_MECHANISMS
        ):
            raise _option_error(unquote(key).strip())


def _check_srv_host(raw: str) -> None:
    """``mongodb+srv://`` takes exactly one DNS name (no port, no list); no lookup is made here."""
    rest = raw[len("mongodb+srv://") :]
    authority = rest.partition("/")[0].partition("?")[0]
    host = authority.rpartition("@")[2]
    if _SRV_HOST_RE.match(host) is None:
        raise UnsafeSourceError(_GENERIC_URI_ERROR)


def check_mongo_uri(uri: str) -> None:
    """Raise ``UnsafeSourceError`` unless ``uri`` is a plain, credential-safe connection string.

    Options are scanned BEFORE the driver parses the URI (parsing ``tlsCAFile`` touches the file
    system). Messages name option keys only: never the URI, the password or any value. ``+srv``
    URIs are checked structurally without DNS.
    """
    raw = uri.strip()
    if not raw.startswith(_URI_PREFIXES):
        raise UnsafeSourceError("uri must start with mongodb:// or mongodb+srv://")
    if _URI_CONTROL_RE.search(raw):
        raise UnsafeSourceError(_GENERIC_URI_ERROR)
    _scan_uri_options(raw)
    if raw.startswith("mongodb+srv://"):
        _check_srv_host(raw)
        return
    try:
        parse_uri(raw, validate=True, warn=False)
    except Exception:  # noqa: BLE001 - driver messages may echo the URI
        raise UnsafeSourceError(_GENERIC_URI_ERROR) from None
