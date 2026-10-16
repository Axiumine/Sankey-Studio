# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers shared by the tests that pin exact pydantic validation messages."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError


def all_messages(model: Any, **data: Any) -> list[str]:
    """Every ``msg`` of the ``ValidationError`` ``model(**data)`` raises, in report order."""
    with pytest.raises(ValidationError) as info:
        model(**data)
    return [str(e["msg"]) for e in info.value.errors(include_input=False, include_url=False)]


def one_message(model: Any, **data: Any) -> str:
    """The single ``msg`` ``model(**data)`` reports (fails when there are several)."""
    messages = all_messages(model, **data)
    assert len(messages) == 1, messages
    return messages[0]
