"""Two regressions found in the last real-browser pass, pinned in the shipped files.

* ``html { padding-bottom: var(--toast-clearance) }`` must not transition: with reduced motion the
  global ``transition-duration: 0.01ms`` still starts a transition, the padding then arrives one
  frame late and the scroll ``core/toast.js`` does right after setting it stops short, leaving the
  stack on top of the focused control.
* The editor heading of a graph whose name is empty once control characters are gone reads
  ``Edit Untitled graph``, like the server-rendered one (``library/names.js`` ``displayName``).
"""

from __future__ import annotations

import re
from typing import Final

from sankey_studio.web.app import STATIC_DIR

CSS: Final = STATIC_DIR / "css" / "components.css"
EDITOR: Final = STATIC_DIR / "js" / "pages" / "editor.js"


def test_the_toast_clearance_padding_of_the_page_never_transitions() -> None:
    rules = re.findall(r"html\s*\{[^}]*--toast-clearance[^}]*\}", CSS.read_text(encoding="utf-8"))
    assert len(rules) == 1
    assert re.search(r"transition-property:\s*none", rules[0])


def test_the_editor_heading_uses_the_untitled_fallback() -> None:
    source = EDITOR.read_text(encoding="utf-8")
    assert 'import { displayName } from "../library/names.js";' in source
    assert "`Edit ${displayName(name)}`" in source
