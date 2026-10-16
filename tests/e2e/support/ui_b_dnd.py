# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``DragLibrary``: the library page object with drag and drop (UI.md 4.2, collections).

Two ways to drag, both without a sleep:

* ``drag`` is a real mouse drag: press on the card's padding (``GRAB``, away from text and
  controls, which are not drag handles), move in steps and wait for the mark on the target.
* ``begin`` / ``over`` / ``drop`` / ``finish`` dispatch the drag events themselves, all with one
  ``DataTransfer`` handle, the way a browser shares it from ``dragstart`` to ``dragend``. They
  return what the page did (``over`` and ``drop``: was the event cancelled, i.e. accepted). A new
  ``DataTransfer`` (``foreign``) is a drag that did not start on the page.

``crumb(name)`` is a crumb of the breadcrumb (``None`` = Library); ``writes`` lists every request
that is not a GET.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from playwright.sync_api import expect

from tests.e2e.support.ui_b_folders import FolderLibrary

if TYPE_CHECKING:
    from playwright.sync_api import JSHandle, Locator, Position, Request

GRAB: Final[Position] = {"x": 6, "y": 6}
EVENT_JS: Final = """(el, [type, dt]) => {
    const event = new DragEvent(type, {dataTransfer: dt, bubbles: true, cancelable: true});
    el.dispatchEvent(event);
    return event.defaultPrevented;
}"""
PRIVATE_TYPE: Final = "application/x-sankey-studio-move"
FOREIGN_JS: Final = {
    "text": "() => { const d = new DataTransfer(); d.setData('text/plain', 'x'); return d; }",
    "file": (
        "() => { const d = new DataTransfer();"
        " d.items.add(new File(['x'], 'a.txt', {type: 'text/plain'})); return d; }"
    ),
}


class DragLibrary(FolderLibrary):
    def crumb(self, name: str | None) -> Locator:
        """The crumb of the collection ``name`` (``None`` = Library)."""
        if name is None:
            return self.page.locator("[data-testid=folder-crumb][data-folder-id=root]")
        return self.crumbs.filter(has_text=name)

    def record_writes(self) -> list[str]:
        """``"METHOD url"`` of every request that is not a GET, from now on."""
        writes: list[str] = []

        def note(request: Request) -> None:
            if request.method != "GET":
                writes.append(f"{request.method} {request.url}")

        self.page.on("request", note)
        return writes

    # ------------------------------------------------------------------ one DataTransfer

    def foreign(self, kind: str = "text") -> JSHandle:
        """A drag that did not start on the page: a fresh ``DataTransfer`` with a text or a file."""
        return self.page.evaluate_handle(FOREIGN_JS[kind])

    def fire(self, target: Locator, event: str, transfer: JSHandle) -> bool:
        """Dispatch a drag event on ``target``; ``True`` when the page cancelled it (accepted)."""
        return bool(target.evaluate(EVENT_JS, [event, transfer]))

    def begin(self, source: Locator) -> JSHandle:
        """``dragstart`` on ``source``; returns the ``DataTransfer`` of the drag.

        The pointer first leaves the page (a real drag starts with the pointer on a part of the
        card that is a handle, not on a button or a text that a click or a selection needs).
        """
        self.page.mouse.move(1, 1)
        transfer = self.page.evaluate_handle("() => new DataTransfer()")
        self.fire(source, "dragstart", transfer)
        return transfer

    def has_private_data(self, transfer: JSHandle) -> bool:
        return bool(transfer.evaluate(f"(d) => d.types.includes('{PRIVATE_TYPE}')"))

    def over(self, target: Locator, transfer: JSHandle) -> bool:
        return self.fire(target, "dragover", transfer)

    def drop(self, target: Locator, transfer: JSHandle) -> bool:
        return self.fire(target, "drop", transfer)

    def finish(self, source: Locator, transfer: JSHandle) -> None:
        self.fire(source, "dragend", transfer)

    # ------------------------------------------------------------------ the real mouse

    def drag(self, source: Locator, target: Locator, *, release: bool = True) -> None:
        """Press on ``source``, move onto ``target`` and (by default) let go there.

        With ``release=False`` the button stays down: call ``release()`` when done.
        """
        source.hover(position=GRAB)
        self.page.mouse.down()
        box = target.bounding_box()
        assert box is not None, "the drop target has no box"
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
        expect(target).to_have_attribute("data-drop", "ok")
        if release:
            self.release()

    def release(self) -> None:
        self.page.mouse.up()
