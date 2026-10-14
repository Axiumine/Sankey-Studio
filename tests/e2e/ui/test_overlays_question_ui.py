"""``askKeepOverlays``: the Keep / Drop / Cancel question about graph-only edits.

The inline tab strip asks it before it replaces the source (wizard wave); the change-source dialog
has its own checkbox. The module is the shared piece, so it is driven here in the real page: it is
imported from the same URL the editor uses, with a fake store that holds a few overlays.
One server for the module (nothing here saves).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from playwright.sync_api import expect

from tests.e2e.support.ui_a_editor import EditorPage

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

ASK: Final = """async (draft) => {
  const { askKeepOverlays } = await import('/static/js/editor/source/overlays.js');
  window.answer = undefined;
  askKeepOverlays({ get: () => ({ draft }) }).then((value) => { window.answer = value; });
}"""
EDITS: Final[dict[str, Any]] = {
    "transform": {"entry_categories": [{}, {}], "extra_links": [{}]},
    "style": {"node_order": ["a", "b"]},
}
NOTHING: Final[dict[str, Any]] = {"transform": {"entry_categories": []}, "style": {}}


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> None:
    EditorPage(page, live_server).goto()


def answer(page: WatchedPage) -> object:
    page.wait_for_function("window.answer !== undefined")
    return page.evaluate("window.answer")


@pytest.mark.usefixtures("editor")
def test_the_question_names_what_would_be_lost(page: WatchedPage) -> None:
    page.evaluate(ASK, EDITS)

    dialog = page.get_by_role("dialog", name="Keep your edits to this graph?")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("2 category edits, 1 added entry, a custom node order")
    expect(dialog.get_by_role("button", name="Keep them")).to_be_focused()
    dialog.get_by_role("button", name="Cancel").click()
    assert answer(page) == "cancel"


@pytest.mark.usefixtures("editor")
@pytest.mark.parametrize(
    ("button", "expected"), [("Keep them", "keep"), ("Drop them", "drop"), ("Cancel", "cancel")]
)
def test_each_button_answers_with_its_own_word(
    page: WatchedPage, button: str, expected: str
) -> None:
    page.evaluate(ASK, EDITS)

    page.get_by_role("dialog").get_by_role("button", name=button).click()

    assert answer(page) == expected
    expect(page.get_by_role("dialog")).to_have_count(0)


@pytest.mark.usefixtures("editor")
def test_escape_cancels_and_nothing_to_keep_never_asks(page: WatchedPage) -> None:
    page.evaluate(ASK, EDITS)
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    assert answer(page) == "cancel"

    page.evaluate(ASK, NOTHING)

    assert answer(page) == "keep"
    expect(page.get_by_role("dialog")).to_have_count(0)
