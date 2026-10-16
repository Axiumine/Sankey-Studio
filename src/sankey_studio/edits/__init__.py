# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Edits to the data of a graph: where each one goes and, when allowed, writing it back.

``plan_edit`` and ``write_edit`` are the whole surface; the web layer calls them with the app's
``Services`` and graph cache. This package sits above ``pipeline`` and below ``web``.

* ``target``: the consent key of a source (built from resolved values) and the effective
  preference;
* ``gates``: the operator rules every file or MongoDB edit passes;
* ``draft`` / ``files`` / ``mongo``: one branch per kind of source;
* ``recolour``: the guard of the row reorder; ``override``: the directive for
  ``entry_categories``; ``reasons``: the fixed English sentences.
"""

from __future__ import annotations

from sankey_studio.edits.plan import plan_edit
from sankey_studio.edits.write import write_edit

__all__ = ["plan_edit", "write_edit"]
