// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * A collapsed, lazily built JSON tree for the sample documents of a MongoDB collection.
 *
 * Every value is shown with `textContent` (never as markup). Objects and arrays are `<details>`
 * elements that build their children when first opened, long strings are cut, a node shows at most
 * 60 children and nesting stops at depth 6, so a huge document cannot freeze the page.
 *
 * `jsonTree(value, {label})` -> an element; `label` is the title of the root (for example
 * "Document 1").
 */

import { h } from "../../core/dom.js";

const MAX_CHILDREN = 60;
const MAX_DEPTH = 6;
const MAX_TEXT = 200;

function leafText(value) {
  if (typeof value === "string") {
    return value.length > MAX_TEXT ? `"${value.slice(0, MAX_TEXT)}…"` : `"${value}"`;
  }
  return String(value);
}

function leaf(key, value) {
  const kind = value === null ? "null" : typeof value;
  return h(
    "div",
    { class: "ed-json-leaf" },
    key === null ? null : h("span", { class: "ed-json-key" }, `${key}: `),
    h("span", { class: "ed-json-value", "data-type": kind }, leafText(value)),
  );
}

function children(entries, depth) {
  const shown = entries.slice(0, MAX_CHILDREN).map(([key, value]) => node(key, value, depth + 1));
  if (entries.length > MAX_CHILDREN) {
    shown.push(h("div", { class: "ed-json-more" }, `… ${entries.length - MAX_CHILDREN} more`));
  }
  return shown;
}

function node(key, value, depth) {
  if (value === null || typeof value !== "object") {
    return leaf(key, value);
  }
  const list = Array.isArray(value);
  const entries = list ? value.map((item, index) => [index, item]) : Object.entries(value);
  const summary = h(
    "summary",
    null,
    key === null ? null : h("span", { class: "ed-json-key" }, `${key}: `),
    h("span", { class: "ed-json-meta" }, list ? `list of ${entries.length}` : `${entries.length} ${entries.length === 1 ? "field" : "fields"}`),
  );
  const body = h("div", { class: "ed-json-children" });
  const el = h("details", { class: "ed-json-node" }, summary, body);
  el.addEventListener("toggle", () => {
    if (el.open && body.childElementCount === 0) {
      body.replaceChildren(...(depth >= MAX_DEPTH ? [h("div", { class: "ed-json-more" }, "…")] : children(entries, depth)));
    }
  });
  return el;
}

/**
 * Builds the tree of one value.
 * @param {unknown} value
 * @param {{label?: string}} [options]
 * @returns {HTMLElement}
 */
export function jsonTree(value, options = {}) {
  return node(options.label ?? null, value, 0);
}
