/**
 * The files in the managed sources folder, as one small observable model shared by the "Text
 * file" and "Upload" tabs and the data preview.
 *
 * - `refresh()`           GET /sources/files; `state` is `{status: "idle"|"loading"|"ready"|"error",
 *                         files: [{name, size, modified}], error}`.
 * - `upload(file, {overwrite})`  POST /sources/files (FormData through the one fetch wrapper). An
 *                         existing name answers 409 `conflict`: the caller asks and retries with
 *                         `overwrite: true`.
 * - `remove(name)`        DELETE /sources/files/{name}.
 * - `preview(name)`       first lines of a file (cached; the cache is cleared when the file
 *                         changes), GET /sources/files/{name}/preview.
 * - `dispose()`           stops listening for `sankey:source-written` (the edit engine wrote a file:
 *                         its cached preview lines are dropped).
 * File names are relative POSIX paths; each segment is URL-encoded, the slashes stay.
 */

import { isAbort } from "../../core/api.js";
import { SOURCE_WRITTEN } from "../edits/touch.js";

const encodeName = (name) => name.split("/").map(encodeURIComponent).join("/");

async function loadList(api, state, current) {
  try {
    const files = await api.get("/sources/files", { quiet: true });
    if (current()) {
      Object.assign(state, { status: "ready", files, error: "" });
    }
  } catch (error) {
    if (!isAbort(error) && current()) {
      Object.assign(state, { status: "error", error: error.friendly ?? error.message });
    }
  }
}

/**
 * Creates the model.
 * @param {typeof import("../../core/api.js").api} api
 * @returns {{state: object, dispose: () => void, subscribe: (callback: () => void) => () => void, refresh: () => Promise<void>, upload: (file: File, options?: {overwrite?: boolean}) => Promise<object>, remove: (name: string) => Promise<void>, preview: (name: string) => Promise<string[]>, find: (name: string) => object | undefined}}
 */
export function createFiles(api) {
  const state = { status: "idle", files: [], error: "" };
  const listeners = new Set();
  const previews = new Map();
  const emit = () => listeners.forEach((callback) => callback());
  let sequence = 0;
  const written = (event) => previews.delete(event.detail?.path);
  document.addEventListener(SOURCE_WRITTEN, written);
  return {
    state,
    dispose: () => document.removeEventListener(SOURCE_WRITTEN, written),
    subscribe(callback) {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
    find: (name) => state.files.find((file) => file.name === name),
    async refresh() {
      sequence += 1;
      const mine = sequence;
      state.status = "loading";
      emit();
      await loadList(api, state, () => mine === sequence);
      emit();
    },
    async upload(file, options = {}) {
      const form = new FormData();
      form.append("file", file);
      if (options.overwrite) {
        form.append("overwrite", "true");
      }
      const stored = await api.upload("/sources/files", form);
      previews.delete(stored.name);
      return stored;
    },
    async remove(name) {
      await api.del(`/sources/files/${encodeName(name)}`);
      previews.delete(name);
    },
    async preview(name) {
      if (!previews.has(name)) {
        const answer = await api.get(`/sources/files/${encodeName(name)}/preview`, { quiet: true });
        previews.set(name, answer.lines ?? []);
      }
      return previews.get(name);
    },
  };
}
