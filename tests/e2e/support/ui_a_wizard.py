"""Page object of the new-graph wizard (``/graphs/new`` before the editor starts).

The wizard is a two-step inline card: step 1 "details" (name, description, tags), step 2 "source"
(the source tabs, "Do it later" for an empty Paste or Manual, then the finish button). It is
the first thing ``/graphs/new`` shows; ``#page-root[data-ready=true]`` appears only when it is done.

Dual mode (the helpers are written for the page with the wizard and for the page without it):

* ``wait_wizard_or_editor(page)`` waits until ``new-wizard`` OR the mounted editor is on the page,
  so the one-time probe below is made when the page has decided which of the two it shows.
* ``NewGraphWizard.present()`` is that probe (``new-wizard`` count). ``complete_if_shown`` and
  ``finish_wizard`` do nothing when it is false, so callers need no ``if``.

``WizardInput`` says what to type: ``text`` is the pasted data (``None`` takes "Do it later", which
leaves the source empty, like the editor of a page without a wizard).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

    from tests.e2e.support.ui_a_sources import Tab

WizardStep = Literal["details", "source"]
#: Kinds whose empty source is a valid graph, so "Do it later" is offered for them.
SKIPPABLE: Final = ("paste", "manual")
EDITOR_OR_WIZARD: Final = "[data-testid=new-wizard], #page-root[data-ready=true]"


@dataclass(frozen=True, slots=True)
class WizardInput:
    """What a test types into the wizard; ``text`` is pasted data for the Paste tab."""

    name: str
    description: str = ""
    tags: tuple[str, ...] = ()
    kind: Tab = "paste"
    text: str | None = None


def wait_wizard_or_editor(page: Page) -> None:
    """The new-graph page shows the wizard, or (no wizard, or already finished) the editor."""
    page.locator(EDITOR_OR_WIZARD).first.wait_for()


class NewGraphWizard:
    """The wizard card; every method is one user action (``complete`` is the whole path)."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def tid(self, testid: str) -> Locator:
        return self.page.get_by_test_id(testid)

    @property
    def root(self) -> Locator:
        return self.tid("new-wizard")

    def present(self) -> bool:
        """The wizard is on the page now (call it after ``wait_wizard_or_editor``)."""
        return self.root.count() > 0

    # ------------------------------------------------------------------ checks

    def expect_showing(self) -> None:
        """The wizard is visible and on its first step."""
        expect(self.root).to_be_visible()
        self.expect_step("details")

    def expect_step(self, step: WizardStep) -> None:
        expect(self.root).to_have_attribute("data-step", step)

    def expect_gone(self) -> None:
        expect(self.root).to_have_count(0)

    # ------------------------------------------------------------------ actions

    def fill_details(self, name: str, description: str = "", tags: tuple[str, ...] = ()) -> None:
        """Step 1: the same fields as the details dialog (``editor-name|description|tags``)."""
        self.tid("editor-name").fill(name)
        if description:
            self.tid("editor-description").fill(description)
        for tag in tags:
            self.tid("editor-tags").fill(tag)
            self.tid("editor-tags").press("Enter")

    def next(self) -> None:
        """Click Next; an empty name keeps the wizard on step 1, so the caller checks the step."""
        self.tid("wizard-next").click()

    def back(self) -> None:
        self.tid("wizard-back").click()

    def create(self) -> None:
        """The finish button of step 2 (enabled once the source has data)."""
        self.tid("wizard-create").click()

    def later(self) -> None:
        """Click Do it later: an empty Paste or Manual source."""
        self.tid("wizard-later").click()

    def choose_kind(self, kind: Tab) -> None:
        tab = self.tid(f"source-tab-{kind}")
        tab.click()
        expect(tab).to_have_attribute("aria-selected", "true")

    def complete(self, data: WizardInput) -> None:
        """Details, Next, the source (pasted ``text`` or "Do it later"), finish; wait until gone."""
        if data.text is None and data.kind not in SKIPPABLE:
            raise ValueError(f"the {data.kind} tab needs a choice: drive the wizard step by step")
        if data.text is not None and data.kind != "paste":
            raise ValueError("text can only be pasted on the Paste tab")
        self.expect_showing()
        self.fill_details(data.name, data.description, data.tags)
        self.next()
        self.expect_step("source")
        self.choose_kind(data.kind)
        if data.text is None:
            self.later()
        else:
            self.tid("source-content").fill(data.text)
            self.create()
        self.expect_gone()

    def complete_if_shown(self, data: WizardInput) -> None:
        """``complete`` when the page shows the wizard; nothing on a page without one."""
        wait_wizard_or_editor(self.page)
        if self.present():
            self.complete(data)


def finish_wizard(page: Page) -> str | None:
    """Finish the wizard with a unique name and no data; the name, or ``None`` without a wizard."""
    wizard = NewGraphWizard(page)
    wait_wizard_or_editor(page)
    if not wizard.present():
        return None
    name = unique_name("E2E graph")
    wizard.complete(WizardInput(name=name))
    return name
