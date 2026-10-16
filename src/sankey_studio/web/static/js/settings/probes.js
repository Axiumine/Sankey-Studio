// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The two "test" requests of the settings page (both need write rights on the server).
 *
 * - `probeStorage(store)`: POST /settings/storage/test with the candidate settings (nothing is
 *   saved). The candidate is the draft, except that the limits come from the stored settings, so a
 *   half-typed limit can never fail a storage test.
 * - `probeConnection(store, row)`: a saved, unchanged connection uses POST
 *   /settings/mongo/{name}/test and reports the round trip in milliseconds. A new or edited one
 *   (including a typed connection string) is tested through the storage probe with the storage
 *   target forced to that connection, which answers ok/error without a latency.
 *
 * Both return `{ok: true, latency_ms}` or `{ok: false, invalid: true}` when the form still has
 * problems in the fields involved (they are made visible and the first one is focused), and throw
 * the `ApiError` of a failed request. An optional `AbortSignal` cancels the request (the form was
 * edited or the connection was deleted meanwhile): the call then rejects with the AbortError.
 */

import { api } from "../core/api.js";
import { formatCount } from "../core/format.js";
import { getTheme } from "../core/theme.js";
import { LIMITS } from "./constants.js";
import { buildBody } from "./model.js";
import { databaseProblem } from "./validate.js";

function candidate(store, target) {
  const { draft, settings } = store;
  const body = buildBody(draft, settings, getTheme());
  for (const spec of LIMITS) {
    body[spec.key] = settings[spec.key];
  }
  if (target) {
    const database = databaseProblem(draft.storage_database) ? settings.storage_database : draft.storage_database.trim();
    Object.assign(body, { storage_backend: "mongo", storage_connection: target, storage_database: database });
  }
  return body;
}

/**
 * The sentence a probe line switches to when the answer takes a while. A MongoDB server that
 * cannot be reached is given the stored `mongo_timeout_ms` before the probe gives up, so the line
 * names that wait. The probe always uses the stored value (`candidate` copies the limits from the
 * stored settings), never a half-edited one.
 * @param {import("./store.js").SettingsStore} store
 * @param {string} what  what is being tested, e.g. "the connection"
 * @param {boolean} mongo  whether the test talks to MongoDB
 * @returns {string}
 */
export function slowProbeText(store, what, mongo) {
  const base = `Still testing ${what}...`;
  const ms = Number(store.settings.mongo_timeout_ms);
  if (!mongo || !(ms > 0)) {
    return base;
  }
  const seconds = Math.max(1, Math.ceil(ms / 1000));
  return `${base} A MongoDB server that cannot be reached can take up to ${formatCount(seconds, "second")} to answer.`;
}

function blocked(store, wanted) {
  const ids = Object.keys(store.clientErrors()).filter(wanted);
  if (ids.length === 0) {
    return false;
  }
  for (const id of ids) {
    store.touch(id);
  }
  store.focus(ids[0]);
  return true;
}

/**
 * Tests the storage location the form describes.
 * @param {import("./store.js").SettingsStore} store
 * @param {AbortSignal} [signal]
 * @returns {Promise<{ok: boolean, invalid?: boolean}>}
 */
export async function probeStorage(store, signal) {
  if (blocked(store, (id) => id.startsWith("storage.") || id.startsWith("row."))) {
    return { ok: false, invalid: true };
  }
  await api.post("/settings/storage/test", candidate(store, null), { signal });
  return { ok: true };
}

function isSavedAsShown(row) {
  return row.previous_name !== null && row.previous_name === row.name.trim() && row.uri.trim() === "";
}

/**
 * Tests one connection row.
 * @param {import("./store.js").SettingsStore} store
 * @param {object} row
 * @param {AbortSignal} [signal]
 * @returns {Promise<{ok: boolean, invalid?: boolean, latency_ms?: number}>}
 */
export async function probeConnection(store, row, signal) {
  if (isSavedAsShown(row)) {
    const answer = await api.post(`/settings/mongo/${encodeURIComponent(row.previous_name)}/test`, undefined, { signal });
    return { ok: true, latency_ms: answer.latency_ms };
  }
  if (blocked(store, (id) => id.startsWith(`row.${row.key}.`))) {
    return { ok: false, invalid: true };
  }
  await api.post("/settings/storage/test", candidate(store, row.name.trim()), { signal });
  return { ok: true };
}
