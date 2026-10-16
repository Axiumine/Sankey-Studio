// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The seed: what the new-graph wizard hands to the editor.
 *
 * Shape: `{meta: {name, description, tags}, source}` where `source` is the wizard store's
 * `draft.source`. The editor applies it AFTER its unsaved-changes tracking is installed
 * (pages/editor.js), without `clean`: the tracker takes its baseline from the blank new graph, so a
 * seed written earlier would be the baseline and the typed data would not be protected from an
 * accidental leave. Because the name is not empty, the graph stays "not saved yet" until the
 * first save.
 */

/**
 * Builds a seed from the wizard store.
 * @param {{get: () => {meta: {name: string, description: string, tags: string[]}, draft: {source: object}}}} store
 * @param {object} [source]  replaces the store's source (used by "Do it later")
 * @returns {{meta: {name: string, description: string, tags: string[]}, source: object}}
 */
export function seedFrom(store, source) {
  const { meta, draft } = store.get();
  return {
    meta: { name: meta.name.trim(), description: meta.description, tags: [...meta.tags] },
    source: source ?? draft.source,
  };
}

/**
 * Writes a seed into the editor store (one notification, not clean). `null` does nothing.
 * @param {{batch: (fn: () => void) => void, patch: Function}} store
 * @param {ReturnType<typeof seedFrom> | null} seed
 */
export function applySeed(store, seed) {
  if (!seed) {
    return;
  }
  store.batch(() => {
    store.patch(["meta", "name"], seed.meta.name);
    store.patch(["meta", "description"], seed.meta.description);
    store.patch(["meta", "tags"], seed.meta.tags);
    store.patch(["draft", "source"], seed.source);
  });
}
