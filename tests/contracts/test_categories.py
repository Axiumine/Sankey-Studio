# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests: category normalisation, reserved names, colour overrides and the donut."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sankey_studio.models import (
    CATEGORY_MAX,
    CategoryRule,
    DonutStyle,
    EntryCategory,
    Link,
    StyleSpec,
    TransformSpec,
)


def test_link_category_is_optional_and_normalised() -> None:
    assert Link(source="a", target="b", value=1).category is None
    assert Link(source="a", target="b", value=1, category=None).category is None
    assert Link(source="a", target="b", value=1, category="   ").category is None
    assert Link(source="a", target="b", value=1, category="  Fast \t Food ").category == "Fast Food"
    assert Link(source="a", target="b", value=1, category="Café").category == "Café"
    with pytest.raises(ValidationError):
        Link(source="a", target="b", value=1, category="x" * (CATEGORY_MAX + 1))


@pytest.mark.parametrize(
    "name", ["Uncategorized", "uncategorized", " UNCATEGORIZED ", "Other", "oTHER"]
)
def test_reserved_category_names_are_rejected_in_user_specs(name: str) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        Link(source="a", target="b", value=1, category=name)
    with pytest.raises(ValidationError, match="reserved"):
        EntryCategory(source="a", target="b", category=name)
    with pytest.raises(ValidationError, match="reserved"):
        CategoryRule(pattern="*", category=name)
    with pytest.raises(ValidationError, match="reserved"):
        StyleSpec(category_colors={name: "#aabbcc"})


# (pydantic itself already refuses a lone surrogate: "unable to parse raw data as a unicode string")
@pytest.mark.parametrize("bad", ["a\0b", "\0", "a\x01", "a\x1bb", "a\x7f", "a\x9fb"])
def test_control_characters_are_rejected_in_every_user_category(bad: str) -> None:
    """NUL as a BSON key breaks the Mongo store; the other controls are invisible garbage."""
    with pytest.raises(ValidationError, match="control"):
        Link(source="a", target="b", value=1, category=bad)
    with pytest.raises(ValidationError, match="control"):
        EntryCategory(source="a", target="b", category=bad)
    with pytest.raises(ValidationError, match="control"):
        CategoryRule(pattern="*", category=bad)
    with pytest.raises(ValidationError, match="control"):
        StyleSpec(category_colors={bad: "#aabbcc"})


def test_whitespace_controls_collapse_in_user_categories() -> None:
    assert Link(source="a", target="b", value=1, category="Fast\tFood\n").category == "Fast Food"


def test_category_length_is_checked_after_normalisation() -> None:
    """``U+0344`` becomes two characters under NFC: 100 of them pass ``max_length`` but are 200."""
    sneaky = "\u0344" * (CATEGORY_MAX // 2 + 1)
    assert len(sneaky) <= CATEGORY_MAX
    with pytest.raises(ValidationError, match="after normalisation"):
        Link(source="a", target="b", value=1, category=sneaky)
    with pytest.raises(ValidationError, match="after normalisation"):
        EntryCategory(source="a", target="b", category=sneaky)
    with pytest.raises(ValidationError, match="after normalisation"):
        CategoryRule(pattern="*", category=sneaky)
    with pytest.raises(ValidationError, match="characters"):
        StyleSpec(category_colors={sneaky: "#aabbcc"})
    exactly = "\u0344" * (CATEGORY_MAX // 2)
    assert (
        len(Link(source="a", target="b", value=1, category=exactly).category or "") == CATEGORY_MAX
    )


def test_category_rule_pattern_rejects_nul() -> None:
    with pytest.raises(ValidationError, match="NUL"):
        CategoryRule(pattern="a\0", category="x")
    assert CategoryRule(pattern="a*[?]", category="x").pattern == "a*[?]"


def test_similar_but_not_reserved_names_are_fine() -> None:
    for name in ("Others", "Other stuff", "Un categorized", "Misc"):
        assert Link(source="a", target="b", value=1, category=name).category == name


def test_entry_category_none_means_force_uncategorised_and_is_explicit() -> None:
    assert EntryCategory(source="a", target="b", category=None).category is None
    assert EntryCategory(source="a", target="b", category="").category is None
    assert EntryCategory(source="a", target="b", category="Food ").category == "Food"
    with pytest.raises(ValidationError):  # omitting the key is not a "clear"
        EntryCategory.model_validate({"source": "a", "target": "b"})


def test_category_rule_requires_a_real_category() -> None:
    with pytest.raises(ValidationError):
        CategoryRule(pattern="*", category="")
    with pytest.raises(ValidationError):
        CategoryRule(pattern="*", category=None)  # type: ignore[arg-type]


def test_entry_categories_must_not_repeat_a_pair() -> None:
    pair = {"source": "a", "target": "b"}
    ok = TransformSpec.model_validate(
        {
            "entry_categories": [
                {**pair, "category": "x"},
                {"source": "b", "target": "a", "category": None},
            ]
        }
    )
    assert len(ok.entry_categories) == 2
    with pytest.raises(ValidationError, match="repeat"):
        TransformSpec.model_validate(
            {"entry_categories": [{**pair, "category": "x"}, {**pair, "category": "y"}]}
        )


def test_category_colors_are_separate_from_node_colors() -> None:
    style = StyleSpec(node_colors={"Housing": "#112233"}, category_colors={"Housing": "#445566"})
    assert style.node_colors == {"Housing": "#112233"}
    assert style.category_colors == {"Housing": "#445566"}
    with pytest.raises(ValidationError, match="repeats"):
        StyleSpec(category_colors={"Food": "#112233", "food ": "#445566"})
    with pytest.raises(ValidationError):
        StyleSpec(category_colors={"Food": "red"})
    assert StyleSpec(category_colors={"  Fast   Food ": "#112233"}).category_colors == {
        "Fast Food": "#112233"
    }


def test_color_override_dicts_are_bounded() -> None:
    too_many = {f"n{i}": "#aabbcc" for i in range(1001)}
    with pytest.raises(ValidationError):
        StyleSpec(node_colors=too_many)
    with pytest.raises(ValidationError):
        StyleSpec(category_colors=too_many)
    with pytest.raises(ValidationError):
        StyleSpec(node_colors={"n" * 201: "#aabbcc"})


def test_donut_defaults_keep_to_six_slices_and_cap_at_eight() -> None:
    assert DonutStyle().max_slices == 6
    assert DonutStyle(max_slices=8).max_slices == 8
    with pytest.raises(ValidationError):
        DonutStyle(max_slices=9)
