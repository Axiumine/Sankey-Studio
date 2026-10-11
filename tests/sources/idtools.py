"""Test ids that survive pytest's id escaping unchanged.

pytest escapes backslashes and non-ASCII characters in an explicit ``ids=`` list, and mutmut
(which runs pytest several times in one process) then sees different node ids on every run, so
it cannot find the tests it recorded. Ids built here are fixed points of that escaping.
"""

from __future__ import annotations


def safe_id(text: str) -> str:
    """``text`` with every backslash and non-printable or non-ASCII character made visible.

    A backslash becomes ``/``, any other character that pytest would escape becomes ``<hex>``.
    """
    return "".join(_safe_char(char) for char in text)


def _safe_char(char: str) -> str:
    if char == "\\":
        return "/"
    if char.isascii() and char.isprintable():
        return char
    return f"<{ord(char):x}>"
