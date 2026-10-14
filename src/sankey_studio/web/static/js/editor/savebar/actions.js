/**
 * The three things the save bar can do to the editor store and the API.
 *
 * - `saveGraph({store, api})` creates (`POST /graphs`) or updates (`PUT /graphs/{id}` with the
 *   revision the editor last saw) and marks the store saved. Edits made while the request ran stay
 *   dirty (store.markSaved keeps them). A 409 `conflict` or 404 is thrown as the ApiError.
 * - `saveCopy({store, api})` creates a NEW graph from the current draft (`POST /graphs`, named
 *   "<name> (copy)") and points the store at it, so the editor continues on the copy and the original
 *   is left exactly as the other writer saved it.
 * - `reloadGraph({store, api})` fetches the saved version and replaces the draft with it (local
 *   edits are discarded).
 * - `copyName(name)`: "<name> (copy)", cut so it never passes the 200 character limit.
 *
 * A graph that sits in a collection (`meta.folder_id`, also the one a new graph was started in)
 * is created inside it (`POST /graphs?folder=<id>`). When that collection is gone (404) the graph
 * is created at the top level instead and the person is told.
 */

import { ApiError } from "../../core/api.js";
import { toast } from "../../core/toast.js";
import { NAME_MAX } from "../meta/limits.js";

const SUFFIX = " (copy)";
const FOLDER_GONE = "That collection no longer exists, so the graph was saved at the top level of the library.";

async function createGraph({ store, api }, body) {
  const folder = store.get().meta.folder_id;
  if (!folder) {
    return api.post("/graphs", body);
  }
  try {
    return await api.post("/graphs", body, { query: { folder } });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) {
      throw error;
    }
    store.patch(["meta", "folder_id"], null, { clean: true });
    toast.warning(FOLDER_GONE);
    return api.post("/graphs", body);
  }
}

/**
 * @param {string} name
 * @returns {string}
 */
export function copyName(name) {
  const letters = Array.from(name.trim());
  return `${letters.slice(0, NAME_MAX - SUFFIX.length).join("")}${SUFFIX}`;
}

/**
 * Creates or updates the graph.
 * @param {{store: object, api: object}} deps
 * @returns {Promise<{definition: object, created: boolean}>}
 */
export async function saveGraph({ store, api }) {
  const id = store.get().meta.id;
  const body = store.toPayload();
  const definition = id ? await api.put(`/graphs/${id}`, body) : await createGraph({ store, api }, body);
  store.markSaved(definition);
  return { definition, created: !id };
}

/**
 * Saves the draft as a new graph and continues on it.
 * @param {{store: object, api: object}} deps
 * @returns {Promise<object>} the new GraphDefinition
 */
export async function saveCopy({ store, api }) {
  const { revision: _revision, ...body } = store.toPayload();
  const definition = await createGraph({ store, api }, { ...body, name: copyName(body.name) });
  store.markSaved(definition);
  return definition;
}

/**
 * Replaces the draft with the saved version.
 * @param {{store: object, api: object}} deps
 * @returns {Promise<object>} the GraphDefinition
 */
export async function reloadGraph({ store, api }) {
  const id = store.get().meta.id;
  const definition = await api.get(`/graphs/${id}`);
  store.load(definition);
  return definition;
}
