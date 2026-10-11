/**
 * Bundle import and export of the library.
 *
 * Export: `exportGraphs(ids)` downloads `GET /graphs/export?ids=` (a JSON bundle).
 *
 * Import: `startImport(file, {onDone})` reads the chosen file in the browser, checks that it looks
 * like a bundle (`{"format": "sankey-studio/graphs", "graphs": [...]}`), asks once ("Import N
 * graphs?"), posts it to `POST /graphs/import` and shows the ImportReport (how many arrived, how
 * many failed and why). The server always gives imported graphs NEW ids, so nothing already in
 * the library is replaced; the dialog says so. File names and error lines are text nodes.
 *
 * Test ids: import-dialog, import-confirm, import-report.
 */

import { api, reportError } from "../core/api.js";
import { openDialog } from "../core/dialog.js";
import { downloadExport } from "../core/download.js";
import { h } from "../core/dom.js";
import { formatBytes, formatCount } from "../core/format.js";
import { toast } from "../core/toast.js";

/** The server refuses import bodies over 16 MiB. */
export const IMPORT_LIMIT_BYTES = 16 * 1024 * 1024;

/**
 * Downloads a bundle of the given graphs.
 * @param {string[]} ids  1..200 graph ids
 * @returns {Promise<{filename: string, size: number}>}
 */
export function exportGraphs(ids) {
  return downloadExport("/graphs/export", { query: { ids }, fallbackName: "sankey-studio-graphs.json" });
}

/** Error with a sentence that is safe to show as is. */
class BundleProblem extends Error {}

/**
 * Reads and checks a bundle file.
 * @param {File} file
 * @returns {Promise<{graphs: unknown[]}>}
 */
export async function readBundle(file) {
  if (file.size > IMPORT_LIMIT_BYTES) {
    throw new BundleProblem(`This file is ${formatBytes(file.size)}. The server accepts bundles up to ${formatBytes(IMPORT_LIMIT_BYTES)}; export fewer graphs per file.`);
  }
  let data = null;
  try {
    data = JSON.parse(await file.text());
  } catch {
    throw new BundleProblem("This file is not valid JSON. Choose a bundle saved with Export.");
  }
  if (!data || typeof data !== "object" || !Array.isArray(data.graphs)) {
    throw new BundleProblem("This is not a Sankey Studio bundle. Choose a file saved with Export.");
  }
  if (data.graphs.length === 0) {
    throw new BundleProblem("This bundle holds no graphs, so there is nothing to import.");
  }
  return data;
}

function confirmBody(file, count) {
  const error = h("p", { class: "field-error", role: "alert", hidden: true });
  const body = h(
    "div",
    { class: "stack stack-sm" },
    h("p", null, h("span", { class: "text-strong" }, file.name), ` (${formatBytes(file.size)})`),
    h("p", null, `This bundle holds ${formatCount(count, "graph")}.`),
    h("p", { class: "text-muted" }, "Imported graphs always get new ids, so nothing in your library is replaced or overwritten. Graphs that cannot be read are skipped and listed afterwards."),
    error,
  );
  return { body, error, pending: null };
}

function reportBody(report) {
  const errors = (report.errors ?? []).map(String);
  return h(
    "div",
    { class: "stack stack-sm" },
    h("p", null, `Imported ${formatCount(report.imported, "graph")}.`),
    report.failed > 0 ? h("p", { class: "text-strong" }, `${formatCount(report.failed, "graph")} could not be imported.`) : null,
    errors.length > 0
      ? h("ul", { class: "import-errors", role: "list", "aria-label": "Import problems" }, errors.map((line) => h("li", null, line)))
      : null,
    report.failed > errors.length ? h("p", { class: "text-muted text-sm" }, `Only the first ${errors.length} problems are listed.`) : null,
  );
}

function showReport(report) {
  const title = report.imported > 0 ? "Import finished" : "Nothing was imported";
  return openDialog({
    title,
    body: reportBody(report),
    testid: "import-report",
    actions: [{ label: "Done", kind: "primary", value: true, initial: true }],
  }).result;
}

function importAction(bundle, parts) {
  return {
    label: "Import",
    kind: "primary",
    testid: "import-confirm",
    initial: true,
    async onClick(close) {
      if (parts.pending) {
        return;
      }
      parts.error.hidden = true;
      parts.pending = api.post("/graphs/import", bundle);
      try {
        await parts.pending;
        close(true);
      } catch (error) {
        parts.pending = null;
        parts.error.textContent = reportError(error)?.friendly ?? "Import failed.";
        parts.error.hidden = false;
      }
    },
  };
}

/** The import failed after its dialog was closed: tell the person, and carry on without a report. */
function reportAndDrop(error) {
  reportError(error, toast);
  return null;
}

async function runImport(file, onDone) {
  let bundle = null;
  try {
    bundle = await readBundle(file);
  } catch (error) {
    toast.error(error instanceof BundleProblem ? error.message : "That file could not be read.");
    return;
  }
  const parts = confirmBody(file, bundle.graphs.length);
  const dialog = openDialog({
    title: "Import graphs",
    body: parts.body,
    testid: "import-dialog",
    actions: [{ label: "Cancel", value: null }, importAction(bundle, parts)],
  });
  await dialog.result;
  // Esc during the request closes the dialog but the import still runs: report it all the same,
  // failure included (the inline message of the closed dialog is gone, so this one is a toast)
  const report = parts.pending ? await parts.pending.catch(reportAndDrop) : null;
  if (report) {
    onDone();
    await showReport(report);
  }
}

/**
 * Runs the whole import flow for a chosen file.
 * @param {File} file
 * @param {{onDone: () => void, returnFocus?: () => void}} options  onDone: called once the library
 *   changed (before the report is shown); returnFocus: called when the flow is over, whatever came
 *   of it, so keyboard users land back on the Import control and not on the document body
 * @returns {Promise<void>}
 */
export async function startImport(file, { onDone, returnFocus }) {
  try {
    await runImport(file, onDone);
  } finally {
    returnFocus?.();
  }
}
