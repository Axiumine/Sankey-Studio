# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Small helpers shared across layers: URI masking and category identity.

Dependency-free on purpose (``models`` and ``mongo`` import this module).
"""

from __future__ import annotations

import re
import unicodedata

MASK = "***"
#: What ``mask_uri`` returns when it has any doubt about a mongodb URI.
MASKED_URI = "mongodb://***"

# --------------------------------------------------------------------------- URI masking

_SCHEME_RE = re.compile(r"^(mongodb(?:\+srv)?)://", re.IGNORECASE)
# Every pattern ends with \Z, never "$": "$" also matches before a trailing newline, which would
# let a line break through into the masked output.
_HOST_RE = re.compile(
    r"^(?:\[[0-9A-Fa-f:.%]{2,64}]|(?:[A-Za-z0-9_-]|%[0-9A-Fa-f]{2})(?:[A-Za-z0-9._-]|%[0-9A-Fa-f]{2})*)"
    r"(?::[0-9]{1,5})?\Z"
)
_HOSTS_MAX = 2000
_USER_RE = re.compile(r"^[A-Za-z0-9._~%+-]{1,128}\Z")
_DB_RE = re.compile(r"^[A-Za-z0-9_.-]{0,64}\Z")
_OPTION_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,39}\Z")
_OPTION_VALUE_RE = re.compile(r"^[A-Za-z0-9_.,-]{0,64}\Z")

#: Query options whose *values* may be shown (lower-case keys). Every other option keeps its key
#: but shows ``***`` as the value: this is an allow-list, so new secret-bearing options fail closed.
SAFE_URI_OPTIONS = frozenset(
    {
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
    }
)

# The positions ``mask_uri`` writes ``***`` into, and only those: the start of the userinfo (after
# the scheme and an optional ``user:``, right before the ``@``), the whole authority (right after
# the scheme) and a whole option value (``key=***``). A password that merely ENDS in ``***`` is
# not one of them.
_MASKED_USERINFO_RE = re.compile(
    r"mongodb(?:\+srv)?://(?:[^:@/]*:)?\*{3}@|mongodb(?:\+srv)?://\*{3}\Z", re.IGNORECASE
)
_MASKED_OPTION_RE = re.compile(r"(?:\A|[&;])[A-Za-z][A-Za-z0-9]*=\*{3}(?:[&;]|\Z)")


def mask_uri(uri: str) -> str:
    """Return ``uri`` rebuilt from its safe parts only: scheme, masked userinfo, hosts, db, options.

    Safe to log or send to the browser. Fails CLOSED: it reconstructs the URI from an allow-list
    instead of redacting known-secret spots, so odd forms cannot leak.

    * Userinfo is everything between ``://`` and the LAST ``@`` (a password may hold ``/ ? # @``);
      ``user:pw`` -> ``user:***``, a userinfo without ``:`` (a token as username) -> ``***``.
    * Option values are shown only for the keys in ``SAFE_URI_OPTIONS`` and only when they look
      plain; everything else (``authMechanismProperties``, ``tlsCertificateKeyFilePassword``,
      percent-encoded or unknown keys, ...) becomes ``key=***``.
    * No ``mongodb://`` / ``mongodb+srv://`` scheme -> ``***``. Any structural doubt -> ``mongodb://***``.
    * Never raises.
    """
    # noinspection PyBroadException
    try:
        return _mask(uri.strip())
    except Exception:  # noqa: BLE001 - this function must never raise or leak
        return MASKED_URI


def _mask_userinfo(userinfo: str) -> str:
    user, colon, _password = userinfo.partition(":")
    if colon and _USER_RE.match(user):
        return f"{user}:{MASK}@"
    return f"{MASK}@"


def _mask_query(query: str) -> str:
    items: list[str] = []
    for raw in re.split(r"[&;]", query):
        if not raw:
            continue
        key, _eq, value = raw.partition("=")
        if not _OPTION_KEY_RE.match(key):
            continue  # unreadable key: drop the whole item
        shown = key.lower() in SAFE_URI_OPTIONS and _OPTION_VALUE_RE.match(value) is not None
        items.append(f"{key}={value if shown else MASK}")
    return "&".join(items)


def _mask(uri: str) -> str:
    match = _SCHEME_RE.match(uri)
    if match is None:
        return MASK
    rest = uri[match.end() :]
    at = rest.rfind("@")
    userinfo = rest[:at] if at >= 0 else None
    authority, _, query = rest[at + 1 :].partition("?")
    hosts, slash, database = authority.partition("/")
    host_list = hosts.split(",")
    if (
        len(hosts) > _HOSTS_MAX
        or not all(_HOST_RE.match(h) for h in host_list)
        or _DB_RE.match(database) is None
    ):
        return MASKED_URI
    out = f"{match.group(1).lower()}://"
    if userinfo is not None:
        out += _mask_userinfo(userinfo)
    out += hosts + (f"/{database}" if slash else "")
    masked_query = _mask_query(query)
    return f"{out}?{masked_query}" if masked_query else out


def looks_masked(value: str) -> bool:
    """True when ``value`` looks like ``mask_uri`` output or a bare asterisk placeholder.

    Used to refuse saving a masked URI back over the real secret. Only the positions ``mask_uri``
    emits count (see ``_MASKED_USERINFO_RE``), so a real password or option value that merely
    ends in or contains ``***`` (``u:abc***@h``) is accepted. The one inherent limit: a password
    or option value that is EXACTLY ``***`` is indistinguishable from the placeholder and must
    be percent-encoded (``%2A%2A%2A``).
    """
    stripped = value.strip()
    if not stripped:
        return False
    if set(stripped) == {"*"} or _MASKED_USERINFO_RE.match(stripped) is not None:
        return True
    # the query starts after the LAST "@" (a password may hold "?" and "@"), as in ``mask_uri``
    query = stripped.rpartition("@")[2].partition("?")[2]
    return _MASKED_OPTION_RE.search(query) is not None


# --------------------------------------------------------------------------- categories

_WS_RE = re.compile(r"\s+")
#: What is left after whitespace collapsing: control characters (Cc; NUL cannot be a BSON key and
#: the rest are invisible) and lone surrogates (Cs; they cannot be encoded as UTF-8 or BSON).
_BAD_CATEGORY_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
#: Casefolded names that are reserved for the synthetic "no category" slice and the donut fold.
RESERVED_CATEGORY_KEYS = frozenset({"uncategorized", "other"})


def normalize_category(value: str) -> str:
    """NFC, trimmed, inner whitespace runs collapsed to one space. Display spelling.

    Whitespace control characters (tab, newline, ...) collapse like any other whitespace; every
    other control (Cc) character and every lone surrogate raises ``ValueError``. NFC can change
    the length (``U+0344`` becomes two characters), so callers that cap the length must check
    the RESULT.
    """
    text = _WS_RE.sub(" ", unicodedata.normalize("NFC", value)).strip()
    if _BAD_CATEGORY_CHARS_RE.search(text):
        raise ValueError("category must not contain control characters")
    return text


def category_key(value: str) -> str:
    """Identity of a category: ``Food``, ``food `` and ``FOOD`` share one key.

    Raises ``ValueError`` like ``normalize_category``.
    """
    return unicodedata.normalize("NFC", normalize_category(value).casefold())


def is_reserved_category(value: str) -> bool:
    """True for ``Uncategorized`` / ``Other`` in any spelling: those names are renderer-owned.

    Raises ``ValueError`` like ``normalize_category``.
    """
    return category_key(value) in RESERVED_CATEGORY_KEYS


#: A cell that starts with one of these (after leading blanks) can be read as a formula.
FORMULA_STARTS = ("=", "+", "-", "@")
#: Characters a spreadsheet may skip before it looks at the first real one.
LEADING_BLANKS = " \t\r\n"


def starts_like_formula(text: str) -> bool:
    """True when a spreadsheet could execute ``text`` as a formula.

    Triggers: the text starts with ``= + - @`` after leading blanks (space, TAB, CR, LF), or the
    raw text starts with a TAB or a carriage return.
    """
    return text.lstrip(LEADING_BLANKS).startswith(FORMULA_STARTS) or text.startswith(("\t", "\r"))
