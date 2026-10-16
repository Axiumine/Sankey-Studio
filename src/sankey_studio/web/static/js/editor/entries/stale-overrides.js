// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * "N of your category edits no longer match an entry": the Entries card says so when graph-only
 * category edits (`transform.entry_categories`) point at pairs the data no longer has (a node was
 * renamed, a row deleted).
 *
 * The server reports it as the preview warning "N entry_categories matched no entry" (the chart's
 * warning list words it too); this notice puts the same fact next to the table where the edits were
 * made. The stale items are listed under "Graph-only edits" (./overlay-list.js), where each can be
 * removed.
 *
 * - `unmatchedCount(warnings)` -> how many category edits matched nothing (0 when none).
 * - `unmatchedText(count)` -> the sentence.
 * - `createStaleOverrides({store})` -> `{el, dispose}`; `el` is an empty slot that holds the notice
 *   (`entries-unmatched`) only while there is something to say.
 */

import { h } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { present, slot } from "../output-panel-kit.js";

const UNMATCHED = /^(\d+) entry_categories matched no entry$/;

/**
 * @param {unknown} warnings  `bundle.warnings`
 * @returns {number}
 */
export function unmatchedCount(warnings) {
  let count = 0;
  for (const warning of Array.isArray(warnings) ? warnings : []) {
    const found = typeof warning === "string" ? UNMATCHED.exec(warning) : null;
    count += found ? Number(found[1]) : 0;
  }
  return count;
}

/**
 * @param {number} count
 * @returns {string}
 */
export function unmatchedText(count) {
  const edits = count === 1 ? "1 of your category edits no longer matches an entry (the name changed)" : `${count} of your category edits no longer match an entry (the names changed)`;
  return `${edits}. ${count === 1 ? "It is" : "They are"} ignored and listed under Graph-only edits.`;
}

/**
 * @param {{store: {get: Function, subscribe: Function}}} deps
 * @returns {{el: HTMLElement, dispose: () => void}}
 */
export function createStaleOverrides({ store }) {
  const place = slot();
  const body = h("div", { class: "notice-body" });
  const notice = h("div", { class: "notice out-basis", "data-kind": "info", role: "status", "data-testid": "entries-unmatched" }, icon("info", { size: 16 }), body);
  const paint = () => {
    const count = unmatchedCount(store.get().bundle?.warnings);
    if (count > 0) {
      body.textContent = unmatchedText(count);
    }
    present(place, notice, count > 0);
  };
  paint();
  return { el: place, dispose: store.subscribe(paint, { select: (state) => state.bundle }) };
}
