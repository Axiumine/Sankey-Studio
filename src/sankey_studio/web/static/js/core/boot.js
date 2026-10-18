// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Page boot data: the JSON the server embeds in `<script type="application/json" id="page-data">`
 * (docs/api.md, section 8.2). It is the only place page data enters the page; read it through here.
 *
 * Shape: `{page, remote_mode, writes_allowed, ...}` plus per page keys (`graphs`/`total` on the
 * library, `graph` on viewer/editor, `ids`/`graphs` on compare). A missing or broken block gives
 * a read-only fallback (`page: "unknown"`, `writes_allowed: false`) instead of throwing.
 *
 * Also the mount points of the shell: `pageRoot()` (where a page draws itself), `pageActions()`
 * (the button row next to the heading), `setHeading(text)` (new `<h1>` and document title, e.g.
 * after a rename) and `lockWriteControls(root)` (disables every `[data-writes]` control inside
 * `root` when the server is read-only, with an explanatory title).
 */

import { stripBidi } from "./text.js";

const FALLBACK = Object.freeze({ page: "unknown", remote_mode: false, writes_allowed: false });
let cached = null;

/**
 * The parsed boot data (frozen, parsed once).
 * @returns {Readonly<Record<string, any>>}
 */
export function boot() {
  if (cached) {
    return cached;
  }
  const node = document.getElementById("page-data");
  try {
    const data = JSON.parse(node ? node.textContent : "");
    cached = Object.freeze(data && typeof data === "object" ? data : { ...FALLBACK });
  } catch {
    cached = FALLBACK;
  }
  return cached;
}

/**
 * True when this server persists changes. Write controls must be disabled otherwise.
 * @returns {boolean}
 */
export function canWrite() {
  return boot().writes_allowed === true;
}

/**
 * True when the server runs in remote mode (reachable from other machines, no login).
 * @returns {boolean}
 */
export function isRemote() {
  return boot().remote_mode === true;
}

/**
 * The element a page renders into (`#page-root`, below the heading).
 * @returns {HTMLElement}
 */
export function pageRoot() {
  return document.getElementById("page-root") ?? document.body;
}

/**
 * The action row next to the heading (`#page-actions`); empty on load.
 * @returns {HTMLElement}
 */
export function pageActions() {
  return document.getElementById("page-actions") ?? document.body;
}

/**
 * Sets the page heading (the shell's `<h1>`) and the document title.
 * @param {string} text
 */
export function setHeading(text) {
  const heading = document.querySelector("#main h1");
  if (heading) {
    heading.textContent = stripBidi(text);
  }
  document.title = `${stripBidi(text)} - Sankey Studio`;
}

/**
 * Disables the write controls (elements marked `data-writes`) when the server is read-only.
 * @param {ParentNode} [root]
 * @returns {number} how many controls were locked
 */
export function lockWriteControls(root = document) {
  if (canWrite()) {
    return 0;
  }
  const controls = Array.from(root.querySelectorAll("[data-writes]"));
  for (const control of controls) {
    control.disabled = true;
    control.setAttribute("aria-disabled", "true");
    control.title = "Not available: this server is read-only";
    if (control.localName === "a") {
      control.removeAttribute("href"); // a link ignores `disabled`: without href it cannot be followed or focused
    }
  }
  return controls.length;
}
