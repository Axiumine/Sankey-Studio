/**
 * Server errors of the settings routes mapped onto form fields.
 *
 * A 422 carries `details` such as `body.max_links: Input should be greater than or equal to 100`
 * or `mongo_connections.0.uri: Value error, uri must start with mongodb://...` (API.md section
 * 2.4). `mapServerError` turns them into `{fields: {id: message}, general: [message]}` with the
 * field ids of validate.js; a detail it cannot place goes to `general`. Other failures (503
 * busy, 503 storage_error, 403 read-only, network) are general messages.
 */

import { fieldErrors } from "../core/api.js";
import { LIMITS } from "./constants.js";

const LIMIT_KEYS = new Set(LIMITS.map((spec) => spec.key));
const ROW_PARTS = { uri: "uri", name: "name", previous_name: "name", default_database: "database" };
const NEEDS_URI = /Connection '([^']+)' needs a connection string/;

const REWRITES = [
  [/storage_backend 'mongo' needs storage_connection naming a connection/i, "Choose the connection that holds your graphs"],
  [/mongo connection names must be unique/i, "Connection names must be unique"],
  [/^uri\b/i, "The connection string"],
];

/**
 * Cleans a pydantic message for people: no "Value error, " prefix, the field jargon of the server
 * replaced, first letter capitalised, a full stop at the end.
 * @param {string} message
 * @returns {string}
 */
export function tidyMessage(message) {
  let text = message.replace(/^Value error,\s*/i, "").trim();
  for (const [pattern, replacement] of REWRITES) {
    text = text.replace(pattern, replacement);
  }
  if (text === "") {
    return "This value is not accepted.";
  }
  const sentence = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`;
}

function rowField(draft, index, part) {
  const row = draft.connections[Number(index)];
  return row && ROW_PARTS[part] ? `row.${row.key}.${ROW_PARTS[part]}` : null;
}

function fieldFor(item, draft) {
  const [head, second, third] = item.path;
  if (LIMIT_KEYS.has(head)) {
    return `limits.${head}`;
  }
  if (head === "storage_database") {
    return "storage.database";
  }
  if (head === "storage_connection" || head === "storage_backend") {
    return "storage.connection";
  }
  if (head === "mongo_connections" && /^\d+$/.test(second ?? "")) {
    return rowField(draft, second, third);
  }
  return fieldForText(item.message, draft);
}

function fieldForText(message, draft) {
  const needs = NEEDS_URI.exec(message);
  if (needs) {
    const row = draft.connections.find((item) => item.name.trim() === needs[1]);
    return row ? `row.${row.key}.uri` : null;
  }
  if (/storage_connection/.test(message)) {
    return "storage.connection";
  }
  return /names must be unique/.test(message) ? "connections" : null;
}

/** What a save that copies the graphs can do about an unreachable store. */
const COPY_HINT = 'To switch without copying your existing graphs, untick "Copy my existing graphs" and save again.';

/**
 * Maps an `ApiError` onto the form. `copying` says that the failed save asked to copy the
 * existing graphs: a storage that cannot be reached then also gets the way out (switch without
 * copying).
 * @param {import("../core/api.js").ApiError} error
 * @param {ReturnType<typeof import("./model.js").draftFromSettings>} draft
 * @param {{copying?: boolean}} [options]
 * @returns {{fields: Record<string, string>, general: string[]}}
 */
export function mapServerError(error, draft, options = {}) {
  const out = { fields: {}, general: [] };
  const items = error.status === 422 ? fieldErrors(error) : [];
  for (const item of items) {
    const id = fieldFor(item, draft);
    if (id && !out.fields[id]) {
      out.fields[id] = tidyMessage(item.message);
    } else if (!id) {
      out.general.push(tidyMessage(item.message));
    }
  }
  if (out.general.length === 0 && Object.keys(out.fields).length === 0) {
    const message = probeMessage(error);
    const stuck = options.copying && error.code === "storage_error";
    out.general.push(stuck ? `${/[.!?]$/.test(message) ? message : `${message}.`} ${COPY_HINT}` : message);
  }
  return out;
}

/**
 * The sentence a failed probe or save shows: its own wording for the codes that need it, the
 * first problem of a 422 without its field location, the server's message otherwise.
 * @param {import("../core/api.js").ApiError} error
 * @returns {string}
 */
export function probeMessage(error) {
  if (error.code === "busy") {
    return "Too many tests are running at the moment. Try again in a few seconds.";
  }
  if (error.readOnly) {
    return "This server is read-only, so it cannot test or change settings.";
  }
  if (error.status === 422) {
    return tidyMessage(fieldErrors(error)[0]?.message ?? error.message);
  }
  return error.friendly;
}
