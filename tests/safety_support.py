"""Helpers shared by the ``mongo_safety`` test modules."""

from __future__ import annotations

from typing import Any

import pytest

from sankey_studio.errors import UnsafeSourceError

ACCEPTED = "<accepted>"


def outcome_of(fn: Any, *args: Any) -> str:
    """``ACCEPTED`` when ``fn(*args)`` returns, else the exact ``UnsafeSourceError`` message."""
    try:
        fn(*args)
    except UnsafeSourceError as exc:
        return exc.message
    return ACCEPTED


def message_of(fn: Any, *args: Any) -> str:
    """The exact ``UnsafeSourceError`` message ``fn(*args)`` raises."""
    with pytest.raises(UnsafeSourceError) as info:
        fn(*args)
    return info.value.message
