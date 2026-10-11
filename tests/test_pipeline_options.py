"""``BundleOptions``: an immutable value without an instance dictionary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sankey_studio.pipeline import BundleOptions


def test_options_are_frozen() -> None:
    options = BundleOptions("light")
    with pytest.raises(FrozenInstanceError):
        options.theme = "dark"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        options.max_drawn_links = 5  # type: ignore[misc]
    assert options.theme == "light"
    assert options.max_drawn_links is None


def test_options_have_slots_and_value_equality() -> None:
    assert not hasattr(BundleOptions("light"), "__dict__")
    assert BundleOptions("light") == BundleOptions("light")
    assert BundleOptions("light") != BundleOptions("dark")
    assert BundleOptions("light", entries_limit=5) != BundleOptions("light")
