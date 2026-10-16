// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Wraps a long chart title so it fits the width of its container.
 *
 * Plotly draws a title on one line and cuts it at the edge of the figure. The server sends the
 * title already escaped (`&lt;`, `&gt;`, `&amp;`), and Plotly reads `<br>` as a line break, so the
 * only thing this module ever adds is `<br>`. It works on the shown text only:
 *
 * - words are kept whole; a word that is longer than a line is broken between characters, never
 *   inside an HTML entity (`&lt;` is one character) and never between a letter and its accents or
 *   inside an emoji sequence;
 * - the width of a character is an estimate in em (0.55 on average, narrower for `i`, `l`, `.`,
 *   wider for capitals, `m`, `w` and full-width characters), so the line length follows the text
 *   and the font size, not a fixed count of characters;
 * - nothing here reads the page: `wrapTitle` and `titleFit` are pure functions.
 *
 * `titleFit` also says how much taller the top margin must be for the extra lines, so the plot
 * area moves down and nothing overlaps the title. Only the client changes: the server figure and
 * the server-side exports keep the title as it is.
 */

/** Font size of a Plotly title when the figure does not set one. */
export const DEFAULT_TITLE_PX = 17;
/** Plotly's line height for multi-line text, in em. */
export const LINE_HEIGHT = 1.3;
const DEFAULT_MARGIN_TOP = 100; // Plotly's own default
const DEFAULT_GUTTER = 16; // room kept free at the right edge when the figure sets no margin
const MIN_LINE_EM = 6;
const SPACE_EM = 0.3;
const AVERAGE_EM = 0.55;
const ENTITY_EM = 0.6;
const BREAK_TAG = /<br\s*\/?>/i;

// One shown character: an HTML entity, a flag (two regional indicators), or a code point with its
// combining marks, skin tone and the parts joined to it by a zero width joiner (emoji sequences).
const PART = String.raw`(?:\p{M}|[\u{1f3fb}-\u{1f3ff}])*`;
const ATOM = new RegExp(String.raw`&(?:#\d{1,7}|#x[\da-f]{1,6}|[a-z][a-z\d]{1,31});|[\u{1f1e6}-\u{1f1ff}]{2}|[^]${PART}(?:\u200d[^]${PART})*`, "giu");
const WIDTHS = [
  [/^[\p{scx=Han}\p{scx=Hiragana}\p{scx=Katakana}\p{scx=Hangul}\p{Extended_Pictographic}]/u, 1.05],
  [/^[mwMW@%]/, 0.9],
  [/^\p{Lu}/u, 0.68],
  [/^[iljtf.,:;'!|()[\]]/, 0.32],
];

function atomEm(atom) {
  if (atom.length > 2 && atom.startsWith("&") && atom.endsWith(";")) {
    return ENTITY_EM;
  }
  return WIDTHS.find(([pattern]) => pattern.test(atom))?.[1] ?? AVERAGE_EM;
}

function measure(atoms) {
  return atoms.reduce((sum, atom) => sum + atomEm(atom), 0);
}

/** Breaks one word that is longer than a line between its characters. */
function breakWord(atoms, maxEm) {
  const lines = [];
  let line = "";
  let used = 0;
  for (const atom of atoms) {
    const em = atomEm(atom);
    if (line && used + em > maxEm) {
      lines.push(line);
      line = "";
      used = 0;
    }
    line += atom;
    used += em;
  }
  return { lines, rest: line, used };
}

function wrapSegment(text, maxEm) {
  const lines = [];
  let line = "";
  let used = 0;
  const close = () => {
    if (line) {
      lines.push(line);
    }
    line = "";
    used = 0;
  };
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const atoms = word.match(ATOM) ?? [];
    const em = measure(atoms);
    if (line && used + SPACE_EM + em <= maxEm) {
      line += ` ${word}`;
      used += SPACE_EM + em;
      continue;
    }
    close();
    if (em <= maxEm) {
      line = word;
      used = em;
      continue;
    }
    const broken = breakWord(atoms, maxEm);
    lines.push(...broken.lines);
    ({ rest: line, used } = broken);
  }
  close();
  return lines;
}

/**
 * Inserts `<br>` into `text` so each line fits `width`.
 * @param {string} text  the title as Plotly gets it (already escaped; a `<br>` in it stays a break)
 * @param {{width: number, fontSize?: number}} options  `width` in px, `fontSize` in px (default 17)
 * @returns {{text: string, lines: number}} the same `text` when it fits on one line
 */
export function wrapTitle(text, { width, fontSize = DEFAULT_TITLE_PX }) {
  const maxEm = Math.max(width / fontSize, MIN_LINE_EM);
  const lines = text.split(BREAK_TAG).flatMap((segment) => wrapSegment(segment, maxEm));
  if (lines.length <= 1) {
    return { text, lines: 1 };
  }
  return { text: lines.join("<br>"), lines: lines.length };
}

/**
 * The title text and the top margin a layout needs in a container `width` px wide.
 * @param {{title?: object | string, margin?: {t?: number, r?: number}}} layout  the figure's layout, title unwrapped
 * @param {number} width  container width in px (0 or less: nothing to fit, null)
 * @returns {{text: string, marginTop: number, lines: number} | null} null when there is no title
 */
export function titleFit(layout, width) {
  const title = layout?.title;
  const text = typeof title === "string" ? title : title?.text;
  if (typeof text !== "string" || text === "" || !(width > 0)) {
    return null;
  }
  const size = title?.font?.size;
  const fontSize = Number.isFinite(size) && size > 0 ? size : DEFAULT_TITLE_PX;
  const gutter = (title?.pad?.l ?? 0) + (layout.margin?.r ?? DEFAULT_GUTTER);
  const wrapped = wrapTitle(text, { width: width - gutter, fontSize });
  const top = layout.margin?.t ?? DEFAULT_MARGIN_TOP;
  return { text: wrapped.text, marginTop: top + (wrapped.lines - 1) * Math.ceil(fontSize * LINE_HEIGHT), lines: wrapped.lines };
}

/**
 * Wraps the title of `layout` in place and grows `margin.t` for the extra lines. A title that fits
 * on one line leaves the layout untouched.
 * @param {object} layout  a copy of the figure's layout
 * @param {number} width  container width in px
 * @returns {{text: string, marginTop: number, lines: number} | null} what was applied, or null
 */
export function wrapLayoutTitle(layout, width) {
  const fit = titleFit(layout, width);
  if (!fit || fit.lines < 2) {
    return fit;
  }
  layout.title = { ...(typeof layout.title === "string" ? {} : layout.title), text: fit.text };
  layout.margin = { ...layout.margin, t: fit.marginTop };
  return fit;
}
