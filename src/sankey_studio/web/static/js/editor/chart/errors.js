/**
 * Plain-English wording for a failed preview (`store.status.error` is `{status, code, message,
 * details}` from the API envelope). The chart panel shows it where the chart would be.
 *
 * `isTransient(error)` is true for failures that may pass by themselves (server unreachable, busy,
 * store down, 5xx): the chart offers "Try again" for those only; a bad setting needs an edit instead.
 *
 * `describePreviewError(error)` -> `{title, message, details}`. Field problems (`validation_error`)
 * are shown next to their fields by the form panels, so the chart only points there; a lost
 * connection or a busy server gets a sentence of its own (the server's text would only repeat the
 * title); everything else repeats the server's sentence, which already names the row, column or cycle.
 *
 * `previewError(error)` -> the error when the preview raised it, else null. The save bar also writes
 * a 422 to `status.error` (tagged `source: "save"`) so the form panels can mark the fields; that is
 * no reason to say the chart is out of date.
 */

const TITLES = {
  source_error: "The data could not be read",
  graph_build_error: "The graph could not be built",
  graph_too_large: "This graph is too large to draw",
  validation_error: "Some settings need fixing",
  source_not_found: "The data source was not found",
  network_error: "The server cannot be reached",
  busy: "The server is busy",
  storage_error: "The data store is not reachable",
};
// The server's own text for these only restates the title ("The server cannot be reached. Cannot
// reach the server. ..."), so the line under the title says what to do instead.
const PLAIN_MESSAGES = {
  network_error: "Check that Sankey Studio is still running, then try again.",
  busy: "Another request is still running. Try again in a moment.",
};
const MAX_DETAILS = 4;
// The server names settings and fields as the API does; the person sees the labels of the form.
const LOOP_HINT = /Set on_cycle to 'break' to drop the links that close it\.?/;
const LOOP_FIX = 'To draw it anyway, set "If the links form a loop" to "Drop the links that close the loop".';
const UNMATCHED = /^(\d+) entry_categories matched no entry$/;

/**
 * The server's sentence for an error or a warning, with field names put into the words of the form.
 * @param {string} text
 * @returns {string}
 */
export function plainText(text) {
  const unmatched = UNMATCHED.exec(text);
  if (unmatched) {
    return unmatched[1] === "1" ? "1 category you set in the entries table no longer matches an entry, so it is ignored." : `${unmatched[1]} categories you set in the entries table no longer match an entry, so they are ignored.`;
  }
  return text.replace(LOOP_HINT, LOOP_FIX);
}

/**
 * @param {{code?: string, message?: string, details?: string[]}} error
 * @returns {{title: string, message: string, details: string[]}}
 */
export function describePreviewError(error) {
  const code = error?.code ?? "";
  const title = TITLES[code] ?? "The preview failed";
  if (code === "validation_error") {
    return { title, message: "Fix the highlighted settings and the chart updates by itself.", details: [] };
  }
  const details = (error?.details ?? []).slice(0, MAX_DETAILS).map(plainText);
  return { title, message: PLAIN_MESSAGES[code] ?? plainText(error?.message || "The preview could not be built."), details };
}

/**
 * @param {{source?: string} | null | undefined} error  `status.error`
 * @returns {object | null}
 */
export function previewError(error) {
  return error && error.source !== "save" ? error : null;
}

const TRANSIENT = new Set(["network_error", "busy", "storage_error", "internal_error"]);

/**
 * @param {{code?: string, status?: number} | null} error
 * @returns {boolean}
 */
export function isTransient(error) {
  return Boolean(error) && (TRANSIENT.has(error.code ?? "") || (error.status ?? 0) >= 500 || error.status === 0);
}
