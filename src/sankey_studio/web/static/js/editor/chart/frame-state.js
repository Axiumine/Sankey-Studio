// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * What the chart frame shows when there is no chart (or a chart that failed): a calm overlay for
 * loading, empty and error. The frame keeps its reserved height, so nothing jumps.
 *
 * - `overlayFor({bundle, previewing, error})` -> `"loading" | "error" | "empty" | "nolinks" | null`
 *   (null = show the chart; a refetch with a chart on screen keeps the chart, see `out-updating`).
 *   `nolinks` is a bundle with nothing to draw (zero nodes): Plotly cannot draw a Sankey of nothing.
 * - `noLinksReason(bundle, transform)` -> `{title, message}`: why there is nothing to draw (the Transform
 *   settings filter every link, every row was skipped, or the data has no rows).
 * - `buildOverlay(kind, error, onRetry, reason)` -> the element for that kind (core/states.js blocks); `basis` is the
 *   donut whose basis leaves out every categorised entry (the server figure is only axes then).
 * - `setOverlay(frame, node | null)` swaps the overlay of a `.chart-frame`.
 */

import { h } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { emptyState, errorState, loadingState } from "../../core/states.js";
import { hasDrawing } from "../output-panel-kit.js";
import { describePreviewError, isTransient } from "./errors.js";

/**
 * Which overlay the frame needs.
 * @param {{bundle: object | null, previewing: boolean, error: object | null}} model
 * @returns {"loading" | "error" | "empty" | "nolinks" | null}
 */
export function overlayFor(model) {
  if (model.bundle) {
    return hasDrawing(model.bundle) ? null : "nolinks";
  }
  if (model.previewing) {
    return "loading";
  }
  if (model.error) {
    return "error";
  }
  return "empty";
}

function errorOverlay(error, onRetry) {
  const info = describePreviewError(error);
  const state = errorState({ title: info.title, message: info.message, compact: true, onRetry: isTransient(error) ? onRetry : undefined });
  if (info.details.length > 0) {
    state.querySelector(".state-text")?.after(h("ul", { class: "out-detail-list" }, info.details.map((text) => h("li", null, text))));
  }
  return state;
}

/**
 * @param {{warnings?: string[]}} bundle  a bundle with zero nodes
 * @param {{min_link_value?: number, hide_nodes?: string[]} | undefined} transform  the draft's Transform settings
 * @returns {{title: string, message: string}}
 */
export function noLinksReason(bundle, transform) {
  const filters = [];
  if (Number(transform?.min_link_value) > 0) {
    filters.push(`minimum link value ${formatNumber(Number(transform.min_link_value))}`);
  }
  if ((transform?.hide_nodes?.length ?? 0) > 0) {
    filters.push(`${transform.hide_nodes.length} hidden ${transform.hide_nodes.length === 1 ? "node" : "nodes"}`);
  }
  if (filters.length > 0) {
    return { title: "No link is left to draw", message: `Your Transform settings filter every link out (${filters.join(", ")}). Loosen them under Transform and the chart comes back.` };
  }
  if ((bundle.warnings ?? []).length > 0) {
    return { title: "No row could be read", message: "Every row of the data was skipped, so there is nothing to draw. The notes below the chart say why." };
  }
  return { title: "No links to draw yet", message: "The data has no row with a source, a target and a value above zero. Add one and the chart appears." };
}

/**
 * @param {"loading" | "error" | "empty" | "nolinks" | "basis"} kind
 * @param {object | null} error  the preview error (for `error`)
 * @param {() => void} [onRetry]  "Try again" for a transient error
 * @param {{title: string, message: string}} [reason]  from `noLinksReason` (for `nolinks`)
 * @returns {HTMLElement}
 */
export function buildOverlay(kind, error, onRetry, reason) {
  if (kind === "loading") {
    return h("div", { class: "chart-overlay out-loading" }, loadingState({ label: "Drawing the chart", block: true }));
  }
  if (kind === "error") {
    return errorOverlay(error, onRetry);
  }
  if (kind === "nolinks") {
    return emptyState({ title: reason.title, message: reason.message, icon: "bar-chart", compact: true });
  }
  if (kind === "basis") {
    return emptyState({
      title: "No categorised entry is counted",
      message: "Your donut basis leaves out every categorised entry. Change the basis under Style, or categorise entries that start or end a flow.",
      icon: "pie-chart",
      compact: true,
    });
  }
  return emptyState({
    title: "Nothing to draw yet",
    message: "Paste or upload some flows (source, target, value), type a few in the table, or pick a MongoDB collection. The chart appears here as you go.",
    icon: "bar-chart",
    compact: true,
  });
}

/**
 * Replaces the overlay of a chart frame (null removes it).
 * @param {HTMLElement} frame  a `.chart-frame` from core/chart.js `createChartFrame`
 * @param {HTMLElement | null} node
 */
export function setOverlay(frame, node) {
  for (const child of Array.from(frame.children)) {
    if (!child.classList.contains("chart-surface")) {
      child.remove();
    }
  }
  if (node) {
    frame.append(node);
  }
}
