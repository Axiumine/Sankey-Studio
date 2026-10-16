// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * "Graph-only edits (N)": the visible, removable list of what this graph holds that its data does not.
 *
 * Category edits, added entries and a custom node order that could not be written to the data stay
 * in the graph (`transform.entry_categories`, `transform.extra_links`, `style.node_order`, listed
 * in ../source/overlays.js `OVERLAYS`). A toast says so once; this chip keeps it visible afterwards.
 *
 * Pure parts (node-testable):
 * - `overlayCount(state)` -> how many items there are (cheap: lengths only; a custom node order is ONE);
 * - `overlayItems(state)` -> `[{kind, path, value, text}]` one per item, in OVERLAYS order; the
 *   custom node order is ONE item;
 * - `withoutItem(draft, item)` -> the draft without that item (a new object).
 *
 * `createOverlayList({store, after})` -> `{el, dispose}`: the chip `entries-overlays` (hidden at 0)
 * opening the dialog `overlays-dialog`: the sentence "These edits are stored in this graph, not in
 * your data.", one row per item and a `overlay-remove` button on each. Removing patches the store at
 * once (the chart and the table follow, the graph becomes unsaved); the focus moves to the next
 * Remove button; at most 200 rows are drawn. `after` is the element that takes the focus when the
 * chip disappears with the last item.
 */

import { openDialog } from "../../core/dialog.js";
import { h } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { closePopovers } from "../../core/popover.js";
import { stripBidi } from "../../core/text.js";
import { OVERLAYS } from "../source/overlays.js";

/** At most this many rows are drawn in the dialog. */
export const LISTED_MAX = 200;

const NONE = Object.freeze([]);
const ORDER = "draft.style.node_order";
const DESCRIBE = {
  "draft.transform.entry_categories": (item) => `${item.source} to ${item.target}: ${item.category ? `category ${item.category}` : "no category"}`,
  "draft.transform.extra_links": (item) => `${item.source} to ${item.target}: ${formatNumber(item.value)}${item.category ? `, category ${item.category}` : ""}`,
};

function listAt(state, path) {
  let node = state;
  for (const key of path) {
    node = node?.[key];
  }
  return Array.isArray(node) ? node : NONE;
}

/**
 * @param {object} state  the store state
 * @returns {number}
 */
export function overlayCount(state) {
  return OVERLAYS.reduce((sum, overlay) => {
    const size = listAt(state, overlay.path).length;
    return sum + (overlay.path.join(".") === ORDER ? Math.min(size, 1) : size);
  }, 0);
}

/**
 * @param {object} state  the store state
 * @returns {{kind: string, path: string[], value: unknown, text: string}[]}
 */
export function overlayItems(state) {
  const items = [];
  for (const overlay of OVERLAYS) {
    const kind = overlay.path.join(".");
    const list = listAt(state, overlay.path);
    if (kind === ORDER && list.length > 0) {
      items.push({ kind, path: overlay.path, value: list, text: `Custom node order (${list.length} ${list.length === 1 ? "node" : "nodes"})` });
    } else if (kind !== ORDER) {
      const describe = DESCRIBE[kind] ?? (() => overlay.describe(list.length));
      items.push(...list.map((value) => ({ kind, path: overlay.path, value, text: stripBidi(describe(value)) })));
    }
  }
  return items;
}

/**
 * @param {object} draft
 * @param {{kind: string, value: unknown}} item
 * @returns {object}
 */
export function withoutItem(draft, item) {
  const [, section, key] = item.kind.split(".");
  const holder = draft[section] ?? {};
  const next = item.kind === ORDER ? [] : (holder[key] ?? []).filter((entry) => entry !== item.value);
  return { ...draft, [section]: { ...holder, [key]: next } };
}

function row(item, onRemove) {
  const remove = h("button", { type: "button", class: "btn btn-sm", "aria-label": `Remove ${item.text}`, "data-testid": "overlay-remove", on: { click: () => onRemove(item) } }, "Remove");
  return h("li", { class: "out-overlay-row" }, h("span", { class: "out-overlay-text" }, item.text), remove);
}

function body(items, onRemove) {
  const shown = items.slice(0, LISTED_MAX);
  const more = items.length - shown.length;
  return [
    h("p", null, "These edits are stored in this graph, not in your data."),
    items.length === 0 ? h("p", { class: "hint" }, "No graph-only edits are left.") : h("ul", { class: "out-overlay-list" }, shown.map((item) => row(item, onRemove))),
    more > 0 ? h("p", { class: "hint" }, `${more} more are not shown. Remove the ones above to see them.`) : null,
  ];
}

function openList({ store, after }) {
  closePopovers();
  const view = h("div", { class: "stack stack-sm" });
  const paint = () => view.replaceChildren(...body(overlayItems(store.get()), remove).filter(Boolean));
  const remove = (item) => {
    const at = overlayItems(store.get()).findIndex((other) => other.kind === item.kind && other.value === item.value);
    store.patch("draft", (draft) => withoutItem(draft, item));
    paint();
    const buttons = view.querySelectorAll('[data-testid="overlay-remove"]');
    (buttons[Math.min(at, buttons.length - 1)] ?? done())?.focus();
  };
  const done = () => dialog.el.querySelector(".dialog-actions button");
  paint();
  const dialog = openDialog({
    title: "Graph-only edits",
    testid: "overlays-dialog",
    closeButton: true,
    body: view,
    initialFocus: (el) => el.querySelector(".dialog-actions button"),
    actions: [{ label: "Done", kind: "primary", value: "done" }],
  });
  dialog.result.then(() => {
    if (after && overlayCount(store.get()) === 0) {
      after.focus(); // the chip left with the last item: the opener cannot take the focus back
    }
  });
}

/**
 * @param {{store: object, after?: HTMLElement}} deps
 * @returns {{el: HTMLButtonElement, dispose: () => void}}
 */
export function createOverlayList({ store, after }) {
  const el = h("button", { type: "button", class: "chip out-overlay-chip", hidden: true, "aria-haspopup": "dialog", title: "Edits stored in this graph, not in your data", "data-testid": "entries-overlays", on: { click: () => openList({ store, after }) } });
  const paint = () => {
    const count = overlayCount(store.get());
    el.hidden = count === 0;
    el.textContent = `Graph-only edits (${count})`;
  };
  paint();
  const offs = OVERLAYS.map((overlay) => store.subscribe(paint, { select: (state) => listAt(state, overlay.path) }));
  return { el, dispose: () => offs.forEach((off) => off()) };
}
