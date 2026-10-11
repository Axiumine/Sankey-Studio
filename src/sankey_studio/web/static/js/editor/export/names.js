/**
 * File names of the editor's downloads: ONE code path for the server's files and the ones the
 * browser draws itself.
 *
 * The scheme: a Sankey file is named after the graph (`Budget.svg`), a donut file after the graph
 * plus `-donut` (`Budget-donut.svg`), so the two charts of one graph never share a name. The server
 * already follows it; `exportFileName` keeps it true for any server answer (an older server that
 * names both alike gets the suffix added, a newer one is left alone, so it is never doubled).
 *
 * `exportFileName({filename, chart, graphName, fromDraft})` -> the final name with extension.
 * - `filename`: what the server called the file (or `<title>.<ext>` for a browser-made image);
 * - `fromDraft`: the file comes from an unsaved or edited graph. POST /export has no graph name and
 *   calls the file `graph` without a style title, so then `graphName` stands in for it;
 * - bidirectional controls are removed and the name is cut so the extension always survives.
 * `stemOf(name)` -> the name without its extension (Plotly adds the extension of a browser image).
 */

import { cleanFilename } from "../../core/download.js";
import { stripBidi } from "../../core/text.js";

const DONUT_SUFFIX = "-donut";
const PLACEHOLDER = "graph";
const NAME_MAX = 150;

function clean(name) {
  return cleanFilename(stripBidi(name), PLACEHOLDER);
}

function split(filename) {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? { stem: filename.slice(0, dot), ext: filename.slice(dot) } : { stem: filename, ext: "" };
}

/**
 * @param {string} name
 * @returns {string}
 */
export function stemOf(name) {
  return split(name).stem;
}

/**
 * @param {{filename: string, chart: string, graphName?: string | null, fromDraft: boolean}} options
 * @returns {string}
 */
export function exportFileName({ filename, chart, graphName, fromDraft }) {
  const { stem, ext } = split(clean(filename));
  const donut = chart === "donut";
  const unnamed = fromDraft && Boolean(graphName?.trim()) && (stem === PLACEHOLDER || (donut && stem === `${PLACEHOLDER}${DONUT_SUFFIX}`));
  const base = unnamed ? clean(graphName) : stem;
  const suffix = donut && (unnamed || !base.endsWith(DONUT_SUFFIX)) ? DONUT_SUFFIX : "";
  const room = Math.max(1, NAME_MAX - ext.length - suffix.length);
  return `${base.slice(0, room)}${suffix}${ext}`;
}
