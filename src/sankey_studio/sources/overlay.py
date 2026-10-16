# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Overlay links: entries that live in the graph (``transform.extra_links``), not in the data.

They are appended AFTER the rows of the source, as raw (pre-merge) names, so ``merge_nodes``,
``hide_nodes`` and the row cap apply to them like to any other row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Sequence

    from sankey_studio.models import Link, RawLink


def with_extra_links(links: Iterable[RawLink], extras: Sequence[Link]) -> Generator[RawLink]:
    """``links`` followed by ``extras`` (an empty category counts as none, like a manual link).

    ``yield from`` forwards ``close()`` to ``links``, so closing this iterator still runs the
    cleanup of the source generator behind it.
    """
    yield from links
    for link in extras:
        yield link.source, link.target, link.value, link.category or None
