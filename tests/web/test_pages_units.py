# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The value types, the template environment and the health model of ``routers/pages.py``.

The dataclasses are immutable values without a ``__dict__``, ``PageView`` defaults to the common
navigation and an empty data dict of its own, the Jinja environment escapes EVERY template
whatever its extension, and ``HealthOut`` says ``ok`` and nothing else.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, Final

import pytest
from jinja2 import DictLoader, TemplateNotFound
from pydantic import ValidationError

from sankey_studio.web.routers import pages

NAV: Final = [("/", "Library"), ("/graphs/new", "New graph"), ("/settings", "Settings")]
MARKUP: Final = "<b>&\"'"
ESCAPED: Final = "&lt;b&gt;&amp;&#34;&#39;"


def assign(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


def test_the_navigation_is_library_new_graph_and_settings_in_that_order() -> None:
    assert [(link.href, link.label) for link in pages.NAV] == NAV
    assert isinstance(pages.NAV, tuple)
    assert pages.PageLink("/a", "A") == pages.PageLink("/a", "A")
    assert pages.PageLink("/a", "A") != pages.PageLink("/a", "B")


def test_a_page_link_is_an_immutable_value_without_a_dict() -> None:
    link = pages.PageLink("/a", "A")
    with pytest.raises(FrozenInstanceError):
        assign(link, "href", "/b")
    with pytest.raises(FrozenInstanceError):
        assign(link, "label", "B")
    assert (link.href, link.label) == ("/a", "A")
    assert not hasattr(link, "__dict__")


def test_a_page_view_is_an_immutable_value_without_a_dict() -> None:
    view = pages.PageView("settings", "Settings")
    for name in ("name", "heading", "links", "data"):
        with pytest.raises(FrozenInstanceError):
            assign(view, name, None)
    assert (view.name, view.heading) == ("settings", "Settings")
    assert not hasattr(view, "__dict__")


def test_a_page_view_defaults_to_the_navigation_and_its_own_empty_data() -> None:
    first = pages.PageView("settings", "Settings")
    second = pages.PageView("settings", "Settings")
    assert first.links == pages.NAV
    assert first.links is pages.NAV
    assert first.data == {}
    assert first.data is not second.data


def test_a_page_view_keeps_the_links_and_data_it_is_given() -> None:
    links = (pages.PageLink("/x", "X"),)
    data: dict[str, Any] = {"k": 1}
    view = pages.PageView("library", "Graphs", links, data)
    assert view.links == links
    assert view.data == {"k": 1}


def test_the_template_environment_lives_in_the_templates_dir() -> None:
    assert pages.TEMPLATES_DIR.is_dir()
    assert pages.TEMPLATES_DIR.name == "templates"
    assert pages.TEMPLATES_DIR.parent.name == "web"
    assert pages.PAGE_TEMPLATE == "page.html"
    assert (pages.TEMPLATES_DIR / pages.PAGE_TEMPLATE).is_file()
    assert (pages.TEMPLATES_DIR / "base.html").is_file()
    assert pages.TEMPLATES.env.get_template(pages.PAGE_TEMPLATE).name == "page.html"
    with pytest.raises(TemplateNotFound):
        pages.TEMPLATES.env.get_template("missing.html")


@pytest.mark.parametrize("name", ["page.html", "page.txt", "page", "page.xml"])
def test_every_template_is_escaped_whatever_its_name(name: str) -> None:
    env = pages.TEMPLATES.env.overlay(loader=DictLoader({name: "{{ value }}"}))
    assert env.autoescape is True
    assert env.get_template(name).render(value=MARKUP) == ESCAPED


def test_a_template_from_a_string_is_escaped_too() -> None:
    template = pages.TEMPLATES.env.from_string("{{ value }}")
    assert template.render(value=MARKUP) == ESCAPED


@pytest.mark.parametrize("raw", [5, None, 1.5, b"abc", {"a": "b"}])
def test_a_compare_query_that_is_not_a_list_or_a_string_reaches_pydantic_unchanged(
    raw: object,
) -> None:
    with pytest.raises(ValidationError) as caught:
        pages.ComparePageQuery.model_validate({"ids": raw})
    assert [error["type"] for error in caught.value.errors()] == ["list_type"]


def test_the_health_model_only_ever_says_ok() -> None:
    assert pages.HealthOut().status == "ok"
    assert pages.HealthOut.model_validate({"status": "ok"}).status == "ok"
    with pytest.raises(ValidationError):
        pages.HealthOut.model_validate({"status": "up"})
    with pytest.raises(ValidationError):
        pages.HealthOut.model_validate({"status": "OK"})


def test_the_health_model_refuses_extra_fields() -> None:
    with pytest.raises(ValidationError):
        pages.HealthOut.model_validate({"status": "ok", "extra": 1})
    schema = pages.HealthOut.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["status"]["const"] == "ok"
    assert schema["properties"]["status"]["default"] == "ok"


BIDI_CONTROLS: Final = [*range(0x202A, 0x202F), *range(0x2066, 0x206A)]
BIDI_NEIGHBOURS: Final = [0x2029, 0x202F, 0x2065, 0x206A, 0x200E, 0x200F]


@pytest.mark.parametrize("code", BIDI_CONTROLS, ids=[f"U+{code:04X}" for code in BIDI_CONTROLS])
def test_every_bidi_embedding_override_and_isolate_is_removed(code: int) -> None:
    assert pages._plain(f"a{chr(code)}b") == "ab"


@pytest.mark.parametrize("code", BIDI_NEIGHBOURS, ids=[f"U+{code:04X}" for code in BIDI_NEIGHBOURS])
def test_the_characters_next_to_the_bidi_ranges_are_kept(code: int) -> None:
    text = f"a{chr(code)}b"
    assert pages._plain(text) == text


#: NUL..BS, VT, FF, SO..US, DEL and the C1 block: no glyph, shown as empty boxes.
CONTROL_CHARACTERS: Final = [
    *range(0x09),
    *range(0x0B, 0x0D),
    *range(0x0E, 0x20),
    *range(0x7F, 0xA0),
]
#: White space the page collapses anyway (TAB, LF, CR), and the neighbours of the removed ranges.
CONTROL_NEIGHBOURS: Final = [0x09, 0x0A, 0x0D, 0x20, 0x7E, 0xA0, 0xA1, 0xAD, 0x200B]


@pytest.mark.parametrize(
    "code", CONTROL_CHARACTERS, ids=[f"U+{code:04X}" for code in CONTROL_CHARACTERS]
)
def test_every_control_character_is_removed(code: int) -> None:
    assert pages._plain(f"a{chr(code)}b") == "ab"


@pytest.mark.parametrize(
    "code", CONTROL_NEIGHBOURS, ids=[f"U+{code:04X}" for code in CONTROL_NEIGHBOURS]
)
def test_the_white_space_and_format_characters_next_to_the_control_ranges_are_kept(
    code: int,
) -> None:
    text = f"a{chr(code)}b"
    assert pages._plain(text) == text
