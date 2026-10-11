"""Keyboard helpers for the smoke suite (UI-A): follow the Tab order and read the focus ring.

``tab_until(page, target)`` presses Tab until the focused element is ``target`` (a test id, or the
class of an element without one such as ``skip-link`` / ``brand``) and returns every element it
passed on the way, so a test can assert the order a keyboard user meets. It fails after
``limit`` presses instead of looping.

``focus_ring(page)`` is the ``(style, width)`` of the outline of the focused element: the focus
ring contract of the app is a solid outline of 2 px or more on links, buttons and tabs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from playwright.sync_api import Page

TAB_LIMIT: Final = 90
_WHO_JS = """() => {
    const el = document.activeElement;
    if (!el || el === document.body) { return ''; }
    const text = (el.textContent || '').trim().slice(0, 40);
    const label = el.getAttribute('aria-label');
    return el.dataset.testid || el.classList[0] || label || text || el.tagName;
}"""
_RING_JS = """() => {
    const style = getComputedStyle(document.activeElement);
    return [style.outlineStyle, parseFloat(style.outlineWidth)];
}"""


def focused(page: Page) -> str:
    """Who has the focus: its test id, else its first class, else its label or tag name."""
    return str(page.evaluate(_WHO_JS))


def tab_until(page: Page, target: str, *, limit: int = TAB_LIMIT) -> list[str]:
    """Press Tab until ``target`` has the focus; return what was focused on the way (inclusive)."""
    seen: list[str] = []
    for _ in range(limit):
        page.keyboard.press("Tab")
        seen.append(focused(page))
        if seen[-1] == target:
            return seen
    raise AssertionError(f"{target!r} was not reached in {limit} Tab presses; saw {seen}")


def focus_ring(page: Page) -> tuple[str, float]:
    """The outline style and width (px) of the focused element."""
    style, width = page.evaluate(_RING_JS)
    return str(style), float(width)
