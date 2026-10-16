// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Where a card may be grabbed: keeps the controls and the text of a draggable card usable.
 *
 * A card with `draggable="true"` turns every mouse press that moves a few pixels into a card drag.
 * That would swallow a click that wobbles on the compare checkbox or a button, and it would stop
 * the mouse from selecting the description, the tags or the meta line. So `watchGrips(root, cards)`
 * flips the attribute of the card under the pointer with one delegated `pointerover` listener:
 * `draggable="false"` while the pointer is over a control (button, input, label, select) or a block
 * of text (`.graph-card-desc`, `.graph-card-meta`, `.tag-list`), `draggable="true"` everywhere else
 * (the card padding, the head, the title link, the icon). The previous card is restored as soon as
 * the pointer reaches another element or leaves the page root. Cards that were rendered without the attribute (read-only
 * server, search results, no collection yet) are never touched.
 *
 * The attribute has to be right BEFORE the press: cancelling a `dragstart` afterwards does not give
 * the click or the text selection back.
 */

const CONTROLS = "button, input, select, textarea, label";
const TEXTS = ".graph-card-desc, .graph-card-meta, .tag-list";

function elementOf(node) {
  return node instanceof Element ? node : (node?.parentElement ?? null);
}

function setGrip(card, grabbable) {
  if (card?.isConnected && card.hasAttribute("draggable")) {
    card.setAttribute("draggable", grabbable ? "true" : "false");
  }
}

/**
 * @param {HTMLElement} root  the page root the cards live in
 * @param {string} cards  CSS selector of the draggable cards
 */
export function watchGrips(root, cards) {
  let hovered = null;
  root.addEventListener("pointerover", (event) => {
    const el = elementOf(event.target);
    const card = el?.closest(cards) ?? null;
    if (hovered !== null && hovered !== card) {
      setGrip(hovered, true);
    }
    hovered = card;
    const inner = card === null ? null : el.closest(`${CONTROLS}, ${TEXTS}`);
    setGrip(card, inner === null || !card.contains(inner));
  });
  root.addEventListener("pointerleave", () => {
    setGrip(hovered, true); // the pointer left the page root altogether
    hovered = null;
  });
}
