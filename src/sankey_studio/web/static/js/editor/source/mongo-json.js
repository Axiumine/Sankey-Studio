/**
 * JSON editors for the Mongo filter (an object) and the aggregation pipeline (a list of stages).
 *
 * The text is checked in the browser as it is typed. Valid JSON of the right shape is written to
 * the store; anything else shows a message under the box and leaves the store (and the preview)
 * on the last valid value, so a half-typed brace never reaches the server. The server's own
 * checks (forbidden operators such as $out, $where) arrive later as field errors. A value that
 * the store changes from outside (a loaded graph) is written back as pretty-printed JSON.
 * Test ids: given by the caller (mongo-filter, mongo-pipeline).
 */

import { field, textArea } from "../../core/form.js";
import { getIn, sameJson } from "../meta/util.js";

const MAX_STAGES = 50;
const isPlainObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

/**
 * Checks a filter text. Empty means "no filter".
 * @param {string} text
 * @returns {{value?: object, error?: string}}
 */
export function checkFilter(text) {
  if (text.trim() === "") {
    return { value: {} };
  }
  let value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return { error: `This is not valid JSON yet: ${error.message}` };
  }
  return isPlainObject(value) ? { value } : { error: 'A filter is a JSON object, for example {"year": 2024}.' };
}

/**
 * Checks a pipeline text. Empty means "no stages".
 * @param {string} text
 * @returns {{value?: object[], error?: string}}
 */
export function checkPipeline(text) {
  if (text.trim() === "") {
    return { value: [] };
  }
  let value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return { error: `This is not valid JSON yet: ${error.message}` };
  }
  if (!Array.isArray(value) || !value.every(isPlainObject)) {
    return { error: 'A pipeline is a JSON list of stages, for example [{"$match": {"year": 2024}}].' };
  }
  return value.length > MAX_STAGES ? { error: `A pipeline can have at most ${MAX_STAGES} stages.` } : { value };
}

const SPECS = {
  filter: { check: checkFilter, empty: {}, rows: 5, placeholder: '{ "year": 2024 }', label: "Filter (JSON object)", hint: "Only documents that match are read. Leave empty to read every document." },
  pipeline: { check: checkPipeline, empty: [], rows: 8, placeholder: '[\n  { "$match": { "year": 2024 } },\n  { "$group": { "_id": { "source": "$from", "target": "$to" }, "value": { "$sum": "$amount" } } }\n]', label: "Aggregation pipeline (JSON list)", hint: "Each output document becomes one flow with the fields below. Write stages never run: the app only reads." },
};

/**
 * Builds the editor of `kind` ("filter" | "pipeline") bound to `draft.source.<kind>`.
 * @param {{store: object, kind: "filter"|"pipeline", testid: string}} options
 * @returns {{field: ReturnType<typeof field>, dispose: () => void}}
 */
export function createJsonEditor({ store, kind, testid }) {
  const spec = SPECS[kind];
  const path = ["draft", "source", kind];
  const control = textArea({ code: true, rows: spec.rows, wrap: "off", placeholder: spec.placeholder, "data-testid": testid });
  const f = field({ label: spec.label, control, hint: spec.hint });
  control.addEventListener("input", () => {
    const result = spec.check(control.value);
    f.setError(result.error ?? "");
    if (!result.error) {
      store.patch(path, result.value);
    }
  });
  const off = store.subscribe(
    (value) => {
      const typed = spec.check(control.value);
      if (typed.error || !sameJson(typed.value, value ?? spec.empty)) {
        control.value = sameJson(value ?? spec.empty, spec.empty) ? "" : JSON.stringify(value, null, 2);
        f.setError("");
      }
    },
    { select: (state) => getIn(state, path), immediate: true },
  );
  return { field: f, dispose: off };
}
