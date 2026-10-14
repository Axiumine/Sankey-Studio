/**
 * Small store/DOM helpers of the engine.
 *
 * - `touchSource(store)`: after a write that did not change the draft (the file or the documents
 *   changed, the spec did not), a NEW source object with the same content makes the preview and
 *   the entries table ask the server again (both select `draft.source`). Clean: nothing to save.
 * - `announceWritten(path)`: tells the page that a managed file changed on disk, so the file model
 *   (`source/files.js`) drops the cached preview lines of that file.
 */

/** The event `announceWritten` fires on `document`; `detail` is `{path}`. */
export const SOURCE_WRITTEN = "sankey:source-written";

/**
 * @param {{patch: Function}} store
 */
export function touchSource(store) {
  store.patch(["draft", "source"], (source) => ({ ...source }), { clean: true });
}

/**
 * @param {string | null | undefined} path  the managed file name, null for a collection
 */
export function announceWritten(path) {
  document.dispatchEvent(new CustomEvent(SOURCE_WRITTEN, { detail: { path: path ?? null } }));
}
