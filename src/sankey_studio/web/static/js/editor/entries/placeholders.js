// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * What the entries list shows instead of the table: loading, "no data yet" and "nothing matches".
 *
 * `placeholderFor({phase, hasRows, hasFilter, error, retry}, onClear)` -> an element, or null when the table
 * itself should show (loading keeps the previous rows; only a first load shows the skeleton).
 */

import { h } from "../../core/dom.js";
import { emptyState, errorState, loadingState } from "../../core/states.js";
import { describePreviewError, isTransient } from "../chart/errors.js";
import { sentence } from "../output-panel-kit.js";

/**
 * @param {{phase: string, hasRows: boolean, hasFilter: boolean, error?: object | null, retry?: () => void}} model
 * @param {() => void} onClear  clears the search and filters
 * @returns {HTMLElement | null}
 */
export function placeholderFor(model, onClear) {
  if (model.phase === "loading") {
    return loadingState({ label: "Loading entries", lines: 4 });
  }
  if (model.phase === "empty") {
    return emptyState({ title: "No entries yet", message: "Once the chart has data, every source to target flow is listed here so you can give it a category.", icon: "table", compact: true });
  }
  if (model.phase === "error" && !model.hasRows) {
    const message = sentence(describePreviewError(model.error).message);
    return errorState({ title: "The entries could not be loaded", message, compact: true, onRetry: isTransient(model.error) ? model.retry : undefined });
  }
  if (model.hasRows || model.phase === "error") {
    return null;
  }
  if (!model.hasFilter) {
    return emptyState({ title: "No entries", message: "This graph has no flows to list.", icon: "table", compact: true });
  }
  const clear = h("button", { type: "button", class: "btn", on: { click: onClear } }, "Clear the search and filters");
  return emptyState({ title: "No entries match", message: "Nothing fits the search and filters you set.", icon: "search", compact: true, actions: [clear] });
}
