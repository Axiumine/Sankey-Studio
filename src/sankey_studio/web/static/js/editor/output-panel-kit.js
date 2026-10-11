/**
 * Small helpers shared by the four OUTPUT panels of the editor (chart, entries, export, savebar).
 *
 * - `ensureOutputStyles()` loads `/static/css/pages-editor-output.css` once and resolves when it is
 *   applied (or failed: the panels then look plain but still work), so a panel never paints
 *   unstyled and never shifts when the sheet arrives. Panels `await` it before they build DOM.
 * - `hasDrawing(bundle)`: true when the bundle has a chart to draw (at least one node). A graph whose
 *   rows were all skipped, or whose Transform settings filter every link away, has a bundle but nothing
 *   to draw: Plotly cannot draw a Sankey of zero nodes, so no panel hands it one.
 * - `safeColor(value)` returns a server-sent CSS colour only when the browser accepts it as one.
 * - `swatch(color)` is the small square that carries a series identity beside ink-coloured text
 *   (text never wears a data colour).
 * - `plainError(error)` turns any failure into one sentence for a notice or a toast.
 * - `sentence(text)` ends a server message with a full stop when it has no closing punctuation, so
 *   another sentence can follow it ("... close it. The chart below ...").
 * - `pairLabel(source, target)` is the accessible name of an entry ("Salary to Rent").
 * - `focusTestId(id)` moves focus to the first element with that test id, if it is on the page.
 * - `trackEdit(promise)` / `editsSettled()`: the entries panel registers every category edit that is
 *   still being checked by the server; the save bar waits for them, so "type a category, click Save"
 *   never saves the graph without the category.
 * - `slot()` / `present(slot, node, on)`: a stable place in a layout where a notice, hint or banner is
 *   put in or taken out. An element that has nothing to say is NOT in the page (not just hidden), so
 *   it cannot be read, tabbed to or counted by mistake; the empty slot takes no space.
 */

import { h } from "../core/dom.js";
import { ensureStylesheet } from "../core/stylesheet.js";

const STYLE_HREF = "/static/css/pages-editor-output.css";

/**
 * Loads the stylesheet of the output panels (once).
 * @returns {Promise<void>}
 */
export function ensureOutputStyles() {
  return ensureStylesheet(STYLE_HREF);
}

/**
 * @param {{stats?: {nodes?: number}} | null | undefined} bundle  `store.bundle`
 * @returns {boolean}
 */
export function hasDrawing(bundle) {
  return Boolean(bundle) && (bundle.stats?.nodes ?? 1) > 0;
}

/**
 * A colour the browser understands, or null (never put an unchecked string into a style).
 * @param {unknown} value
 * @returns {string | null}
 */
export function safeColor(value) {
  return typeof value === "string" && value.length <= 64 && CSS.supports("color", value) ? value : null;
}

/**
 * A colour swatch element; the colour reaches the CSS through the `--swatch` custom property.
 * @param {unknown} color  a server-sent colour
 * @param {string} [kind]  `category`, `uncategorized`, `other`, `layer`, `node` (hatch for `other`)
 * @returns {HTMLElement}
 */
export function swatch(color, kind = "") {
  return h("span", { class: "swatch out-swatch", "data-kind": kind, "aria-hidden": "true", style: { "--swatch": safeColor(color) } });
}

/**
 * One sentence for a failure (an ApiError, an Error or anything else).
 * @param {unknown} error
 * @returns {string}
 */
export function plainError(error) {
  if (error && typeof error === "object") {
    const text = error.friendly ?? error.message;
    if (typeof text === "string" && text) {
      return text;
    }
  }
  return "Something went wrong.";
}

/**
 * The text as a finished sentence (a full stop is added when it ends without punctuation).
 * @param {unknown} text
 * @returns {string}
 */
export function sentence(text) {
  const value = String(text ?? "").trim();
  return /[.!?\u2026]$/.test(value) ? value : `${value}.`;
}

/**
 * The accessible name of an entry.
 * @param {string} source
 * @param {string} target
 * @returns {string}
 */
export function pairLabel(source, target) {
  return `${source} to ${target}`;
}

/**
 * Focuses the first element with the given data-testid (no-op when absent).
 * @param {string} id
 * @returns {boolean} whether something was focused
 */
export function focusTestId(id) {
  const node = document.querySelector(`[data-testid="${CSS.escape(id)}"]`);
  if (node instanceof HTMLElement) {
    node.focus();
    return true;
  }
  return false;
}

/**
 * An empty, space-free place for an optional element (see `present`).
 * @returns {HTMLElement}
 */
export function slot() {
  return h("div", { class: "out-slot" });
}

/**
 * Puts `node` into `place` when `on` is true, takes it out otherwise (cheap when nothing changes).
 * @param {HTMLElement} place  from `slot()`
 * @param {Node} node
 * @param {boolean} on
 */
export function present(place, node, on) {
  if (on && node.parentNode !== place) {
    place.replaceChildren(node);
  } else if (!on && node.parentNode === place) {
    node.remove();
  }
}

const inflight = new Set();

/**
 * Registers an edit that is still being checked (returns the same promise).
 * @template T
 * @param {Promise<T>} promise
 * @returns {Promise<T>}
 */
export function trackEdit(promise) {
  inflight.add(promise);
  const done = () => inflight.delete(promise);
  promise.then(done, done);
  return promise;
}

/**
 * Resolves when no tracked edit is in flight (edits made while waiting are waited for too).
 * @returns {Promise<void>}
 */
export async function editsSettled() {
  while (inflight.size > 0) {
    await Promise.allSettled(Array.from(inflight));
  }
}
