"""Stable pytest ids for parametrised text that holds escapes or non-ASCII characters.

pytest escapes a string id again each time the same module is collected twice in one process
(``'a\\n'`` becomes ``'a\\\\n'``), and mutmut collects once for its statistics and selects tests by
node id in the next run: such an id is then "not found" and mutmut aborts. Ids made of printable
ASCII without a backslash survive every collection unchanged.
"""

from __future__ import annotations


def stable_id(text: str) -> str:
    """``text`` in single quotes; a backslash, control or non-ASCII character becomes ``<hex>``."""
    plain = (c if c.isascii() and c.isprintable() and c != "\\" else f"<{ord(c):x}>" for c in text)
    return "'" + "".join(plain) + "'"
