# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The saved answer to "may edits be written back to the data source?"."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from sankey_studio.models.base import WRITE_TARGET_MAX, _Model


class WriteBackPref(_Model):
    """What the graph owner chose for one write target.

    ``target`` is the opaque key the SERVER returned for the source (``EditOutcome.target_key``);
    the client stores it verbatim. The preference only counts while it equals the key of the
    current source, so changing the file, connection, database or collection asks again. It is
    client-supplied state (UX consent), not an authorisation boundary.
    """

    mode: Literal["source", "graph"]
    target: str = Field(min_length=1, max_length=WRITE_TARGET_MAX)
