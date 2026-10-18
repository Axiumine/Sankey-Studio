// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Early checks of the settings draft, so the form can say what is wrong before a request is made.
 * They mirror the server rules (docs/api.md, section 5.5); the server stays the authority and
 * its 422 answers are mapped onto the same field ids (errors.js).
 *
 * Field ids: `limits.<key>`, `storage.connection`, `storage.database`, and for a connection row
 * `row.<key>.name`, `row.<key>.database`, `row.<key>.uri`.
 */

import { formatNumber } from "../core/format.js";
import {
  DB_FORBIDDEN, DB_NAME_MAX, LIMITS, MAX_CONNECTIONS, NAME_PATTERN, SYSTEM_DATABASES, URI_CONTROL,
  URI_PREFIX,
} from "./constants.js";

/**
 * The problem with one number setting, or "".
 * @param {string} text  the raw input value
 * @param {{min: number, max: number}} spec
 * @returns {string}
 */
export function limitProblem(text, spec) {
  const value = text.trim();
  const range = `${formatNumber(spec.min)} to ${formatNumber(spec.max)}`;
  if (!/^\d+$/.test(value)) {
    return `Enter a whole number from ${range}.`;
  }
  const number = Number(value);
  return number < spec.min || number > spec.max ? `Enter a whole number from ${range}.` : "";
}

/**
 * The problem with a MongoDB database name, or "".
 * @param {string} name
 * @returns {string}
 */
export function databaseProblem(name) {
  const value = name.trim();
  if (value === "") {
    return "Enter a database name.";
  }
  if (value.length > DB_NAME_MAX) {
    return `Use at most ${DB_NAME_MAX} characters.`;
  }
  if (DB_FORBIDDEN.test(value)) {
    return "A database name cannot contain spaces or any of / \\ . \" $ * < > : | ?";
  }
  if (SYSTEM_DATABASES.includes(value.toLowerCase())) {
    return "The admin, local and config databases are not available.";
  }
  return "";
}

function nameProblem(row, draft) {
  const name = row.name.trim();
  if (name === "") {
    return "Give the connection a name.";
  }
  if (!NAME_PATTERN.test(name) || /^\.+$/.test(name)) {
    return "Use 1 to 64 letters, digits, dots, dashes or underscores (not only dots).";
  }
  const twin = draft.connections.some((other) => other !== row && other.name.trim() === name);
  return twin ? "Another connection already has this name." : "";
}

function uriProblem(row) {
  const uri = row.uri.trim();
  if (uri === "") {
    return row.has_secret ? "" : "Enter the connection string.";
  }
  if (!URI_PREFIX.test(uri)) {
    return "A connection string starts with mongodb:// or mongodb+srv://.";
  }
  return URI_CONTROL.test(uri) ? "The connection string contains a control character." : "";
}

function rowProblems(row, draft) {
  const found = {
    [`row.${row.key}.name`]: nameProblem(row, draft),
    [`row.${row.key}.uri`]: uriProblem(row),
    [`row.${row.key}.database`]: row.default_database.trim() ? databaseProblem(row.default_database) : "",
  };
  return Object.entries(found).filter(([, message]) => message);
}

function storageProblems(draft) {
  if (draft.storage_backend !== "mongo") {
    return [];
  }
  const found = [];
  if (!storageRowExists(draft)) {
    found.push(["storage.connection", "Choose the connection that holds the graphs."]);
  }
  const database = databaseProblem(draft.storage_database);
  if (database) {
    found.push(["storage.database", database]);
  }
  return found;
}

function storageRowExists(draft) {
  const row = draft.connections.find((item) => item.key === draft.storage_connection);
  return Boolean(row) && row.name.trim() !== "";
}

/**
 * Every problem of a draft as `{id: message}` (empty object when it can be saved).
 * @param {ReturnType<typeof import("./model.js").draftFromSettings>} draft
 * @returns {Record<string, string>}
 */
export function validateDraft(draft) {
  const found = [];
  for (const spec of LIMITS) {
    const message = limitProblem(draft.limits[spec.key], spec);
    if (message) {
      found.push([`limits.${spec.key}`, message]);
    }
  }
  found.push(...storageProblems(draft));
  for (const row of draft.connections) {
    found.push(...rowProblems(row, draft));
  }
  if (draft.connections.length > MAX_CONNECTIONS) {
    found.push(["connections", `At most ${MAX_CONNECTIONS} connections.`]);
  }
  return Object.fromEntries(found);
}
