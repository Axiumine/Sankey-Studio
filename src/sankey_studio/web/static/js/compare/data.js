/**
 * Compare data: the bundles of several graphs drawn with one shared category colour map.
 *
 * `GET /compare/render?ids=` answers for the whole set or not at all: one deleted id is a 404 and
 * one graph that cannot be built (a cycle, an unreadable source) is a 422 for everyone. `resolve`
 * therefore falls back to asking for each graph alone (`GET /graphs/{id}/render`) to find out which
 * ones are missing or broken, then asks again for the set that works, so one bad graph never blanks
 * the page.
 */

import { ApiError, api, isAbort } from "../core/api.js";

const PROBE_BATCH = 4;
const RETRYABLE = new Set([404, 422]);

/**
 * @param {string[]} ids  1..12 graph ids
 * @param {"light"|"dark"} theme
 * @param {AbortSignal} [signal]
 * @returns {Promise<object[]>} RenderBundles in the order of `ids`
 */
export function fetchCompare(ids, theme, signal) {
  return api.get("/compare/render", { query: { ids, theme }, signal });
}

async function probe(id, theme, signal) {
  try {
    await api.get(`/graphs/${id}/render`, { query: { theme }, signal, quiet: true });
    return { id, ok: true };
  } catch (error) {
    if (isAbort(error) || !(error instanceof ApiError)) {
      throw error;
    }
    return { id, ok: false, kind: error.status === 404 ? "missing" : "broken", message: error.friendly };
  }
}

async function probeAll(ids, theme, signal) {
  const results = [];
  for (let start = 0; start < ids.length; start += PROBE_BATCH) {
    const batch = ids.slice(start, start + PROBE_BATCH);
    results.push(...(await Promise.all(batch.map((id) => probe(id, theme, signal)))));
  }
  return results;
}

/**
 * Loads the bundles for `ids`, isolating graphs that are missing or broken.
 * @param {string[]} ids
 * @param {"light"|"dark"} theme
 * @param {AbortSignal} [signal]
 * @returns {Promise<{bundles: Map<string, object>, problems: Map<string, {kind: "missing"|"broken", message: string}>}>}
 */
export async function resolve(ids, theme, signal) {
  const bundles = new Map();
  const problems = new Map();
  if (ids.length === 0) {
    return { bundles, problems };
  }
  let good = ids;
  let list = null;
  try {
    list = await fetchCompare(ids, theme, signal);
  } catch (error) {
    if (!(error instanceof ApiError) || !RETRYABLE.has(error.status)) {
      throw error;
    }
    const checked = await probeAll(ids, theme, signal);
    checked.filter((item) => !item.ok).forEach((item) => problems.set(item.id, { kind: item.kind, message: item.message }));
    good = checked.filter((item) => item.ok).map((item) => item.id);
    list = good.length > 0 ? await fetchCompare(good, theme, signal) : [];
  }
  good.forEach((id, index) => bundles.set(id, list[index]));
  return { bundles, problems };
}
