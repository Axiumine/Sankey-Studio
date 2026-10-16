// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Small pure helpers shared by the editor panels (meta, source, transform, style).
 *
 * Nothing here touches the DOM or the network, so every function can be reasoned about on its own.
 * Paths are arrays of keys ("draft", "style", "height") exactly as store.js takes them.
 */

import { stripBidi } from "../../core/text.js";

/**
 * Reads `path` (array of keys) from `value`; undefined when any step is missing.
 * @param {unknown} value
 * @param {(string|number)[]} path
 * @returns {any}
 */
export function getIn(value, path) {
  let node = value;
  for (const key of path) {
    if (node == null || typeof node !== "object") {
      return undefined;
    }
    node = node[key];
  }
  return node;
}

/**
 * Sorted unique non-empty strings (case-insensitive order), at most `limit`.
 * @param {Iterable<unknown>} values
 * @param {number} [limit]
 * @returns {string[]}
 */
export function uniqueSorted(values, limit = 500) {
  const seen = new Set();
  for (const value of values) {
    const text = typeof value === "string" ? value.trim() : "";
    if (text) {
      seen.add(text);
    }
  }
  const sorted = Array.from(seen).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  return sorted.slice(0, limit);
}

/**
 * Node names the preview knows about (from the entries preview of the last RenderBundle).
 * @param {{entries?: {source: string, target: string}[]} | null | undefined} bundle
 * @returns {string[]}
 */
export function knownNodeNames(bundle) {
  const names = [];
  for (const row of bundle?.entries ?? []) {
    names.push(row.source, row.target);
  }
  return uniqueSorted(names);
}

/**
 * Category names the preview knows about, plus `extra` (names typed in the editor).
 * @param {{category_names?: string[]} | null | undefined} bundle
 * @param {string[]} [extra]
 * @returns {string[]}
 */
export function knownCategories(bundle, extra = []) {
  return uniqueSorted([...(bundle?.category_names ?? []), ...extra]);
}

/**
 * Parses a decimal typed by a person ("1200", "1 200.5", "-3"); NaN when it is not a number.
 * Thousands separators are NOT guessed ("1,5" is ambiguous), so a comma gives NaN.
 * @param {string} text
 * @returns {number}
 */
export function parseNumber(text) {
  const clean = String(text).replace(/[\s ]/g, "");
  if (!/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(clean)) {
    return Number.NaN;
  }
  return Number(clean);
}

/** Plain-text message for a value out of range. */
function rangeMessage({ min, max, int }) {
  const kind = int ? "a whole number" : "a number";
  if (min != null && max != null) {
    return `Enter ${kind} from ${min} to ${max}.`;
  }
  if (min != null) {
    return `Enter ${kind} of ${min} or more.`;
  }
  if (max != null) {
    return `Enter ${kind} of ${max} or less.`;
  }
  return `Enter ${kind}.`;
}

/**
 * Checks a number against a range; returns an error message or "".
 * @param {number} n
 * @param {{min?: number, max?: number, int?: boolean}} range
 * @returns {string}
 */
export function checkRange(n, range) {
  const bad =
    !Number.isFinite(n) ||
    (range.int && !Number.isInteger(n)) ||
    (range.min != null && n < range.min) ||
    (range.max != null && n > range.max);
  return bad ? rangeMessage(range) : "";
}

/**
 * True when two JSON-like values are deeply equal (key order ignored for objects).
 * @param {unknown} a
 * @param {unknown} b
 * @returns {boolean}
 */
export function sameJson(a, b) {
  if (Object.is(a, b)) {
    return true;
  }
  if (a == null || b == null || typeof a !== "object" || typeof b !== "object") {
    return false;
  }
  if (Array.isArray(a) !== Array.isArray(b)) {
    return false;
  }
  const keysA = Object.keys(a);
  if (keysA.length !== Object.keys(b).length) {
    return false;
  }
  return keysA.every((key) => Object.hasOwn(b, key) && sameJson(a[key], b[key]));
}

/**
 * The reserved category names the renderer owns (any case, inner spaces collapsed).
 * @param {string} name
 * @returns {boolean}
 */
export function isReservedCategory(name) {
  const key = String(name).trim().replace(/\s+/g, " ").toLowerCase();
  return key === "uncategorized" || key === "other";
}

/**
 * Text safe for an `aria-label` or `title`: bidi controls removed, long text cut with an ellipsis.
 * @param {unknown} value
 * @param {number} [max]
 * @returns {string}
 */
export function labelText(value, max = 60) {
  const text = stripBidi(value ?? "");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/**
 * Length of `text` the way the server counts it: in characters (code points), not UTF-16 units, so
 * an emoji is one character. A loop, not `Array.from`: a 2,000,000 character paste is counted on
 * every keystroke.
 * @param {string} text
 * @returns {number}
 */
export function charCount(text) {
  let count = text.length;
  for (let i = 0; i < text.length - 1; i += 1) {
    const high = text.charCodeAt(i);
    const low = text.charCodeAt(i + 1);
    if (high >= 0xd800 && high <= 0xdbff && low >= 0xdc00 && low <= 0xdfff) {
      count -= 1; // a surrogate pair is one character
      i += 1;
    }
  }
  return count;
}

/**
 * The first `max` characters of `text` (code points).
 * @param {string} text
 * @param {number} max
 * @returns {string}
 */
export function clipText(text, max) {
  return Array.from(text).slice(0, max).join("");
}
