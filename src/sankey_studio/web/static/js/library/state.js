/**
 * State of the library page: the query (search, tag, sort, page) that the URL keeps, and the
 * set of graphs picked for a comparison.
 *
 * The query lives in the address (`/?q=rent&tag=demo&sort=name-asc&page=2`) so a reload, the back
 * button and a copied link show the same list. Defaults are left out of the URL.
 */

import { stripBidi } from "../core/text.js";

/** Cards per page. */
export const PAGE_SIZE = 12;
/** Most graphs the compare page accepts. */
export const MAX_COMPARE = 12;
/** Longest search text and tag the API accepts. */
export const Q_MAX = 200;
export const TAG_MAX = 40;
/**
 * Last page the address may name. A page this far out is empty anyway (the list then jumps to its
 * real last page); the cap keeps `offset` a plain integer the API accepts.
 */
export const PAGE_MAX = 100000;

/** Sort choices; only the first is the server's own order, the others sort on the client. */
export const SORTS = Object.freeze([
  { value: "updated-desc", label: "Recently updated" },
  { value: "updated-asc", label: "Least recently updated" },
  { value: "name-asc", label: "Name, A to Z" },
  { value: "name-desc", label: "Name, Z to A" },
]);

export const DEFAULT_SORT = SORTS[0].value;

/**
 * Reads the query state from a location search string. Search text and tag lose control and
 * bidirectional characters (a value made only of them is no filter), and the page is capped at
 * `PAGE_MAX`.
 * @param {string} search  such as `location.search`
 * @returns {{q: string, tag: string, sort: string, page: number}}
 */
export function readQuery(search) {
  const params = new URLSearchParams(search);
  const sort = params.get("sort");
  const page = Number.parseInt(params.get("page") ?? "1", 10);
  const text = (name, max) => stripBidi(params.get(name) ?? "").trim().slice(0, max);
  return {
    q: text("q", Q_MAX),
    tag: text("tag", TAG_MAX),
    sort: SORTS.some((item) => item.value === sort) ? sort : DEFAULT_SORT,
    page: Number.isFinite(page) && page >= 1 ? Math.min(page, PAGE_MAX) : 1,
  };
}

/**
 * The address search string for a state (empty for the defaults).
 * @param {{q: string, tag: string, sort: string, page: number}} state
 * @returns {string}
 */
export function queryString(state) {
  const params = new URLSearchParams();
  if (state.q) {
    params.set("q", state.q);
  }
  if (state.tag) {
    params.set("tag", state.tag);
  }
  if (state.sort !== DEFAULT_SORT) {
    params.set("sort", state.sort);
  }
  if (state.page > 1) {
    params.set("page", String(state.page));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

/**
 * Writes the state into the address without adding a history entry.
 * @param {{q: string, tag: string, sort: string, page: number}} state
 */
export function writeQuery(state) {
  const next = `${location.pathname}${queryString(state)}`;
  if (next !== `${location.pathname}${location.search}`) {
    history.replaceState(null, "", next);
  }
}

/**
 * The graphs picked for comparison: an ordered set with a cap.
 * `toggle(id, name)` returns false when the cap blocks an addition.
 * @param {number} [max]
 * @returns {{has: (id: string) => boolean, toggle: (id: string, name?: string) => boolean, remove: (id: string) => void, clear: () => void, ids: () => string[], size: () => number, full: () => boolean, subscribe: (fn: () => void) => () => void}}
 */
export function createSelection(max = MAX_COMPARE) {
  const picked = new Map();
  const listeners = new Set();
  const emit = () => listeners.forEach((fn) => fn());
  return {
    has: (id) => picked.has(id),
    toggle(id, name = "") {
      if (picked.delete(id)) {
        emit();
        return true;
      }
      if (picked.size >= max) {
        return false;
      }
      picked.set(id, name);
      emit();
      return true;
    },
    remove(id) {
      if (picked.delete(id)) {
        emit();
      }
    },
    clear() {
      if (picked.size > 0) {
        picked.clear();
        emit();
      }
    },
    ids: () => Array.from(picked.keys()),
    size: () => picked.size,
    full: () => picked.size >= max,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}
