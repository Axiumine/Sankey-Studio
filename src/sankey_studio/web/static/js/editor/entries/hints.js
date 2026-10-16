// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The donut-basis hint: categorised entries that the chosen donut basis leaves out.
 *
 * The donut basis (`style.donut.basis`) decides which links the donut counts: `all` every link,
 * `initial` only links that leave a starting node (a node nothing flows into), `terminal` only links
 * that arrive at an end node (a node nothing flows out of). A category on a middle entry is then
 * kept in the graph but does not show in the donut; people should be told, not left guessing.
 *
 * `basisHint(bundle, basis)` -> `{count, text}` or null. It reads the entries preview of the bundle
 * and only speaks when that preview holds every entry (`entries.length >= entries_total`), because
 * a partial list cannot tell a middle node from an end node. When the server itself reports
 * `donut_empty_reason === "basis_empty"` it always speaks.
 */

const WHAT = {
  initial: "the donut only counts entries that leave a starting node",
  terminal: "the donut only counts entries that arrive at an end node",
};

function ignoredCount(entries, basis) {
  const sources = new Set(entries.map((row) => row.source));
  const targets = new Set(entries.map((row) => row.target));
  return entries.filter((row) => {
    if (row.category == null) {
      return false;
    }
    return basis === "initial" ? targets.has(row.source) : sources.has(row.target);
  }).length;
}

/**
 * @param {{entries?: object[], entries_total?: number, donut_empty_reason?: string | null} | null} bundle
 * @param {string | undefined} basis  `all`, `initial` or `terminal`
 * @returns {{count: number, text: string} | null}
 */
export function basisHint(bundle, basis) {
  if (!bundle || !(basis in WHAT)) {
    return null;
  }
  const entries = bundle.entries ?? [];
  const complete = entries.length >= (bundle.entries_total ?? 0);
  const count = complete ? ignoredCount(entries, basis) : 0;
  const empty = bundle.donut_empty_reason === "basis_empty";
  if (count === 0 && !empty) {
    return null;
  }
  const subject = count > 0 ? `${count} categorised ${count === 1 ? "entry is" : "entries are"} not counted in the donut` : "No categorised entry is counted in the donut";
  return { count, text: `${subject}: ${WHAT[basis]}. Change the donut basis under Style to count the others.` };
}
