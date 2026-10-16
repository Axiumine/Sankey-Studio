// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Where a graph or a collection may go: the one place that knows why a place is refused.
 *
 * The Move dialog (folder-dialogs.js) and drag and drop (dnd-moves.js) both ask it, so they refuse
 * the same places with the same sentences. It is pure (no DOM, no requests): it only reads the
 * lookups of `buildIndex` (folders-data.js).
 *
 * `createRules({index, current, moving})` returns `reasonFor(target, depth?)`:
 *   - `target`   the collection that would receive the thing (`null` = the top level, the library)
 *   - `depth`    levels down to `target` (`index.depthOf(target)` when left out)
 *   - the result is the reason the place is refused, or `null` when it is fine
 * `current` is the collection the thing sits in now (`null` = the top level; leave it `undefined`
 * when several graphs from different places move, so no place is "already here"). `moving` is the
 * collection being moved, or `null` for graphs: a collection cannot go into itself or below itself,
 * and not so deep that its own tree passes `DEPTH_MAX` levels. Graphs have no such rules.
 *
 * `parentOf(index, id)` is the collection that `id` is drawn under (`null` = the top level), after
 * the index read dangling parents as the top level and cut cycles.
 */

import { DEPTH_MAX } from "./folders-data.js";

/** The reasons, as the Move dialog shows them next to a disabled place. */
export const REASON_INSIDE = "inside the collection being moved";
export const REASON_HERE = "already here";
export const REASON_DEEP = `too deep (at most ${DEPTH_MAX} levels)`;

/**
 * @param {{pathOf: (id: string | null) => {id: string}[]}} index
 * @param {string} id
 * @returns {string | null}
 */
export function parentOf(index, id) {
  const path = index.pathOf(id);
  return path.length > 1 ? path[path.length - 2].id : null;
}

/**
 * @param {{index: object, current?: string | null, moving?: {id: string} | null}} options
 * @returns {(target: string | null, depth?: number) => string | null}
 */
export function createRules({ index, current, moving = null }) {
  const blocked = new Set(moving ? [moving.id, ...index.descendantsOf(moving.id).map((item) => item.id)] : []);
  const height = moving ? index.heightOf(moving.id) : 0;
  return (target, depth = index.depthOf(target)) => {
    if (target === null) {
      return current === null ? REASON_HERE : null; // the top level is never too deep
    }
    if (blocked.has(target)) {
      return REASON_INSIDE;
    }
    if (target === current) {
      return REASON_HERE;
    }
    return moving && depth + height > DEPTH_MAX ? REASON_DEEP : null;
  };
}
