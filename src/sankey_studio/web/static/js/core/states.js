// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Honest empty, error and loading states, so every page looks the same when there is nothing to
 * show. Each returns an element to mount (core/dom.js `mount`); text always goes through
 * textContent.
 *
 * - `emptyState({title, message, icon, actions, compact})`: nothing here yet, say what to do.
 * - `errorState({title, message, onRetry, retryLabel})`: what failed, with a retry button when a
 *   retry makes sense (role="alert").
 * - `loadingState({label, lines, block})`: skeleton lines or one block inside a role="status"
 *   region; the label is read by screen readers. Keep the previous content visible (class
 *   `is-stale`) when RE-loading instead of swapping in a skeleton.
 * Test ids: `state-empty`, `state-error`, `state-retry`, `state-loading` (testids-extra.txt).
 */

import { h } from "./dom.js";
import { icon } from "./icons.js";

/**
 * @param {{title: string, message?: string, icon?: string, actions?: Node[], compact?: boolean, testid?: string}} options
 * @returns {HTMLElement}
 */
export function emptyState(options) {
  return h(
    "div",
    { class: ["state", options.compact ? "is-compact" : null], "data-kind": "empty", "data-testid": options.testid ?? "state-empty" },
    h("div", { class: "state-icon" }, icon(options.icon ?? "file", { size: 22 })),
    h("div", { class: "state-title" }, options.title),
    options.message ? h("p", { class: "state-text" }, options.message) : null,
    options.actions?.length ? h("div", { class: "state-actions" }, options.actions) : null,
  );
}

/**
 * @param {{title?: string, message: string, onRetry?: () => void, retryLabel?: string, compact?: boolean}} options
 * @returns {HTMLElement}
 */
export function errorState(options) {
  const retry = options.onRetry
    ? h("button", { type: "button", class: "btn", "data-testid": "state-retry", on: { click: options.onRetry } }, icon("refresh"), options.retryLabel ?? "Try again")
    : null;
  return h(
    "div",
    { class: ["state", options.compact ? "is-compact" : null], role: "alert", "data-kind": "error", "data-testid": "state-error" },
    h("div", { class: "state-icon" }, icon("alert", { size: 22 })),
    h("div", { class: "state-title" }, options.title ?? "Something went wrong"),
    h("p", { class: "state-text" }, options.message),
    retry ? h("div", { class: "state-actions" }, retry) : null,
  );
}

/**
 * @param {{label?: string, lines?: number, block?: boolean}} [options]
 * @returns {HTMLElement}
 */
export function loadingState(options = {}) {
  const lines = options.lines ?? 3;
  const skeleton = options.block
    ? h("span", { class: "skeleton skeleton-block" })
    : Array.from({ length: lines }, (_, i) => h("span", { class: ["skeleton", "skeleton-line", i === lines - 1 ? "is-short" : null] }));
  return h(
    "div",
    { class: "state-loading", role: "status", "aria-busy": "true", "data-testid": "state-loading" },
    h("span", { class: "visually-hidden" }, options.label ?? "Loading"),
    skeleton,
  );
}
