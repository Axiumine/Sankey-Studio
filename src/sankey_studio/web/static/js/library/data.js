/**
 * Library data: one page of graphs, the tag list, and the three row actions.
 *
 * The API lists graphs newest first and has no sort option. "Recently updated" therefore pages
 * on the server (`limit`/`offset`); every other sort loads the matching graphs (at most
 * `FETCH_CAP`, 200 per request), sorts them here and cuts the page. `truncated` tells the page
 * when more graphs matched than were loaded, so it can say the order covers the newest only.
 */

import { api } from "../core/api.js";
import { withDisplayName } from "./names.js";
import { DEFAULT_SORT, PAGE_SIZE } from "./state.js";

/** Most graphs loaded for a client-side sort (five requests of 200). */
export const FETCH_CAP = 1000;
const REQUEST_MAX = 200;
const ID_PATTERN = /^[0-9a-f]{32}$/;

/**
 * True for a graph id as the API makes them (32 lowercase hex characters).
 * @param {unknown} id
 * @returns {boolean}
 */
export function isGraphId(id) {
  return typeof id === "string" && ID_PATTERN.test(id);
}

/**
 * Path of a graph page. The id comes from the API; anything else is refused.
 * @param {string} id
 * @param {string} [suffix]  such as `/edit`
 * @returns {string}
 */
export function graphHref(id, suffix = "") {
  if (!isGraphId(id)) {
    throw new TypeError("not a graph id");
  }
  return `/graphs/${id}${suffix}`;
}

const compareText = (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

const SORTERS = {
  "updated-asc": (a, b) => a.updated_at.localeCompare(b.updated_at),
  "name-asc": (a, b) => compareText(a.name, b.name) || a.id.localeCompare(b.id),
  "name-desc": (a, b) => compareText(b.name, a.name) || a.id.localeCompare(b.id),
};

/**
 * Sorts graph summaries (a copy). "updated-desc" keeps the server's order.
 * @param {object[]} items
 * @param {string} sort
 * @returns {object[]}
 */
export function sortItems(items, sort) {
  const sorter = SORTERS[sort];
  return sorter ? [...items].sort(sorter) : [...items];
}

async function fetchAll(base, signal) {
  const items = [];
  let total = 0;
  while (items.length < FETCH_CAP) {
    const page = await api.get("/graphs", {
      query: { ...base, limit: REQUEST_MAX, offset: items.length },
      signal,
    });
    total = page.total;
    items.push(...page.items.map(withDisplayName));
    if (page.items.length === 0 || items.length >= total) {
      break;
    }
  }
  return { items, total };
}

/**
 * Loads the page of graphs the state asks for.
 * @param {{q: string, tag: string, sort: string, page: number}} state
 * @param {AbortSignal} [signal]
 * @returns {Promise<{items: object[], total: number, truncated: boolean}>}
 */
export async function fetchPage(state, signal) {
  const base = { q: state.q, tag: state.tag };
  const offset = (state.page - 1) * PAGE_SIZE;
  if (state.sort === DEFAULT_SORT) {
    const page = await api.get("/graphs", { query: { ...base, limit: PAGE_SIZE, offset }, signal });
    return { items: page.items.map(withDisplayName), total: page.total, truncated: false };
  }
  const all = await fetchAll(base, signal);
  const sorted = sortItems(all.items, state.sort);
  return {
    items: sorted.slice(offset, offset + PAGE_SIZE),
    total: all.total,
    truncated: all.total > all.items.length,
  };
}

/**
 * The ids to export when nothing is picked: the newest graphs that match the filters.
 * @param {{q: string, tag: string}} state
 * @param {AbortSignal} [signal]
 * @returns {Promise<{ids: string[], total: number}>}
 */
export async function fetchExportIds(state, signal) {
  const page = await api.get("/graphs", {
    query: { q: state.q, tag: state.tag, limit: REQUEST_MAX, offset: 0 },
    signal,
  });
  return { ids: page.items.map((item) => item.id), total: page.total };
}

/**
 * All tags in use, sorted.
 * @param {AbortSignal} [signal]
 * @returns {Promise<string[]>}
 */
export function fetchTags(signal) {
  return api.get("/tags", { signal, quiet: true });
}

/**
 * Deletes a graph.
 * @param {string} id
 * @returns {Promise<null>}
 */
export function deleteGraph(id) {
  return api.del(`/graphs/${id}`);
}

/**
 * Duplicates a graph; resolves to the new GraphDefinition.
 * @param {string} id
 * @returns {Promise<{id: string, name: string}>}
 */
export function duplicateGraph(id) {
  return api.action(`/graphs/${id}/duplicate`);
}
