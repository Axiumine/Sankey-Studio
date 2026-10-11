"""The inertness check of the security suites must be able to fail: tested with real injections."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support import ui_b_hostile as hostile
from tests.e2e.support.ui_b_library import LibraryPage

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

INJECT_BOLD = """() => {
    const bold = document.createElement('b');
    bold.textContent = 'x';
    document.querySelector('main').append(bold);
}"""
INJECT_SCRIPT = """() => {
    const script = document.createElement('script');
    script.type = 'text/plain';
    script.textContent = 'noop';
    document.body.append(script);
}"""


@pytest.fixture
def inert(page: WatchedPage, live_server: LiveServer) -> hostile.Inert:
    LibraryPage(page, live_server).goto()
    return hostile.Inert.watch(page)


def test_a_clean_page_passes_and_injections_are_found(inert: hostile.Inert) -> None:
    inert.check()
    inert.page.evaluate(INJECT_BOLD)
    assert inert.injected() == {"main b": 1}
    with pytest.raises(AssertionError, match="injected elements"):
        inert.check()
    inert.page.evaluate("() => document.querySelector('main b').remove()")
    inert.page.evaluate(INJECT_SCRIPT)
    with pytest.raises(AssertionError, match="inline script"):
        inert.check()


def test_a_javascript_dialog_is_recorded_and_dismissed(inert: hostile.Inert) -> None:
    inert.page.evaluate("() => alert('boom')")  # returns once the recorded dialog was dismissed
    assert inert.dialogs == ["alert: boom"]
    with pytest.raises(AssertionError, match="dialogs"):
        inert.check()
