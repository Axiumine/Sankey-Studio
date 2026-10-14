/**
 * Pure draft rewrites of the edit engine: no DOM, no network, every function returns NEW objects.
 *
 * An edit that stays in the graph is an "overlay": `transform.entry_categories` (a category for a
 * pair), `transform.extra_links` (an added entry) and `style.node_order` (a node order). An edit
 * that reaches the data comes back from the server as a new `source` plus an `override` telling
 * what to do with a stale `entry_categories` item (`drop` it, or `set` it again).
 */

import { upsertEntry } from "../entries/edits.js";

/** The server caps `transform.extra_links` here (`MAX_EXTRA_LINKS`). */
export const EXTRA_LINKS_MAX = 2000;

function samePair(item, edit) {
  return item.source === edit.source && item.target === edit.target;
}

/**
 * The draft with the overlay `extra_links` row of an `add_entry` edit appended.
 * @param {object} draft
 * @param {{source: string, target: string, value: number, category?: string | null}} edit
 * @returns {object}
 */
export function overlayAdd(draft, edit) {
  const link = { source: edit.source, target: edit.target, value: edit.value, category: edit.category ?? null };
  return { ...draft, transform: { ...draft.transform, extra_links: [...(draft.transform?.extra_links ?? []), link] } };
}

/**
 * Why another added entry cannot be kept in the graph, or null.
 * @param {object} draft
 * @returns {string | null}
 */
export function addProblem(draft) {
  const count = draft.transform?.extra_links?.length ?? 0;
  return count >= EXTRA_LINKS_MAX ? `This graph already holds ${EXTRA_LINKS_MAX.toLocaleString("en")} added entries, which is the limit.` : null;
}

/**
 * What to do with the `entry_categories` item of the edited pair after the data changed.
 * `drop` removes it (the data now says it), `set` writes the edit's category (possibly null) again.
 * @param {object} draft
 * @param {"drop" | "set" | null | undefined} override
 * @param {{source: string, target: string, category?: string | null}} edit
 * @returns {object}
 */
export function applyOverride(draft, override, edit) {
  const list = draft.transform?.entry_categories ?? [];
  let next = null;
  if (override === "drop") {
    next = list.filter((item) => !samePair(item, edit));
  } else if (override === "set") {
    next = upsertEntry(list, edit, edit.category ?? null);
  }
  if (next === null || (override === "drop" && next.length === list.length)) {
    return draft;
  }
  return { ...draft, transform: { ...draft.transform, entry_categories: next } };
}

/**
 * The draft with the stored node order replaced.
 * @param {object} draft
 * @param {string[]} order
 * @returns {object}
 */
export function withOrder(draft, order) {
  return { ...draft, style: { ...draft.style, node_order: order } };
}

/**
 * The draft with the colours a row reorder pinned (the server's `pins`) added to its style. A
 * colour the person already pinned wins over a new pin.
 * @param {object} draft
 * @param {{node_colors?: object, category_colors?: object} | null | undefined} pins
 * @returns {object}
 */
export function withPins(draft, pins) {
  if (!pins) {
    return draft;
  }
  const style = { ...draft.style };
  for (const key of ["node_colors", "category_colors"]) {
    if (pins[key] && Object.keys(pins[key]).length) {
      style[key] = { ...pins[key], ...draft.style?.[key] };
    }
  }
  return { ...draft, style };
}

/**
 * The sentence for the pins a reorder added, or null when there are none.
 * @param {{node_colors?: object, category_colors?: object} | null | undefined} pins
 * @returns {string | null}
 */
export function pinsText(pins) {
  const count = Object.keys(pins?.node_colors ?? {}).length + Object.keys(pins?.category_colors ?? {}).length;
  return count ? `${count} colour${count === 1 ? " was" : "s were"} pinned so the chart keeps its colours.` : null;
}

/**
 * The draft with a write-back preference (or `null`) on its source.
 * @param {object} draft
 * @param {{mode: "source" | "graph", target: string} | null} pref
 * @returns {object}
 */
export function withPref(draft, pref) {
  return { ...draft, source: { ...draft.source, write_back: pref } };
}

/**
 * The parts of a draft an edit can touch, for Undo.
 * @param {object} draft
 * @returns {{source: object, entry_categories: object[] | undefined, extra_links: object[] | undefined, node_order: string[] | undefined, node_colors: object | undefined, category_colors: object | undefined}}
 */
export function snapshotFor(draft) {
  return {
    source: draft.source,
    entry_categories: draft.transform?.entry_categories,
    extra_links: draft.transform?.extra_links,
    node_order: draft.style?.node_order,
    node_colors: draft.style?.node_colors,
    category_colors: draft.style?.category_colors,
  };
}

function put(object, key, value) {
  if (value === undefined) {
    const { [key]: _gone, ...rest } = object ?? {};
    return rest;
  }
  return { ...object, [key]: value };
}

/**
 * The draft with the snapshot's parts put back (everything else stays as it is now).
 * @param {object} draft
 * @param {ReturnType<typeof snapshotFor>} snapshot
 * @returns {object}
 */
export function restore(draft, snapshot) {
  let transform = put(draft.transform, "entry_categories", snapshot.entry_categories);
  transform = put(transform, "extra_links", snapshot.extra_links);
  let style = put(draft.style, "node_order", snapshot.node_order);
  style = put(style, "node_colors", snapshot.node_colors);
  style = put(style, "category_colors", snapshot.category_colors);
  return { ...draft, source: snapshot.source, transform, style };
}

/**
 * The draft with ONE edit undone, or null when that is no longer possible. Only the parts the edit
 * changed (`before` against `after`, both from `snapshotFor`) are put back, and only while each of
 * them is still the very object the edit left; a later edit of the same part (another added entry,
 * another drag) makes the Undo of the first one refuse instead of wiping the later work. Parts the
 * edit did not change, and later edits of those, stay as they are.
 * @param {object} draft  the current draft
 * @param {ReturnType<typeof snapshotFor>} before
 * @param {ReturnType<typeof snapshotFor>} after
 * @returns {object | null}
 */
export function undoEdit(draft, before, after) {
  const now = snapshotFor(draft);
  const changed = Object.keys(before).filter((part) => before[part] !== after[part]);
  if (changed.some((part) => now[part] !== after[part])) {
    return null;
  }
  return restore(draft, { ...now, ...Object.fromEntries(changed.map((part) => [part, before[part]])) });
}

/**
 * Identity of a source for "once per reason and source" notices.
 * @param {object | undefined} source
 * @returns {string}
 */
export function sourceKey(source) {
  return [source?.type, source?.path, source?.connection, source?.database, source?.collection].join("\u0000");
}

/**
 * "3 rows" or "1 document".
 * @param {string} where
 * @param {number} count
 * @returns {string}
 */
export function noun(where, count) {
  const word = where === "mongo" ? "document" : "row";
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}
