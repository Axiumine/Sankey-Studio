"""Thousands separators: the first group holds one to three digits, never four."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.sources.formats.values import parse_value


class Group(NamedTuple):
    text: str
    expected: float | None


GROUPS = [
    Group("1,234,567", 1234567.0),
    Group("12,345,678", 12345678.0),
    Group("123,456,789", 123456789.0),
    Group("1,234.5", 1234.5),
    Group("123,456.5", 123456.5),
    Group("1234,567,890", None),
    Group("1234,567.5", None),
    Group("12345,678,901", None),
]


@pytest.mark.parametrize("case", GROUPS, ids=[c.text for c in GROUPS])
def test_the_first_thousands_group_has_at_most_three_digits(case: Group) -> None:
    assert parse_value(case.text) == case.expected
