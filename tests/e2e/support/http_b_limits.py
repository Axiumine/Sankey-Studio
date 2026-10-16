# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers of the limits suites (E2E.md A.9): live settings and bundle readers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from tests.e2e.support.clients import json_of

if TYPE_CHECKING:
    import httpx

API: Final = "/api/v1"
NODE_COLUMNS: Final = ("source", "target", "value")


def change_settings(api: httpx.Client, **changes: Any) -> httpx.Response:
    """Read the settings, apply ``changes`` and ``PUT`` the whole document (a ``PUT`` replaces)."""
    settings = dict(json_of(api.get(f"{API}/settings")))
    settings.pop("bootstrap")
    return api.put(f"{API}/settings", json={**settings, **changes})


def drawn_values(bundle: dict[str, Any]) -> list[float]:
    """The values of the links the Sankey figure of ``bundle`` really draws."""
    return list(bundle["figure"]["data"][0]["link"]["value"])


def note_texts(bundle: dict[str, Any]) -> list[str]:
    """The texts of the annotations in the figure (the "Showing N of M links" note is one)."""
    return [annotation["text"] for annotation in bundle["figure"]["layout"]["annotations"]]
