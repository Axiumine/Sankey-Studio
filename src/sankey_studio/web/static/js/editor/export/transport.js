// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Fetches an export file: the saved graph's route or the draft's route.
 *
 * - `fetchExport({graphId, draft, query, signal})` -> `{blob, filename}`. With a `graphId` it is
 *   `GET /graphs/{id}/export`; without one it is `POST /export` with the draft as JSON body (the
 *   file is then named after the style title, `graph` without one). The panel passes `graphId` only
 *   for a saved graph with no unsaved edits, so the file always matches what is on screen.
 * - Both go through the app's one fetch wrapper (`api.blob`), so failures are `ApiError`s built
 *   from the error envelope, like everywhere else.
 */

import { api } from "../../core/api.js";
import { filenameFromDisposition } from "../../core/download.js";

/**
 * @param {{graphId?: string | null, draft: object, query: object, signal?: AbortSignal}} request
 * @returns {Promise<{blob: Blob, filename: string}>}
 */
export async function fetchExport({ graphId, draft, query, signal }) {
  const { blob, headers } = graphId
    ? await api.blob(`/graphs/${graphId}/export`, { query, signal })
    : await api.blob("/export", { method: "POST", json: draft, query, signal });
  return { blob, filename: filenameFromDisposition(headers.get("Content-Disposition"), "graph") };
}
