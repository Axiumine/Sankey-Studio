# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Exact error messages of the shared field types, ``StyleSpec`` colours and ``SankeyGraph``."""

from __future__ import annotations

from array import array
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from sankey_studio.models import (
    CATEGORY_MAX,
    AppSettings,
    DonutStyle,
    Link,
    MongoConnection,
    MongoSource,
    SankeyGraph,
    StyleSpec,
)
from sankey_studio.models.fields import NameStr, OptUserCategory, UserCategory

RESERVED = "Value error, 'Uncategorized' and 'Other' are reserved names; pick another category"
CONTROL = "Value error, category must not contain control characters"


def first_message(model: Any, **data: Any) -> str:
    with pytest.raises(ValidationError) as info:
        model(**data)
    return str(info.value.errors(include_input=False, include_url=False)[0]["msg"])


def adapter_message(adapter: Any, value: object) -> str:
    with pytest.raises(ValidationError) as info:
        adapter.validate_python(value)
    return str(info.value.errors(include_input=False, include_url=False)[0]["msg"])


# --------------------------------------------------------------------------- field types


def test_node_names_refuse_nul_with_a_plain_message() -> None:
    adapter = TypeAdapter(NameStr)
    assert adapter_message(adapter, "a\0b") == "Value error, must not contain NUL"
    assert adapter_message(adapter, "\0") == "Value error, must not contain NUL"
    assert adapter.validate_python("a b") == "a b"
    assert first_message(Link, source="x\0", target="b", value=1) == (
        "Value error, must not contain NUL"
    )
    assert first_message(Link, source="a", target="\0y", value=1) == (
        "Value error, must not contain NUL"
    )


def test_database_and_collection_names_report_the_guard_message() -> None:
    base = {"connection": "c", "collection": "events"}
    assert first_message(MongoSource, **{**base, "collection": "system.users"}) == (
        "Value error, MongoDB system collections are not allowed"
    )
    assert first_message(MongoSource, **{**base, "collection": "a$b"}) == (
        "Value error, invalid MongoDB collection name"
    )
    assert first_message(MongoSource, **{**base, "database": "admin"}) == (
        "Value error, MongoDB system databases (admin, local, config) are not allowed"
    )
    assert first_message(MongoSource, **{**base, "database": "a b"}) == (
        "Value error, invalid MongoDB database name"
    )
    assert first_message(AppSettings, storage_database="config") == (
        "Value error, MongoDB system databases (admin, local, config) are not allowed"
    )
    assert first_message(MongoConnection, name="c", uri="mongodb://h/", default_database="a.b") == (
        "Value error, invalid MongoDB database name"
    )


@pytest.mark.parametrize("adapter", [TypeAdapter(UserCategory), TypeAdapter(OptUserCategory)])
def test_user_categories_refuse_reserved_names_and_controls(adapter: Any) -> None:
    for name in ("Uncategorized", "other", " OTHER ", "UNCATEGORIZED"):
        assert adapter_message(adapter, name) == RESERVED
    assert adapter_message(adapter, "a\x00b") == CONTROL
    assert adapter_message(adapter, "a\x1bb") == CONTROL


@pytest.mark.parametrize("adapter", [TypeAdapter(UserCategory), TypeAdapter(OptUserCategory)])
def test_user_category_length_is_checked_after_normalisation(adapter: Any) -> None:
    """``U+0344`` becomes two characters under NFC, so 51 of them are 102 after cleaning."""
    expected = (
        f"Value error, category must be at most {CATEGORY_MAX} characters after normalisation"
    )
    assert adapter_message(adapter, "\u0344" * 51) == expected
    assert adapter.validate_python("\u0344" * 50) == "\u0308\u0301" * 50
    assert adapter.validate_python("x" * CATEGORY_MAX) == "x" * CATEGORY_MAX
    assert adapter_message(adapter, "x" * (CATEGORY_MAX + 1)) == (
        "String should have at most 100 characters"
    )


def test_optional_category_turns_blank_into_none() -> None:
    adapter = TypeAdapter(OptUserCategory)
    assert adapter.validate_python(None) is None
    assert adapter.validate_python("") is None
    assert adapter.validate_python("   ") is None
    assert adapter.validate_python("\t Food \n x ") == "Food x"
    assert Link(source="a", target="b", value=1, category="  ").category is None


# --------------------------------------------------------------------------- style colours


def test_bad_colour_overrides_list_at_most_five_names() -> None:
    names = [f"n{i}" for i in range(7)]
    message = first_message(StyleSpec, node_colors=dict.fromkeys(names, "red"))
    assert message == (
        "Value error, node_colors must be #rrggbb; bad entries: ['n0', 'n1', 'n2', 'n3', 'n4']"
    )
    one = first_message(StyleSpec, node_colors={"A": "#12345"})
    assert one == "Value error, node_colors must be #rrggbb; bad entries: ['A']"
    only_bad = first_message(StyleSpec, node_colors={"good": "#a1B2c3", "bad": "#GGGGGG"})
    assert only_bad == "Value error, node_colors must be #rrggbb; bad entries: ['bad']"


def test_bad_category_colours_use_their_own_label() -> None:
    message = first_message(StyleSpec, category_colors={"Food": "#fff"})
    assert message == "Value error, category_colors must be #rrggbb; bad entries: ['Food']"


@pytest.mark.parametrize("color", [None, "#a1B2c3", "#000000", "#FFFFFF"])
def test_the_one_colour_is_a_hex_colour_or_unset(color: str | None) -> None:
    assert StyleSpec(mono_color=color).mono_color == color


@pytest.mark.parametrize("color", ["#fff", "#12345", "#1234567", "#GGGGGG", "red", "", "aabbcc"])
def test_a_bad_one_colour_is_refused(color: str) -> None:
    assert first_message(StyleSpec, mono_color=color) == "Value error, mono_color must be #rrggbb"


def test_category_colour_keys_are_normalised_checked_and_unique() -> None:
    assert StyleSpec(category_colors={"  Food  x ": "#aabbcc"}).category_colors == {
        "Food x": "#aabbcc"
    }
    keys = "Value error, category_colors keys must be 1-100 characters"
    assert first_message(StyleSpec, category_colors={"": "#aabbcc"}) == keys
    assert first_message(StyleSpec, category_colors={"x" * 101: "#aabbcc"}) == keys
    StyleSpec(category_colors={"x" * 100: "#aabbcc"})
    reserved = "Value error, 'Uncategorized' and 'Other' are reserved names with fixed colours"
    assert first_message(StyleSpec, category_colors={"other": "#aabbcc"}) == reserved
    twice = "Value error, category_colors repeats a category (names compare case-insensitively)"
    assert (
        first_message(StyleSpec, category_colors={"Food": "#aabbcc", "FOOD ": "#112233"}) == twice
    )


def test_value_format_message_and_defaults() -> None:
    expected = "Value error, value_format must be a d3-format string such as ',.2~f'"
    assert first_message(StyleSpec, value_format="a;b") == expected
    assert first_message(StyleSpec, value_format="x" * 25) == expected
    assert StyleSpec().value_format == ",.2~f"
    assert DonutStyle().max_slices == 6


# --------------------------------------------------------------------------- SankeyGraph


def build(**over: Any) -> SankeyGraph:
    base: dict[str, Any] = {
        "node_names": ("a", "b", "c"),
        "node_layers": (0, 1, 2),
        "node_color_slot": (0, 1, 2),
        "node_in": (0.0, 5.0, 3.0),
        "node_out": (5.0, 3.0, 0.0),
        "link_source": array("i", [0, 1]),
        "link_target": array("i", [1, 2]),
        "link_value": array("d", [5.0, 3.0]),
        "link_category": array("i", [-1, -1]),
    }
    return SankeyGraph(**{**base, **over})


def graph_message(**over: Any) -> str:
    try:
        build(**over)
    except ValueError as exc:
        return str(exc)
    return "<accepted>"


UNIQUE = "categories must be unique (names compare case-insensitively)"
NODE_COLUMNS = "node columns must all have one entry per node"
LINK_COLUMNS = "link columns must all have one entry per link"


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"node_layers": (0, 1)}, NODE_COLUMNS),
        ({"node_color_slot": (0, 1)}, NODE_COLUMNS),
        ({"node_in": (0.0, 5.0)}, NODE_COLUMNS),
        ({"node_out": (5.0, 3.0, 0.0, 1.0)}, NODE_COLUMNS),
        ({"link_value": array("d", [5.0])}, LINK_COLUMNS),
        ({"link_source": array("i", [0])}, LINK_COLUMNS),
        ({"link_target": array("i", [1, 2, 0])}, LINK_COLUMNS),
        ({"link_category": array("i", [-1])}, LINK_COLUMNS),
        ({"categories": ("a",)}, "category_color_slot needs one entry per category"),
        ({"category_color_slot": (0,)}, "category_color_slot needs one entry per category"),
    ],
)
def test_shape_messages(over: dict[str, Any], message: str) -> None:
    assert graph_message(**over) == message


@pytest.mark.parametrize(
    ("column", "bad", "code"),
    [
        ("link_source", array("I", [0, 1]), "i"),
        ("link_target", array("l", [1, 2]), "i"),
        ("link_category", array("b", [-1, -1]), "i"),
        ("link_value", array("f", [5.0, 3.0]), "d"),
        ("link_source", [0, 1], "i"),
        ("link_value", (5.0, 3.0), "d"),
    ],
)
def test_typecode_messages_name_the_column(column: str, bad: object, code: str) -> None:
    assert graph_message(**{column: bad}) == f"{column} must be array('{code}')"


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"link_source": array("i", [0, 3])}, "link_source must index node_names"),
        ({"link_source": array("i", [-1, 1])}, "link_source must index node_names"),
        ({"link_target": array("i", [1, 3])}, "link_target must index node_names"),
        ({"link_target": array("i", [-1, 2])}, "link_target must index node_names"),
        (
            {"link_category": array("i", [-2, -1])},
            "link_category must be -1 (uncategorised) or index categories",
        ),
        (
            {"link_category": array("i", [0, -1])},
            "link_category must be -1 (uncategorised) or index categories",
        ),
    ],
)
def test_range_messages_name_the_column(over: dict[str, Any], message: str) -> None:
    assert graph_message(**over) == message


def test_index_edges_are_accepted() -> None:
    nodes = build(link_source=array("i", [0, 2]), link_target=array("i", [2, 0]))
    assert (list(nodes.link_source), list(nodes.link_target)) == ([0, 2], [2, 0])
    assert len(nodes.node_names) == 3  # 2 is the last valid node index
    cats = build(
        link_category=array("i", [-1, 1]),
        categories=("a", "b"),
        category_color_slot=(0, 1),
    )
    assert list(cats.link_category) == [-1, 1]  # -1 = uncategorised, 1 = the last category
    assert (cats.categories, cats.category_color_slot) == (("a", "b"), (0, 1))


@pytest.mark.parametrize(
    ("names", "message"),
    [
        (("",), "categories must not contain an empty name"),
        (("  ",), "categories must not contain an empty name"),
        (("Uncategorized",), "categories must not contain the reserved names Uncategorized/Other"),
        (("Food", " other"), "categories must not contain the reserved names Uncategorized/Other"),
        (("Food", "FOOD"), UNIQUE),
        (
            ("Cafe\u0301", "Caf\u00e9"),
            "categories must be unique (names compare case-insensitively)",
        ),
        (("a\x00b",), "category must not contain control characters"),
    ],
)
def test_category_messages(names: tuple[str, ...], message: str) -> None:
    assert graph_message(categories=names, category_color_slot=tuple(range(len(names)))) == message
