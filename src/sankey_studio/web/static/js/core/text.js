// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Text hygiene for user strings (graph names, categories, node names, file names, errors).
 *
 * Bidirectional control characters are invisible but change how the text AROUND them is drawn:
 * U+202E (right-to-left override) turns "report" + "gpj.exe" into "reportexe.jpg", and an
 * unclosed override or isolate bleeds into the badges, buttons and table cells that follow in the
 * same line. Nothing legitimate in a graph name needs them, so they are removed from every string
 * that reaches the page as text or as an attribute (see dom.js `h`, which calls this for you).
 * The harmless direction marks U+200E and U+200F are kept: they are used in real Arabic and
 * Hebrew text.
 *
 * Control characters (a bell, an escape, a stray NUL pasted into a name) have no glyph: the browser
 * draws each one as an empty "tofu" box. Names, tags and categories never need them, so they are
 * removed as well. Tab, line feed and carriage return are kept (they are white space the page
 * already collapses), and so are the format characters that real text uses (U+200B, U+00AD ...).
 *
 * Removed: U+202A-U+202E (embeddings and overrides), U+2066-U+2069 (isolates), and the control
 * characters U+0000-U+0008, U+000B, U+000C, U+000E-U+001F, U+007F-U+009F.
 */

const UNSEEN_CONTROLS = /[\u202A-\u202E\u2066-\u2069\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g;

/**
 * Returns `value` as a string without bidirectional embedding, override and isolate characters and
 * without control characters (except tab, line feed and carriage return).
 * Use it for any text you hand to `textContent`, `document.title` or an attribute yourself;
 * `h()` and `mount()` already do it.
 * @param {unknown} value
 * @returns {string}
 */
export function stripBidi(value) {
  return String(value).replace(UNSEEN_CONTROLS, "");
}
