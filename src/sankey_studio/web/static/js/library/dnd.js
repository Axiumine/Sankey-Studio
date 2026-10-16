// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Drag and drop on the library page: a second, pointer way to do the two moves the Move dialog does
 * (graphs into a collection, a collection into another one). The Move buttons stay the way without a
 * mouse (keyboard, screen reader, touch); there is no dragging in search results.
 *
 * Drag sources are the cards that carry `draggable="true"` (card.js, folder-cards.js: only while
 * writes are allowed and the list follows the open collection); a `dragstart` inside any other card
 * is left to the browser (a link dragged to the bookmarks bar keeps its address). dnd-grip.js turns
 * the attribute off while the pointer is over a control or a block of text. A graph card that is picked
 * (compare checkbox) carries every picked graph in selection order, an unpicked one only itself. A
 * collection card carries its collection.
 *
 * Drop targets are the collection cards (`folder-card`) and the crumbs of the path (`folder-crumb`,
 * `data-folder-id="root"` for Library). The last crumb is the open collection and always refuses.
 *
 * Marks, all removed when the drag ends:
 *   - `data-dragging="true"`  on the card(s) being carried (set one frame after the drag starts, a
 *                             change made inside `dragstart` would cancel the drag in Chromium)
 *   - `data-drop="ok"`        on the target under the pointer when the thing can go there
 *   - `data-drop="denied"`    on a target that refuses; `data-drop-reason` holds the sentence of the
 *                             Move dialog ("already here", "inside the collection being moved", ...); it is
 *                             also announced once, "Not possible: <reason>", when the pointer enters the target
 *
 * Event flow: a few listeners on the page root (`dragstart`, `dragenter`, `dragover`, `dragleave`,
 * `drop`, `dragend`) so redraws never lose them. `dragover` cannot read `dataTransfer` data, so what
 * is dragged lives here (`drag = {kind, items, picked, local, zone}`); a drag counts as ours only when this
 * state exists AND the event carries the private type below. Anything else (a file, text, a link
 * from another page or tab) is ignored completely: no marks, no `preventDefault`, no request. A
 * valid target gets `preventDefault` and `dropEffect = "move"`; a refusing one neither, so the
 * browser shows the no-drop cursor.
 *
 * `createDnd({root, selection, host})` wires it up. `host` is the page's side (dnd-moves.js):
 *   - `allowed()`              may a drag start now (writes, scoped list, the collection exists)
 *   - `busy`                   a move request is running: no new drag starts
 *   - `reason(drag, target)`   why `target` (`null` = the library) cannot take the drag, or `null`
 *   - `drop(drag, target)`     does the move (a promise; it reports its own failures)
 */

import { announce } from "../core/a11y.js";
import { watchGrips } from "./dnd-grip.js";

/** The private type that marks a drag as ours. */
export const PRIVATE_TYPE = "application/x-sankey-studio-move";

const GRAPH_CARD = '[data-testid="graph-card"]';
const FOLDER_CARD = '[data-testid="folder-card"]';
const ZONES = `${FOLDER_CARD}, [data-testid="folder-crumb"]`;
const MARKS = ["data-dragging", "data-drop", "data-drop-reason"];

function elementOf(node) {
  return node instanceof Element ? node : (node?.parentElement ?? null);
}

class Dnd {
  constructor({ root, selection, host }) {
    this.root = root;
    this.selection = selection;
    this.host = host;
    this.drag = null;
    const listeners = {
      dragstart: (event) => this.start(event),
      dragenter: (event) => this.over(event),
      dragover: (event) => this.over(event),
      dragleave: (event) => this.leave(event),
      drop: (event) => this.drop(event),
      dragend: () => this.end(),
    };
    for (const [type, listener] of Object.entries(listeners)) {
      root.addEventListener(type, listener);
    }
    window.addEventListener("blur", () => this.end());
    watchGrips(root, `${GRAPH_CARD}, ${FOLDER_CARD}`);
  }

  /** Takes the card a drag started on (the event target can be its link or a text node inside it). */
  start(event) {
    const card = elementOf(event.target)?.closest(`${GRAPH_CARD}, ${FOLDER_CARD}`);
    if (!card || !this.root.contains(card) || card.getAttribute("draggable") !== "true" || !this.host.allowed()) {
      return; // not ours (a card that is no source, a link, text, read-only, search results): the browser does what it always did
    }
    const transfer = event.dataTransfer;
    if (this.host.busy || !transfer) {
      event.preventDefault();
      return;
    }
    this.end(); // marks of a drag whose end was never seen
    const drag = this.carry(card);
    transfer.clearData(); // a dragged link brings its address along; a stray drop must not navigate
    transfer.setData(PRIVATE_TYPE, drag.kind); // Firefox only starts a drag that has data
    transfer.effectAllowed = "move";
    const box = card.getBoundingClientRect();
    transfer.setDragImage(card, event.clientX - box.left, event.clientY - box.top); // the card, not the link text
    this.drag = drag;
    // a redraw can remove the source mid-drag: its `dragend` then never reaches the root, but still reaches the node
    event.target.addEventListener("dragend", () => this.end(drag), { once: true });
    requestAnimationFrame(() => this.mark(drag));
  }

  /**
   * What the drag carries: `{kind, items: [{id, name}], picked, local, zone}`. `picked`: the carried set is the
   * selection. `local`: every carried graph is on the page now, so each one sits directly in the open
   * collection (a pick made in a search can come from anywhere, and then no place is "already here").
   */
  carry(card) {
    if (card.matches(FOLDER_CARD)) {
      return { kind: "folder", items: [{ id: card.dataset.folderId, name: "" }], picked: false, local: true, zone: null };
    }
    const id = card.dataset.graphId;
    const picked = this.selection.has(id);
    const name = card.querySelector('[data-testid="graph-open"]')?.textContent ?? "";
    const items = picked ? this.selection.items() : [{ id, name }];
    const shown = new Set(Array.from(this.root.querySelectorAll(GRAPH_CARD), (el) => el.dataset.graphId));
    return { kind: "graph", items, picked, local: items.every((item) => shown.has(item.id)), zone: null };
  }

  /** Marks the carried cards, unless the drag already ended before the first frame. */
  mark(drag) {
    if (this.drag !== drag) {
      return;
    }
    const ids = new Set(drag.items.map((item) => item.id));
    for (const card of this.root.querySelectorAll(drag.kind === "graph" ? GRAPH_CARD : FOLDER_CARD)) {
      if (ids.has(card.dataset.graphId ?? card.dataset.folderId)) {
        card.dataset.dragging = "true";
      }
    }
  }

  /** Our drag, when this event belongs to it; `null` for anything else. */
  current(event) {
    const types = Array.from(event.dataTransfer?.types ?? []);
    return this.drag !== null && types.includes(PRIVATE_TYPE) ? this.drag : null;
  }

  /** The target under a node: `{el, target, reason}` (`target` null = the library), or `null` when it is no target. */
  zoneAt(drag, node) {
    const el = elementOf(node)?.closest(ZONES);
    const id = el?.dataset.folderId;
    if (!el || !id || !this.root.contains(el)) {
      return null;
    }
    if (drag.zone?.el === el) {
      return drag.zone;
    }
    const target = id === "root" ? null : id;
    return { el, target, reason: this.host.reason(drag, target) };
  }

  /** Moves the target marks to `zone` (nothing changes while the pointer stays on the same one). */
  setZone(drag, zone) {
    if ((drag.zone?.el ?? null) === (zone?.el ?? null)) {
      return;
    }
    this.clearZone(drag);
    drag.zone = zone;
    if (zone !== null) {
      zone.el.dataset.drop = zone.reason === null ? "ok" : "denied";
      if (zone.reason !== null) {
        zone.el.dataset.dropReason = zone.reason;
        announce(`Not possible: ${zone.reason}`); // the cursor and the dashed border say no; this says why
      }
    }
  }

  clearZone(drag) {
    const el = drag.zone?.el;
    if (el) {
      delete el.dataset.drop;
      delete el.dataset.dropReason;
    }
    drag.zone = null;
  }

  /** `dragenter` and `dragover`: accept the drop on a target that can take the drag, refuse it elsewhere. */
  over(event) {
    const drag = this.current(event);
    if (drag === null) {
      return; // foreign: not ours to judge
    }
    const zone = this.zoneAt(drag, event.target);
    this.setZone(drag, zone);
    const accepts = zone !== null && zone.reason === null;
    event.dataTransfer.dropEffect = accepts ? "move" : "none"; // on every event: Safari, and Ctrl/Option flip it to copy
    if (accepts) {
      event.preventDefault();
    }
  }

  /** Leaving the page root (or the window) clears the target mark; moves between children are settled by `dragover`. */
  leave(event) {
    const drag = this.current(event);
    if (drag === null) {
      return;
    }
    // Safari gives no relatedTarget: ask where the pointer is (null outside the window)
    const to = event.relatedTarget instanceof Node ? event.relatedTarget : document.elementFromPoint(event.clientX, event.clientY);
    if (to === null || !this.root.contains(to)) {
      this.clearZone(drag);
    }
  }

  drop(event) {
    const drag = this.current(event);
    if (drag === null) {
      return; // foreign: the browser keeps its own behaviour
    }
    event.preventDefault(); // a dropped link must never navigate
    const zone = this.zoneAt(drag, event.target);
    this.end();
    if (zone !== null && zone.reason === null) {
      this.host.drop(drag, zone.target);
    }
  }

  /** Forgets the drag and removes every mark; `only` limits it to that drag (a late `dragend` of an older one). */
  end(only = null) {
    if (only !== null && this.drag !== only) {
      return;
    }
    this.drag = null;
    for (const el of this.root.querySelectorAll("[data-dragging], [data-drop]")) {
      MARKS.forEach((name) => el.removeAttribute(name));
    }
  }
}

/**
 * @param {{root: HTMLElement, selection: {has: (id: string) => boolean, items: () => {id: string, name: string}[]}, host: {allowed: () => boolean, busy: boolean, reason: (drag: object, target: string | null) => string | null, drop: (drag: object, target: string | null) => Promise<void>}}} options
 * @returns {Dnd}
 */
export function createDnd(options) {
  return new Dnd(options);
}
