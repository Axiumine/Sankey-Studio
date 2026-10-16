// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The two server calls of the engine and the one-sentence text of a failure.
 *
 * `plan(api, draft, edit)` -> `EditOutcome` (POST /edits/plan: pure, writes nothing).
 * `write(api, draft, edit)` -> `EditOutcome` (POST /edits/write: needs the saved consent in
 * `draft.source.write_back`). Both are `quiet` (no busy bar): the engine reports its own result.
 */

import { fieldErrors } from "../../core/api.js";

const NOISE = /^(Value error|Assertion failed),\s*/;

/**
 * @param {{post: Function}} api
 * @param {object} draft
 * @param {object} edit
 * @returns {Promise<object>}
 */
export function plan(api, draft, edit) {
  return api.post("/edits/plan", { draft, edit }, { quiet: true });
}

/**
 * @param {{post: Function}} api
 * @param {object} draft
 * @param {object} edit
 * @returns {Promise<object>}
 */
export function write(api, draft, edit) {
  return api.post("/edits/write", { draft, edit }, { quiet: true });
}

/**
 * One sentence for a failed request.
 * @param {unknown} error
 * @returns {string}
 */
export function problemText(error) {
  const first = error?.details?.length ? fieldErrors(error)[0] : null;
  if (first?.message) {
    return `The server did not accept that: ${first.message.replace(NOISE, "")}`;
  }
  return error?.friendly ?? error?.message ?? "The change could not be checked.";
}
