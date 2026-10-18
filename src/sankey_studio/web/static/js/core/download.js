// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Downloads.
 *
 * - `downloadExport(path, {query, signal, fallbackName})` fetches an attachment route through
 *   the API client (errors become ApiError, CSRF and content rules stay in one place), then saves
 *   it with an anchor `download` click. The file name comes from `Content-Disposition`
 *   (`filename*=UTF-8''...` first, then `filename="..."`) and wins as it is; without one the name is
 *   `fallbackName`, given the chart suffix by `chartFileName`.
 * - `isClientFallback(error)`: true when the server cannot draw the image (422 export_too_large,
 *   501/502/503/504): offer core/chart.js `downloadImage` instead (docs/api.md, section 3.2).
 * - `saveBlob(blob, filename)` and `downloadText(filename, text, mime)` save data that already
 *   exists in the browser.
 * - `exportHref(path, query)` is the URL of an export route for a plain `<a href>`.
 * - File names of the charts: the server names a Sankey `<name>.<ext>` and a donut
 *   `<name>-donut.<ext>`. `chartStem` and `chartFileName` apply the same rule to the names the
 *   browser has to make itself (no `Content-Disposition`, or an image drawn by Plotly), once: a
 *   name that already ends in `-donut` is left alone, so the server's name never doubles up.
 * Names are cleaned: no path separators, no control or bidirectional characters, at most 150
 * characters.
 */

import { API_BASE, api, buildQuery } from "./api.js";
import { h } from "./dom.js";
import { stripBidi } from "./text.js";

const FALLBACK_STATUS = new Set([501, 502, 503, 504]);

/**
 * Makes a file name safe: no directories (a slash or backslash becomes a hyphen, so "Budget 2024/25"
 * keeps both halves), no control characters, never empty.
 * @param {string} name
 * @param {string} [fallback]
 * @returns {string}
 */
export function cleanFilename(name, fallback = "download") {
  const base = stripBidi(name).replace(/[\\/]+/g, "-").replace(/[\u0000-\u001f\u007f"<>:|?*]/g, "").trim();
  return (base || fallback).slice(0, 150);
}

/**
 * The file name in a Content-Disposition header value.
 * @param {string | null} header
 * @param {string} [fallback]
 * @returns {string}
 */
export function filenameFromDisposition(header, fallback = "download") {
  const value = header ?? "";
  const star = /filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i.exec(value);
  if (star) {
    try {
      return cleanFilename(decodeURIComponent(star[2].trim()), fallback);
    } catch {
      // malformed escape: fall through to the plain filename
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(value);
  return plain ? cleanFilename(plain[1], fallback) : fallback;
}

/**
 * Starts a browser download of `blob`.
 * @param {Blob} blob
 * @param {string} filename
 */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = h("a", { href: url, download: cleanFilename(filename), hidden: true });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/**
 * The name of a chart file without its extension: `Budget` stays `Budget` for the Sankey and
 * becomes `Budget-donut` for the donut (already ending in `-donut`: unchanged). A Sankey and a
 * donut of one graph therefore never share a name.
 * @param {string} stem
 * @param {string} [chart]  "sankey" or "donut"
 * @returns {string}
 */
export function chartStem(stem, chart) {
  return chart === "donut" && !stem.endsWith("-donut") ? `${stem}-donut` : stem;
}

/**
 * `chartStem` for a name with an extension (`Budget.svg` -> `Budget-donut.svg` for the donut).
 * @param {string} filename
 * @param {string} [chart]  "sankey" or "donut"
 * @returns {string}
 */
export function chartFileName(filename, chart) {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? `${chartStem(filename.slice(0, dot), chart)}${filename.slice(dot)}` : chartStem(filename, chart);
}

/**
 * Saves text produced in the browser.
 * @param {string} filename
 * @param {string} text
 * @param {string} [mime]
 */
export function downloadText(filename, text, mime = "text/plain") {
  saveBlob(new Blob([text], { type: `${mime};charset=utf-8` }), filename);
}

/**
 * Downloads an export route (attachment) through the API client.
 * @param {string} path  such as `/graphs/<id>/export`
 * @param {{query?: object, signal?: AbortSignal, fallbackName?: string, chart?: string}} [options]  `chart` "donut" adds `-donut` to `fallbackName` (the server's own name is kept as it is)
 * @returns {Promise<{filename: string, size: number}>}
 */
export async function downloadExport(path, options = {}) {
  const { blob, headers } = await api.blob(path, { query: options.query, signal: options.signal });
  const served = filenameFromDisposition(headers.get("Content-Disposition"), "");
  const filename = served || chartFileName(cleanFilename(options.fallbackName ?? "download"), options.chart);
  saveBlob(blob, filename);
  return { filename, size: blob.size };
}

/**
 * True when a failed image export should fall back to the client-side download.
 * @param {unknown} error
 * @returns {boolean}
 */
export function isClientFallback(error) {
  const code = error?.code;
  return code === "export_too_large" || FALLBACK_STATUS.has(error?.status);
}

/**
 * URL of an API route with a query, for `<a href>` (same origin, root-relative).
 * @param {string} path
 * @param {object} [query]
 * @returns {string}
 */
export function exportHref(path, query) {
  return `${API_BASE}${path}${buildQuery(query)}`;
}
