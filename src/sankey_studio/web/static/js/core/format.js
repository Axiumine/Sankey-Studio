// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Number, percent, byte and date formatting.
 *
 * Locale comes from `<html lang>` (English) or the browser; every function is total: a value that
 * is not a finite number gives an en dash ("–"), an invalid date too, and if Intl throws for
 * any reason the plain fallback formats are used, so output never depends on the platform
 * exploding. Fallbacks are deterministic (same input, same text).
 */

const DASH = "–";

function locale() {
  return document.documentElement.lang || navigator.language || "en";
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * Formats a number with grouping ("12,345.6").
 * @param {number} value
 * @param {{maximumFractionDigits?: number, minimumFractionDigits?: number, compact?: boolean}} [options]
 * @returns {string}
 */
export function formatNumber(value, options = {}) {
  if (!finite(value)) {
    return DASH;
  }
  const digits = options.maximumFractionDigits ?? 2;
  try {
    return new Intl.NumberFormat(locale(), {
      maximumFractionDigits: digits,
      minimumFractionDigits: options.minimumFractionDigits ?? 0,
      notation: options.compact ? "compact" : "standard",
    }).format(value);
  } catch {
    return String(Math.round(value * 10 ** digits) / 10 ** digits);
  }
}

/**
 * Formats a share (0.25 -> "25%"; 0.0123 with digits 1 -> "1.2%").
 * @param {number} share  fraction, 1 = 100%
 * @param {number} [digits]
 * @returns {string}
 */
export function formatPercent(share, digits = 1) {
  if (!finite(share)) {
    return DASH;
  }
  try {
    return new Intl.NumberFormat(locale(), {
      style: "percent",
      maximumFractionDigits: digits,
      minimumFractionDigits: 0,
    }).format(share);
  } catch {
    return `${(share * 100).toFixed(digits)}%`;
  }
}

/**
 * Formats a byte count ("1.5 MB", base 1024).
 * @param {number} bytes
 * @returns {string}
 */
export function formatBytes(bytes) {
  if (!finite(bytes) || bytes < 0) {
    return DASH;
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${formatNumber(value, { maximumFractionDigits: unit === 0 ? 0 : 1 })} ${units[unit]}`;
}

function parseDate(value) {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Formats an ISO date or Date ("Oct 10, 2026", with `time` also "7:47 PM").
 * @param {string | Date} value
 * @param {{time?: boolean}} [options]
 * @returns {string}
 */
export function formatDate(value, options = {}) {
  const date = parseDate(value);
  if (!date) {
    return DASH;
  }
  try {
    return new Intl.DateTimeFormat(locale(), {
      dateStyle: "medium",
      timeStyle: options.time ? "short" : undefined,
    }).format(date);
  } catch {
    return date.toISOString().slice(0, options.time ? 16 : 10).replace("T", " ");
  }
}

const STEPS = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/**
 * "3 days ago", "in 2 hours", "just now" (under a minute); older than a year falls back to the date.
 * @param {string | Date} value
 * @param {number} [now]  epoch milliseconds, for tests
 * @returns {string}
 */
export function formatRelative(value, now = Date.now()) {
  const date = parseDate(value);
  if (!date) {
    return DASH;
  }
  const seconds = Math.round((date.getTime() - now) / 1000);
  const step = STEPS.find(([, size]) => Math.abs(seconds) >= size);
  if (!step) {
    return "just now";
  }
  try {
    const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
    return rtf.format(Math.trunc(seconds / step[1]), step[0]);
  } catch {
    return formatDate(date);
  }
}

/**
 * "1 graph" / "3 graphs" (regular plural: add "s", or pass the plural form).
 * @param {number} count
 * @param {string} singular
 * @param {string} [plural]
 * @returns {string}
 */
export function formatCount(count, singular, plural = `${singular}s`) {
  return `${formatNumber(count, { maximumFractionDigits: 0 })} ${count === 1 ? singular : plural}`;
}
