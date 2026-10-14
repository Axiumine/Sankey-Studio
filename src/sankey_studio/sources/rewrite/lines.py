"""Physical lines of a text, byte for byte.

The parsers read through universal newlines (``\\r\\n``, ``\\r`` and ``\\n`` end a line) and keep
every other character, so these helpers split on exactly those three and nothing else:
``str.splitlines`` would also split on VT, FF, NEL and U+2028, which the parsers keep.
"""

from __future__ import annotations

import re

from sankey_studio.errors import SourceEditRefused
from sankey_studio.sources.formats.lines import BOM, LINE_MAX

_PHYSICAL_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_EOL_RE = re.compile(r"\r\n|\r|\n")
DEFAULT_EOL = "\n"
#: On a tie the earlier one wins.
_EOL_ORDER = ("\n", "\r\n", "\r")


def split_physical(text: str) -> list[str]:
    """The lines of ``text`` with their line breaks; joining them gives ``text`` back."""
    return _PHYSICAL_RE.findall(text)


def peel_bom(text: str) -> tuple[str, str]:
    """``(bom, rest)``: a leading byte order mark apart from the text."""
    if text.startswith(BOM):
        return BOM, text[len(BOM) :]
    return "", text


def eol_of(line: str) -> str:
    """The line break at the end of ``line`` (empty for a last line without one)."""
    for eol in ("\r\n", "\r", "\n"):
        if line.endswith(eol):
            return eol
    return ""


def dominant_eol(text: str) -> str:
    """The most common line break of ``text`` (``\\n`` when there is none or on a tie)."""
    found = _EOL_RE.findall(text)
    if not found:
        return DEFAULT_EOL
    return max(_EOL_ORDER, key=found.count)


def without_eol(line: str) -> str:
    """``line`` without its line break."""
    return line.removesuffix(eol_of(line))


def check_line_length(chunk: str) -> None:
    """A line longer than the parsers read would be skipped: ``unsupported_format``."""
    if any(len(without_eol(line)) > LINE_MAX for line in split_physical(chunk)):
        raise SourceEditRefused("unsupported_format")
