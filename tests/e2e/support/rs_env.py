# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Where the replica-set suite finds its URI: the process environment, else the repo-root ``.env``.

Only ``SANKEY_TEST_MONGO_RS_URI`` is ever taken from ``.env``: the file also holds the Qodana token,
and no test may see it. The value goes to the caller and nowhere else: it is not logged, not printed
and not copied into ``os.environ``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Final

from tests.conftest import REAL_MONGO_RS_ENV

if TYPE_CHECKING:
    from collections.abc import Mapping

#: ``tests/e2e/support/rs_env.py`` -> the repository root
ENV_FILE: Final = Path(__file__).resolve().parents[3] / ".env"
QUOTES: Final = "'\""


def _unquote(value: str) -> str:
    """``"x"`` and ``'x'`` -> ``x`` (a comment after the closing quote is ignored); an unquoted
    value ends at a `` #`` comment."""
    if value and value[0] in QUOTES:
        closing = value.find(value[0], 1)
        if closing > 0:
            return value[1:closing]
    return value.split(" #", 1)[0].strip()


def value_from_env_file(path: Path, key: str) -> str | None:
    """The value of ``key`` in a dotenv file (the last assignment wins), or ``None`` when the file
    is missing, unreadable or does not assign ``key`` a non-empty value."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None
    found: str | None = None
    for raw in text.splitlines():
        name, sep, value = raw.strip().removeprefix("export ").partition("=")
        if sep and name.strip() == key:
            found = _unquote(value.strip())
    return found or None


def rs_uri(env: Mapping[str, str] | None = None, path: Path = ENV_FILE) -> str | None:
    """The replica-set URI: ``env`` (default ``os.environ``) first, then the dotenv file."""
    source = os.environ if env is None else env
    return source.get(REAL_MONGO_RS_ENV) or value_from_env_file(path, REAL_MONGO_RS_ENV)
