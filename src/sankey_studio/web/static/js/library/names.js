/**
 * Names that can be shown.
 *
 * A graph name made only of control or bidirectional characters (a bell, an escape, a right-to-left
 * override) is not empty for the server, but once `core/text.js` `stripBidi` has removed them there
 * is nothing left to draw: a card link with no height, a heading with no text, `Select “” to
 * compare`. Every page that shows a graph therefore passes the name through `displayName` (or the
 * whole summary through `withDisplayName`) where it enters the page, and shows "Untitled graph"
 * when nothing visible remains. White space and invisible format characters (zero-width space, the
 * direction marks) count as nothing too.
 */

import { stripBidi } from "../core/text.js";

/** What a graph with no visible name is called. */
export const UNTITLED = "Untitled graph";

const INVISIBLE = /[\s\p{Cf}]/gu;

/**
 * True when `text` has at least one character that can be seen once control characters are gone.
 * @param {unknown} text
 * @returns {boolean}
 */
export function isShown(text) {
  return stripBidi(text ?? "").replace(INVISIBLE, "") !== "";
}

/**
 * The name to draw for a graph: the name without control characters, or "Untitled graph".
 * @param {unknown} name
 * @returns {string}
 */
export function displayName(name) {
  return isShown(name) ? stripBidi(name) : UNTITLED;
}

/** What a collection with no visible name is called (the no-script list of the server says the same). */
export const UNTITLED_FOLDER = "Untitled collection";

/**
 * The name to draw for a collection: the name without control characters, or "Untitled collection".
 * @param {unknown} name
 * @returns {string}
 */
export function folderLabel(name) {
  return isShown(name) ? stripBidi(name) : UNTITLED_FOLDER;
}

/**
 * A copy of a graph summary whose `name` can be shown and whose tags are all visible.
 * @template {{name?: string, tags?: string[]}} T
 * @param {T} graph
 * @returns {T}
 */
export function withDisplayName(graph) {
  const copy = { ...graph, name: displayName(graph.name) };
  if (Array.isArray(graph.tags)) {
    copy.tags = graph.tags.filter(isShown);
  }
  return copy;
}
