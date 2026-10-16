// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Data of the library collections (the API and the code call them folders): the five calls and the
 * index the page builds from the list.
 *
 * `buildIndex(items)` turns the list of `FolderSummary` records (`GET /folders`, or the boot data)
 * into lookups that never loop and never throw, whatever the records say: a folder whose parent is
 * not in the list is read as a top-level one, and a cycle (A below B and B below A, which two racing
 * moves can leave behind) is cut where the first walk over the list comes back on itself (the same
 * folder every time for the same list), so every folder is reachable from the top and `pathOf`,
 * `descendantsOf` and `heightOf` always finish.
 *
 *   index.childrenOf(id)     folders directly inside `id` (`null` = the top level), list order
 *   index.pathOf(id)         the folders from the top down to `id`, itself last; [] for an unknown id
 *   index.depthOf(id)        levels down to `id`: 0 for the top level and for an unknown id, 1 for a top folder
 *   index.heightOf(id)       levels of the tree that starts at `id`: 1 for a folder with no folder inside
 *   index.descendantsOf(id)  every folder below `id` (not `id` itself)
 */

import { api } from "../core/api.js";

/** Most levels a collection may be nested (the server refuses a ninth). */
export const DEPTH_MAX = 8;
/** Most collections the server stores. */
export const FOLDERS_MAX = 1000;
/** Longest collection name the server accepts. */
export const LABEL_MAX = 100;

/**
 * Where each folder sits after dangling parents became the top level and cycles were cut.
 * @param {{id: string, parent_id: string | null}[]} items
 * @returns {Map<string, string | null>}
 */
function effectiveParents(items) {
  const known = new Set(items.map((item) => item.id));
  const parents = new Map(items.map((item) => [item.id, known.has(item.parent_id) ? item.parent_id : null]));
  const settled = new Set();
  for (const item of items) {
    const walked = new Set();
    let current = item.id;
    while (current !== null && !settled.has(current)) {
      if (walked.has(current)) {
        parents.set(current, null); // the walk came back to a folder it already passed: cut the cycle here
        break;
      }
      walked.add(current);
      current = parents.get(current);
    }
    walked.forEach((id) => settled.add(id));
  }
  return parents;
}

/**
 * The lookups over a list of folders (see the file header).
 * @param {{id: string, name: string, parent_id: string | null}[]} items
 * @returns {{items: object[], has: (id: string) => boolean, get: (id: string) => object | undefined, childrenOf: (id: string | null) => object[], pathOf: (id: string | null) => object[], depthOf: (id: string | null) => number, heightOf: (id: string | null) => number, descendantsOf: (id: string) => object[]}}
 */
export function buildIndex(items) {
  const byId = new Map(items.map((item) => [item.id, item]));
  const parents = effectiveParents(items);
  const kids = new Map();
  for (const item of items) {
    const parent = parents.get(item.id);
    kids.set(parent, [...(kids.get(parent) ?? []), item]);
  }
  const childrenOf = (id) => kids.get(id ?? null) ?? [];
  const pathOf = (id) => {
    const path = [];
    for (let current = byId.has(id) ? id : null; current !== null; current = parents.get(current)) {
      path.push(byId.get(current));
    }
    return path.reverse();
  };
  const heightOf = (id) => 1 + Math.max(0, ...childrenOf(id).map((child) => heightOf(child.id)));
  const descendantsOf = (id) => childrenOf(id).flatMap((child) => [child, ...descendantsOf(child.id)]);
  return {
    items,
    has: (id) => byId.has(id),
    get: (id) => byId.get(id),
    childrenOf,
    pathOf,
    depthOf: (id) => pathOf(id).length,
    heightOf,
    descendantsOf,
  };
}

/**
 * Every collection with the number of graphs and collections directly inside it.
 * @param {AbortSignal} [signal]
 * @returns {Promise<object[]>}  FolderSummary records in name order
 */
export async function fetchFolders(signal) {
  const page = await api.get("/folders", { signal, quiet: true });
  return page.items;
}

/**
 * Creates a collection.
 * @param {{name: string, parent_id: string | null}} body
 * @returns {Promise<{id: string, name: string}>}
 */
export function createFolder(body) {
  return api.post("/folders", body);
}

/**
 * Renames and/or moves a collection. The server wants the whole record and the revision this page
 * last saw; a stale revision is a 409 `conflict`.
 * @param {{id: string, name: string, parent_id: string | null, revision: number}} folder
 * @param {{name?: string, parent_id?: string | null}} patch
 * @returns {Promise<object>}
 */
export function updateFolder(folder, patch) {
  const body = { name: folder.name, parent_id: folder.parent_id ?? null, revision: folder.revision, ...patch };
  return api.put(`/folders/${folder.id}`, body);
}

/**
 * Deletes a collection; its graphs and collections move up to its parent.
 * @param {string} id
 * @returns {Promise<null>}
 */
export function deleteFolder(id) {
  return api.del(`/folders/${id}`);
}

/**
 * Moves graphs into a collection (`null` = the top level).
 * @param {string[]} ids  1..200 graph ids
 * @param {string | null} folderId
 * @returns {Promise<{moved: number, missing: string[]}>}
 */
export function moveGraphs(ids, folderId) {
  return api.post("/graphs/move", { ids, folder_id: folderId });
}
