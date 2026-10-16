// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The settings form as plain data, with no DOM: building a draft from the API answer, the
 * canonical snapshot used for dirty tracking, and the request body.
 *
 * Secrets: a connection row holds `uri` (what the user typed, in memory only) and the API's
 * `has_secret` / `uri_masked`. The snapshot only records WHETHER something was typed, never the
 * text, and `buildBody` is the one place that copies the typed value into a request.
 */

import { LIMITS } from "./constants.js";

let counter = 0;

/**
 * A page-unique key for a connection row (stable while the name is being edited).
 * @returns {string}
 */
export function newKey() {
  counter += 1;
  return `conn-${counter}`;
}

/**
 * A row for a connection the server already stores.
 * @param {{name: string, uri_masked?: string, has_secret?: boolean, default_database?: string | null}} conn
 * @returns {object}
 */
export function rowFromConnection(conn) {
  return {
    key: newKey(),
    name: conn.name,
    previous_name: conn.name,
    uri: "",
    has_secret: conn.has_secret === true,
    uri_masked: conn.uri_masked ?? "",
    default_database: conn.default_database ?? "",
  };
}

/**
 * An empty row for a connection that is being added.
 * @returns {object}
 */
export function blankRow() {
  return {
    key: newKey(),
    name: "",
    previous_name: null,
    uri: "",
    has_secret: false,
    uri_masked: "",
    default_database: "",
  };
}

/**
 * The editable draft for a `SettingsOut` answer.
 * @param {Record<string, any>} settings
 * @param {boolean} [migrate]  initial state of the "copy existing graphs" box
 * @returns {{storage_backend: string, storage_connection: string | null, storage_database: string,
 *   limits: Record<string, string>, connections: object[], migrate: boolean}}
 */
export function draftFromSettings(settings, migrate = true) {
  const connections = settings.mongo_connections.map(rowFromConnection);
  const active = connections.find((row) => row.name === settings.storage_connection);
  return {
    storage_backend: settings.storage_backend,
    storage_connection: active ? active.key : null,
    storage_database: settings.storage_database,
    limits: Object.fromEntries(LIMITS.map((spec) => [spec.key, String(settings[spec.key])])),
    connections,
    migrate,
  };
}

/**
 * The name of the connection a draft uses for storage, or null.
 * @param {{connections: object[], storage_connection: string | null}} draft
 * @returns {string | null}
 */
export function storageConnectionName(draft) {
  const row = draft.connections.find((item) => item.key === draft.storage_connection);
  return row ? row.name.trim() : null;
}

/**
 * Canonical text of everything the form edits, without any secret: two drafts with the same
 * snapshot would save the same settings. A typed connection string counts as a change but its
 * text is not part of the snapshot.
 * @param {ReturnType<typeof draftFromSettings>} draft
 * @returns {string}
 */
export function snapshot(draft) {
  const mongo = draft.storage_backend === "mongo";
  return JSON.stringify({
    backend: draft.storage_backend,
    connection: mongo ? storageConnectionName(draft) : null,
    database: mongo ? draft.storage_database.trim() : null,
    limits: LIMITS.map((spec) => draft.limits[spec.key].trim()),
    rows: draft.connections.map((row) => [
      row.name.trim(),
      row.previous_name,
      row.default_database.trim(),
      row.uri.length > 0,
    ]),
  });
}

/**
 * True when the storage target of the draft differs from the stored one (a switch). A new
 * connection string on the connection that holds the graphs counts: the server compares URIs.
 * @param {ReturnType<typeof draftFromSettings>} draft
 * @param {Record<string, any>} settings  the last `SettingsOut`
 * @returns {boolean}
 */
export function storageChanged(draft, settings) {
  if (draft.storage_backend !== settings.storage_backend) {
    return true;
  }
  if (draft.storage_backend === "file") {
    return false;
  }
  const active = draft.connections.find((row) => row.key === draft.storage_connection);
  return (
    storageConnectionName(draft) !== settings.storage_connection ||
    draft.storage_database.trim() !== settings.storage_database ||
    (active !== undefined && active.uri.trim() !== "")
  );
}

function rowBody(row) {
  const body = {
    name: row.name.trim(),
    previous_name: row.previous_name,
    default_database: row.default_database.trim() || null,
  };
  if (row.uri.trim() !== "") {
    body.uri = row.uri.trim();
  }
  return body;
}

/**
 * True when the stored settings are no longer what the page loaded: someone else (another window,
 * another person on a remote server) saved in the meantime. The theme is not compared, it is
 * saved on its own by the header switch; `bootstrap` never changes while the server runs.
 * @param {Record<string, any>} loaded  the last `SettingsOut` this page holds
 * @param {Record<string, any>} fresh  a `SettingsOut` fetched now
 * @returns {boolean}
 */
export function changedElsewhere(loaded, fresh) {
  const core = ({ theme, bootstrap, ...rest }) => JSON.stringify(rest);
  return core(loaded) !== core(fresh);
}

/**
 * The `SettingsIn` body for a draft. `fresh` is a recent `SettingsOut`: it supplies what the form
 * does not edit (`default_style`) and the stored storage database used while the backend is
 * "file" (the hidden Mongo fields are then not sent). The read-only `bootstrap` block and the
 * masked URIs are left out.
 * @param {ReturnType<typeof draftFromSettings>} draft
 * @param {Record<string, any>} fresh
 * @param {string} theme  the theme to store ("system", "light" or "dark")
 * @returns {Record<string, unknown>}
 */
export function buildBody(draft, fresh, theme) {
  const mongo = draft.storage_backend === "mongo";
  const body = {
    storage_backend: draft.storage_backend,
    storage_connection: mongo ? storageConnectionName(draft) : null,
    storage_database: mongo ? draft.storage_database.trim() : fresh.storage_database,
    mongo_connections: draft.connections.map(rowBody),
    theme,
    default_style: fresh.default_style,
  };
  for (const spec of LIMITS) {
    body[spec.key] = Number(draft.limits[spec.key].trim());
  }
  return body;
}
