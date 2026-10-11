"""``escape_label``, ``truncate_label`` and ``value_text``: user text never becomes markup."""

from __future__ import annotations

import pytest

from sankey_studio.models import StyleSpec
from sankey_studio.render.text import (
    ELLIPSIS,
    LABEL_MAX,
    escape_label,
    strip_unseen,
    truncate_label,
    value_text,
)

PAYLOADS = [
    ("plain", "plain"),
    (
        'R&D <a href="https://evil.example">pay</a>',
        'R&amp;D &lt;a href="https://evil.example"&gt;pay&lt;/a&gt;',
    ),
    ("a<b>bold</b>", "a&lt;b&gt;bold&lt;/b&gt;"),
    ("&lt;", "&amp;lt;"),
    ("x<y", "x&lt;y"),
    ("%{value}", "%{value}"),
    ("</script><script>alert(1)</script>", "&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;"),
    ("&&", "&amp;&amp;"),
    ("", ""),
    ("é 中", "é 中"),
]


@pytest.mark.parametrize(("raw", "escaped"), PAYLOADS)
def test_escape_label_payloads(raw: str, escaped: str) -> None:
    assert escape_label(raw) == escaped


@pytest.mark.parametrize("raw", [payload for payload, _ in PAYLOADS])
def test_an_escaped_label_has_no_markup_left(raw: str) -> None:
    escaped = escape_label(raw)
    assert "<" not in escaped
    assert ">" not in escaped


def test_label_limit_is_32_characters() -> None:
    assert LABEL_MAX == 32
    assert ELLIPSIS == "…"


@pytest.mark.parametrize(
    ("length", "shown"), [(0, 0), (1, 1), (31, 31), (32, 32), (33, 33), (34, 33), (500, 33)]
)
def test_truncation_keeps_32_characters_then_an_ellipsis(length: int, shown: int) -> None:
    text = "x" * length
    out = truncate_label(text)
    assert len(out) == shown
    assert out == (text if length <= 32 else "x" * 32 + "…")


def test_truncation_limit_can_be_changed() -> None:
    assert truncate_label("abcdef", 3) == "abc…"
    assert truncate_label("abc", 3) == "abc"


@pytest.mark.parametrize(
    ("value", "fmt", "suffix", "expected"),
    [
        (1234.5, ",.2~f", "", "1,234.5"),
        (1234.5, ",.2~f", "%", "1,234.5%"),
        (1234.5, ",.2~f", "USD", "1,234.5 USD"),
        (1234.5, ",.2~f", "$", "1,234.5$"),
        (1234.5, ",.2~f", "2x", "1,234.5 2x"),
        (5.0, ",.2~f", "<b>", "5&lt;b&gt;"),
        (5.0, ",.2~f", "R&D", "5 R&amp;D"),
    ],
)
def test_value_text_appends_the_escaped_suffix(
    value: float, fmt: str, suffix: str, expected: str
) -> None:
    style = StyleSpec(value_format=fmt, value_suffix=suffix)
    assert value_text(value, style) == expected


#: What ``escape_label`` removes: C0 (TAB, LF, CR too), DEL, C1, bidi overrides and isolates.
UNSEEN = [*range(0x20), *range(0x7F, 0xA0), *range(0x202A, 0x202F), *range(0x2066, 0x206A)]
#: Their neighbours and the harmless format characters that real text uses: all kept.
SEEN = [0x20, 0x7E, 0xA0, 0xA1, 0xAD, 0x200B, 0x200E, 0x200F, 0x2029, 0x202F, 0x2065, 0x206A]


@pytest.mark.parametrize("code", UNSEEN, ids=[f"U+{code:04X}" for code in UNSEEN])
def test_every_unseen_character_is_removed(code: int) -> None:
    assert strip_unseen(f"a{chr(code)}b") == "ab"
    assert escape_label(f"a{chr(code)}<b>") == "a&lt;b&gt;"


@pytest.mark.parametrize("code", SEEN, ids=[f"U+{code:04X}" for code in SEEN])
def test_the_neighbours_of_the_removed_ranges_are_kept(code: int) -> None:
    text = f"a{chr(code)}b"
    assert strip_unseen(text) == text
    assert escape_label(text) == text


def test_the_markup_example_is_drawn_as_literal_text() -> None:
    raw = "<a href=javascript:1>x</a><b>y</b><br>"
    assert (
        escape_label(raw) == "&lt;a href=javascript:1&gt;x&lt;/a&gt;&lt;b&gt;y&lt;/b&gt;&lt;br&gt;"
    )


def test_quotes_are_left_alone_because_plotly_does_not_decode_their_entities() -> None:
    assert escape_label("""say "hi" it's""") == """say "hi" it's"""


def test_unseen_characters_do_not_hide_markup_from_the_escape() -> None:
    assert escape_label("<\x07b\u202e>") == "&lt;b&gt;"
    assert escape_label("&\x00amp;") == "&amp;amp;"


def test_clean_text_comes_back_as_the_same_object() -> None:
    """No copy per label: the 20 000-link memory budget of ``build_figure`` depends on it."""
    text = f"Salary {2026} éü☃"
    assert strip_unseen(text) is text
    assert escape_label(text) is text
