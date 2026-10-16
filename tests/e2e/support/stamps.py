# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""API timestamps as instants.

The API prints ``updated_at`` as ``2026-10-11T10:00:46Z`` when the millisecond part is zero and as
``2026-10-11T10:00:46.001Z`` otherwise. As text the first sorts AFTER the second (``Z`` > ``.``),
as an instant it sorts before: compare instants, never strings.
"""

from __future__ import annotations

from datetime import UTC, datetime


def instant(stamp: object) -> datetime:
    """The aware UTC datetime of an API timestamp (asserts the ``Z`` suffix the API promises)."""
    text = str(stamp)
    assert text.endswith("Z"), f"not a UTC timestamp: {text!r}"
    return datetime.fromisoformat(text).astimezone(UTC)
