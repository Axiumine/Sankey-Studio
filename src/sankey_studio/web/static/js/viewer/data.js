/**
 * Viewer data: the render bundle of a saved graph.
 */

import { api } from "../core/api.js";

/**
 * `GET /graphs/{id}/render?theme=` (the figures carry their own colours for that theme).
 * @param {string} id
 * @param {"light"|"dark"} theme
 * @param {AbortSignal} [signal]
 * @returns {Promise<object>} a RenderBundle
 */
export function fetchRender(id, theme, signal) {
  return api.get(`/graphs/${id}/render`, { query: { theme }, signal });
}

/**
 * The saved graph as the library knows it now (name, description, tags, source type, revision,
 * update time), or null when it cannot be read; the page then keeps what it has.
 * @param {string} id
 * @param {AbortSignal} [signal]
 * @returns {Promise<{id: string, name: string, description: string, tags: string[], source_type: string, revision: number, updated_at: string} | null>}
 */
export async function fetchGraph(id, signal) {
  try {
    const graph = await api.get(`/graphs/${id}`, { signal, quiet: true });
    const { name, description, tags, revision, updated_at: updated } = graph;
    return { id, name, description, tags, source_type: graph.source?.type, revision, updated_at: updated };
  } catch {
    return null;
  }
}

/**
 * The donut basis of the saved style (`all`, `initial`, `terminal`), or null when the definition
 * cannot be read (the page then simply leaves the note out).
 * @param {string} id
 * @param {AbortSignal} [signal]
 * @returns {Promise<string | null>}
 */
export async function fetchDonutBasis(id, signal) {
  try {
    const graph = await api.get(`/graphs/${id}`, { signal, quiet: true });
    return graph?.style?.donut?.basis ?? null;
  } catch {
    return null;
  }
}
