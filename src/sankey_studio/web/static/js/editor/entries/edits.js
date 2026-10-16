// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Pure rules of the entries table: what a category edit does to a draft, and what is allowed.
 * No DOM and no network, so every rule here can be exercised on plain objects.
 *
 * An entry is a (source, target) pair. A category edit goes through the edit engine (../edits/): the
 * server writes it into the data (manual links, pasted text, a file, a collection) when it can, and
 * what it cannot write stays in the graph as `transform.entry_categories` `{source, target,
 * category | null}`, one item per pair; `null` forces the pair uncategorised, even over a category
 * that comes with the data. `withCategory` below is that graph-only form.
 * Rules (`transform.category_rules`) are separate: a glob over node names.
 *
 * Every function returns NEW objects and never touches its input. The server stays the authority
 * (it canonicalises spelling and answers 422); the checks here only give a quicker, plainer answer.
 */

import { stripBidi } from "../../core/text.js";

export const CATEGORY_MAX = 100;
export const ENTRY_CATEGORIES_MAX = 20000;
export const RULES_MAX = 200;
export const PATTERN_MAX = 200;

const RESERVED = new Set(["uncategorized", "other"]);
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/;

/**
 * Normalises a typed category like the server (NFC, trimmed, inner whitespace collapsed).
 * @param {unknown} text
 * @returns {string}
 */
export function normalizeCategory(text) {
  return stripBidi(text ?? "").normalize("NFC").replace(/\s+/g, " ").trim();
}

/**
 * Checks a typed category. Empty means "no category" (a clear) and is fine.
 * @param {unknown} text
 * @returns {{ok: true, value: string | null} | {ok: false, message: string}}
 */
export function checkCategory(text) {
  const value = normalizeCategory(text);
  if (value === "") {
    return { ok: true, value: null };
  }
  if (RESERVED.has(value.toLowerCase())) {
    return { ok: false, message: `"${value}" is reserved for the chart (it labels the leftovers). Pick another name.` };
  }
  if (value.length > CATEGORY_MAX || CONTROL.test(value) || (value.isWellFormed && !value.isWellFormed())) {
    return { ok: false, message: value.length > CATEGORY_MAX ? `Category names can have at most ${CATEGORY_MAX} characters.` : "That category name contains characters that cannot be used." };
  }
  return { ok: true, value };
}

/**
 * The spelling already in use for `value` (names are compared ignoring case), else `value`.
 * @param {string} value
 * @param {string[]} known  `bundle.category_names`
 * @returns {string}
 */
export function canonicalCategory(value, known) {
  const key = value.toLowerCase();
  return known.find((name) => name.toLowerCase() === key) ?? value;
}

/**
 * True when categories of this draft live on the links of a manual source.
 * @param {{source?: {type?: string}}} draft
 * @returns {boolean}
 */
export function isManual(draft) {
  return draft?.source?.type === "manual";
}

function sameEntry(item, source, target) {
  return item.source === source && item.target === target;
}

/**
 * `entry_categories` with the pair set to `category` (replaced in place, else appended).
 * @param {{source: string, target: string, category: string | null}[]} list
 * @param {{source: string, target: string}} entry
 * @param {string | null} category
 * @returns {{source: string, target: string, category: string | null}[]}
 */
export function upsertEntry(list, entry, category) {
  const next = { source: entry.source, target: entry.target, category };
  const index = list.findIndex((item) => sameEntry(item, entry.source, entry.target));
  if (index < 0) {
    return [...list, next];
  }
  return list.map((item, at) => (at === index ? next : item));
}

/**
 * The draft after giving the pair `category` (null = none) as a graph-only edit.
 * @param {object} draft  `{source, transform, style}`
 * @param {{source: string, target: string}} entry
 * @param {string | null} category
 * @returns {object}
 */
export function withCategory(draft, entry, category) {
  const list = draft.transform?.entry_categories ?? [];
  return { ...draft, transform: { ...draft.transform, entry_categories: upsertEntry(list, entry, category) } };
}

/**
 * Why the edit cannot be made (too many individual entries), or null.
 * @param {object} draft
 * @param {{source: string, target: string}} entry
 * @returns {string | null}
 */
export function limitProblem(draft, entry) {
  if (isManual(draft)) {
    return null;
  }
  const list = draft.transform?.entry_categories ?? [];
  const known = list.some((item) => sameEntry(item, entry.source, entry.target));
  if (!known && list.length >= ENTRY_CATEGORIES_MAX) {
    return `You have set ${ENTRY_CATEGORIES_MAX.toLocaleString("en")} entries one by one, which is the limit. Use rules instead: search for the entries, then press "Categorise all entries matching this filter".`;
  }
  return null;
}

/**
 * Escapes the glob characters of `text` so they match themselves: `*` `?` `[` become `[*]` `[?]` `[[]`.
 * @param {string} text
 * @returns {string}
 */
export function escapeGlob(text) {
  return text.replace(/[*?[]/g, (char) => `[${char}]`);
}

/**
 * The rule that gives every entry whose source or target name contains `query` the category.
 * @param {string} query  the search text
 * @param {string} category  already checked
 * @returns {{match: "either", pattern: string, category: string}}
 */
export function ruleFor(query, category) {
  return { match: "either", pattern: `*${escapeGlob(query.trim())}*`, category };
}

/**
 * Why the rule cannot be added (empty search, pattern too long, too many rules, duplicate), or null.
 * @param {object} draft
 * @param {{pattern: string, category: string}} rule
 * @returns {string | null}
 */
export function ruleProblem(draft, rule) {
  const rules = draft.transform?.category_rules ?? [];
  if (rule.pattern === "**") {
    return "Type something in the search box first: the rule uses that text.";
  }
  if (rule.pattern.length > PATTERN_MAX) {
    return "That search text is too long for a rule. Use a shorter part of the name.";
  }
  if (rules.length >= RULES_MAX) {
    return `You have ${RULES_MAX} rules, which is the limit. Remove some rules first.`;
  }
  const same = rules.some((item) => item.match === "either" && item.pattern.toLowerCase() === rule.pattern.toLowerCase() && item.category.toLowerCase() === rule.category.toLowerCase());
  return same ? "That rule already exists." : null;
}

/**
 * The draft with a rule appended (last place: the first matching rule wins).
 * @param {object} draft
 * @param {object} rule
 * @returns {object}
 */
export function withRule(draft, rule) {
  return { ...draft, transform: { ...draft.transform, category_rules: [...(draft.transform?.category_rules ?? []), rule] } };
}

/**
 * The draft without the rule at `index`.
 * @param {object} draft
 * @param {number} index
 * @returns {object}
 */
export function withoutRule(draft, index) {
  const rules = (draft.transform?.category_rules ?? []).filter((_, at) => at !== index);
  return { ...draft, transform: { ...draft.transform, category_rules: rules } };
}

/**
 * The draft without the LAST rule equal to `rule` (used to undo a rule that was just added).
 * @param {object} draft
 * @param {{match: string, pattern: string, category: string}} rule
 * @returns {object}
 */
export function withoutRuleLike(draft, rule) {
  const rules = draft.transform?.category_rules ?? [];
  const same = (item) => item.match === rule.match && item.pattern === rule.pattern && item.category === rule.category;
  const index = rules.map(same).lastIndexOf(true);
  return index < 0 ? draft : withoutRule(draft, index);
}

function unescapeGlob(text) {
  return text.replace(/\[([*?[])]/g, "$1");
}

/**
 * Plain wording of a rule: `names containing "rent"`; unusual patterns are shown as written.
 * @param {{match: string, pattern: string}} rule
 * @returns {string}
 */
export function describeRule(rule) {
  const where = { source: "source names", target: "target names", either: "names" }[rule.match] ?? "names";
  const middle = rule.pattern.slice(1, -1);
  const simple = rule.pattern.length > 2 && rule.pattern.startsWith("*") && rule.pattern.endsWith("*") && escapeGlob(unescapeGlob(middle)) === middle;
  return simple ? `${where} containing "${unescapeGlob(middle)}"` : `${where} matching ${rule.pattern}`;
}

/**
 * Why "categorise all matching" would do nothing right now, or null. The search also looks at
 * categories but a rule only looks at names, so when the whole result is on screen and no source
 * or target name contains the text, the rule would change nothing.
 * @param {{phase: string, rows: {source: string, target: string}[], total: number}} state  the loader state
 * @param {string} query  the search text
 * @returns {string | null}
 */
export function bulkProblem(state, query) {
  const needle = query.trim().toLowerCase();
  if (state.phase !== "ready") {
    return null;
  }
  if (state.total === 0) {
    return "No entry matches this search, so a rule would do nothing.";
  }
  const whole = state.rows.length >= state.total;
  if (whole && !state.rows.some((row) => `${row.source}\n${row.target}`.toLowerCase().includes(needle))) {
    return `No source or target name contains "${query.trim()}" (the search also looks at categories), so a rule would do nothing.`;
  }
  return null;
}
