// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Keeps `status.dirty` honest.
 *
 * The store marks the graph "dirty" on every edit under `draft` and `meta`, even one that puts
 * the same values back (switching from Manual to Paste and back, retyping a character, or a
 * column guess made while a saved graph opens). This module compares the graph with the last
 * clean state, its baseline, and takes the flag back when nothing differs. Both sides are first put
 * in the same form (baseline.js), so a field that was cleared (the key is gone) equals the
 * server's `null` or default for it:
 *
 * - the baseline is the draft, name, description and tags at every moment the store says the
 *   graph is clean (after a load, a save, or a write made with `{clean: true}`);
 * - while the store says it is dirty, the flag is cleared again as soon as the graph equals the
 *   baseline;
 * - after a save that left newer edits in flight the baseline is unknown, so the store's own
 *   flag is trusted until the next clean moment.
 *
 * `applyDerived` is for writes the person did not make (a guess made from the data): they must not
 * turn a clean graph into an "unsaved" one.
 */

import { savedForm } from "./baseline.js";
import { sameJson } from "./util.js";

const snapshotOf = savedForm;

/**
 * Starts tracking; returns the stop function.
 * @param {{get: Function, subscribe: Function, patch: Function}} store
 * @returns {() => void}
 */
export function trackDirty(store) {
  let baseline = snapshotOf(store.get());
  let saved = `${store.get().meta.id}|${store.get().meta.revision}`;
  return store.subscribe(
    (_, state) => {
      const version = `${state.meta.id}|${state.meta.revision}`;
      if (version !== saved) {
        saved = version;
        baseline = null; // a save landed: the baseline is only known again at the next clean moment
      }
      if (!state.status.dirty) {
        baseline = snapshotOf(state);
      } else if (baseline && sameJson(snapshotOf(state), baseline)) {
        store.patch(["status", "dirty"], false, { clean: true });
      }
    },
  );
}

/**
 * Runs `fn` (a batch of store writes that follow from the data, not from an edit by the person).
 * A graph that was clean before stays clean; a graph with unsaved edits stays dirty.
 * @param {{get: Function, batch: Function, patch: Function}} store
 * @param {() => void} fn
 */
export function applyDerived(store, fn) {
  const wasClean = !store.get().status.dirty;
  store.batch(() => {
    fn();
    if (wasClean) {
      store.patch(["status", "dirty"], false, { clean: true });
    }
  });
}
