# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""What the browser does with ``transform.entry_categories`` after a category reached the data.

The server never edits ``transform`` (no clobbering of concurrent edits); it only says what to do
with the stale override of the pair: ``drop`` it, or ``set`` it again because something outranks
the data (``rules_override``, a ``category_rules`` entry for a cleared category, or an
``extra_links`` row of the same pair that was not rewritten).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sankey_studio.models import SetCategory

if TYPE_CHECKING:
    from sankey_studio.edits.job import EditJob


def _pair_in_extra_links(job: EditJob, edit: SetCategory) -> bool:
    alias = job.alias
    pair = (alias.get(edit.source, edit.source), alias.get(edit.target, edit.target))
    return any(
        (alias.get(link.source, link.source), alias.get(link.target, link.target)) == pair
        for link in job.draft.transform.extra_links
    )


def override_for(job: EditJob) -> Literal["drop", "set"] | None:
    """The directive after a successful data write of ``job.edit`` (``None``: not a category)."""
    edit = job.edit
    if not isinstance(edit, SetCategory):
        return None
    transform = job.draft.transform
    outranked = (
        bool(transform.category_rules) if edit.category is None else transform.rules_override
    )
    return "set" if outranked or _pair_in_extra_links(job, edit) else "drop"
