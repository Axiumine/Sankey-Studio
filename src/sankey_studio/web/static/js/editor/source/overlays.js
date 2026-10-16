// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Graph-level edits that only make sense for the data they were made on: the "overlays".
 *
 * They are stored in the graph, not in its data, so after the data source is replaced they may
 * point at rows that are gone. This is the ONLY place that lists them:
 *   transform.entry_categories  category edits that could not be written to the data
 *   transform.extra_links       entries added to the graph only
 *   style.node_order            a custom node order
 * Hide / merge nodes and category rules are name based and harmless when a name is absent, so a
 * source change keeps them.
 *
 * - `OVERLAYS` - `[{path, count(list), describe(count)}]`.
 * - `overlaySummary(state)` -> `{count, text}`: how many overlay items exist and a sentence part
 *   such as "3 category edits, a custom node order" (empty text when there are none).
 * - `clearOverlays(store)` removes every present overlay (call it inside the caller's batch).
 * - `askKeepOverlays(store)` -> `Promise<"keep"|"drop"|"cancel">`: the one-line question shared by
 *   the change-source dialog and the inline tab strip; resolves "keep" without asking when there
 *   is nothing to keep.
 * The question's buttons ("Cancel", "Drop them", "Keep them") carry no test ids: tests find them by role.
 */

import { closePopovers } from "../../core/popover.js";
import { openDialog } from "../../core/dialog.js";
import { h } from "../../core/dom.js";
import { formatCount } from "../../core/format.js";

/** @type {{path: string[], describe: (count: number) => string}[]} */
export const OVERLAYS = [
  { path: ["draft", "transform", "entry_categories"], describe: (count) => formatCount(count, "category edit") },
  { path: ["draft", "transform", "extra_links"], describe: (count) => formatCount(count, "added entry", "added entries") },
  { path: ["draft", "style", "node_order"], describe: () => "a custom node order" },
];

function lengthAt(state, path) {
  let node = state;
  for (const key of path) {
    node = node?.[key];
  }
  return Array.isArray(node) ? node.length : 0;
}

/**
 * Counts the overlay items of a store state.
 * @param {object} state
 * @returns {{count: number, text: string}}
 */
export function overlaySummary(state) {
  let count = 0;
  const parts = [];
  for (const overlay of OVERLAYS) {
    const n = lengthAt(state, overlay.path);
    if (n > 0) {
      count += n;
      parts.push(overlay.describe(n));
    }
  }
  return { count, text: parts.join(", ") };
}

/**
 * Removes every overlay that is present.
 * @param {{get: () => object, remove: (path: string[]) => void, batch: (fn: () => void) => void}} store
 */
export function clearOverlays(store) {
  store.batch(() => {
    for (const overlay of OVERLAYS) {
      if (lengthAt(store.get(), overlay.path) > 0) {
        store.remove(overlay.path);
      }
    }
  });
}

/**
 * Asks whether the graph-only edits stay when the source changes. Drops nothing itself: the
 * caller clears them on "drop".
 * @param {{get: () => object}} store
 * @returns {Promise<"keep"|"drop"|"cancel">}
 */
export async function askKeepOverlays(store) {
  const { count, text } = overlaySummary(store.get());
  if (count === 0) {
    return "keep";
  }
  closePopovers();
  const dialog = openDialog({
    title: "Keep your edits to this graph?",
    body: h("p", null, `This graph has ${text}. They were made on the current data and may not fit the new source.`),
    actions: [
      { label: "Cancel", value: "cancel" },
      { label: "Drop them", value: "drop" },
      { label: "Keep them", value: "keep", kind: "primary", initial: true },
    ],
  });
  return (await dialog.result) ?? "cancel";
}
