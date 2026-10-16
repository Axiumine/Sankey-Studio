// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Accessibility helpers.
 *
 * - `announce(message, {assertive})`: speaks `message` through the visually hidden live regions
 *   of the shell (`#a11y-polite`, `#a11y-assertive`). The region is cleared first so the same
 *   message twice is announced twice. Use it for results that have no visible focus change
 *   ("12 graphs found", "Saved", "Preview updated").
 * - `prefersReducedMotion()`: honour it before any scripted animation or smooth scrolling.
 * - `setTitle(text)`: sets the document title as "<text> - Sankey Studio".
 */

import { stripBidi } from "./text.js";

const SUFFIX = "Sankey Studio";

/**
 * Announces a message to screen readers.
 * @param {string} message
 * @param {{assertive?: boolean}} [options]
 */
export function announce(message, options = {}) {
  const id = options.assertive ? "a11y-assertive" : "a11y-polite";
  const region = document.getElementById(id);
  if (!region) {
    return;
  }
  region.textContent = "";
  requestAnimationFrame(() => {
    region.textContent = stripBidi(message);
  });
}

/**
 * True when the visitor asked for less motion.
 * @returns {boolean}
 */
export function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Sets the document title to "<text> - Sankey Studio".
 * @param {string} text
 */
export function setTitle(text) {
  document.title = text ? `${stripBidi(text)} - ${SUFFIX}` : SUFFIX;
}
