/**
 * Viewer data: the render bundle of a saved graph.
 */

import { api } from "../core/api.js";

/**
 * `GET /graphs/{id}/render?theme=&node_values=&donut_percent=&donut_value=` (the figures carry
 * their own colours for that theme). `display` holds only the switches the person changed; a
 * missing one keeps what the saved style says.
 * @param {string} id
 * @param {"light"|"dark"} theme
 * @param {AbortSignal} [signal]
 * @param {{node_values?: boolean, donut_percent?: boolean, donut_value?: boolean}} [display]
 * @returns {Promise<object>} a RenderBundle
 */
export function fetchRender(id, theme, signal, display) {
  return api.get(`/graphs/${id}/render`, { query: { theme, ...display }, signal });
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

/** What the viewer shows when the saved style cannot be read (the model's defaults). */
export const DEFAULT_VIEW = Object.freeze({
  basis: null,
  values: Object.freeze({ node_values: false, donut_percent: true, donut_value: false }),
});

/**
 * The parts of the saved style the viewer needs: the donut basis (`all`, `initial`, `terminal`) and
 * the label switches, or null when the definition cannot be read (the page then leaves the basis
 * note out and starts from the defaults).
 * @param {string} id
 * @param {AbortSignal} [signal]
 * @returns {Promise<{basis: string | null, values: {node_values: boolean, donut_percent: boolean, donut_value: boolean}} | null>}
 */
export async function fetchViewStyle(id, signal) {
  try {
    const graph = await api.get(`/graphs/${id}`, { signal, quiet: true });
    const style = graph?.style ?? {};
    const donut = style.donut ?? {};
    const { values } = DEFAULT_VIEW;
    return {
      basis: donut.basis ?? null,
      values: {
        node_values: style.show_values_in_labels ?? values.node_values,
        donut_percent: donut.show_percent ?? values.donut_percent,
        donut_value: donut.show_value ?? values.donut_value,
      },
    };
  } catch {
    return null;
  }
}
