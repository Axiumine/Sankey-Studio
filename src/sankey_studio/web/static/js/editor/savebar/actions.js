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
 */

const NAME_MAX = 200;
const SUFFIX = " (copy)";

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
  const definition = id ? await api.put(`/graphs/${id}`, body) : await api.post("/graphs", body);
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
  const definition = await api.post("/graphs", { ...body, name: copyName(body.name) });
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
