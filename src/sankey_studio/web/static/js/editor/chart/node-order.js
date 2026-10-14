/**
 * The order of the nodes of a drawn Sankey, as pure functions on `bundle.nodes`.
 *
 * `bundle.nodes` is what POST /preview answers: `[{name, layer, node_in, node_out}]`, one row per node
 * of the figure, in the order of `figure.data[0].node.label` (so a `pointNumber` is an index into it).
 * An ORDER here is one list of names: the nodes of the first column from the first to the last
 * position, then the second column, and so on. It is what `style.node_order` stores; the server sorts
 * the drawn nodes by it and Plotly keeps that order inside each of its columns.
 *
 * The columns are the ones Plotly DRAWS, not the server's `layer`: Plotly's default alignment
 * ("justify") moves every node without an outgoing link to the last column, so `Rent` (layer 2)
 * and `Groceries` (layer 3) stand side by side. `visualNodes(bundle)` gives each node its drawn
 * column in `layer`; the functions below take such rows (`{name, layer}`, `layer` = the column).
 * Grouping by the server layer would put the two in different groups and drop a drag across them.
 *
 * - `orderFromPositions({nodes, coords})`: the order after a drag. `coords[i]` is the position of
 *   `nodes[i]` ACROSS its column (see `axisFor`); inside a layer the smaller coordinate comes first
 *   and a tie keeps the index order. Returns `null` when the numbers cannot be trusted (not one
 *   finite number per node): the caller ignores the drag, it never guesses.
 * - `currentOrder(nodes)`: the order the nodes are drawn in (layer by layer, in figure order).
 * - `sameOrder(a, b)`: both lists hold the same names in the same places.
 * - `axisFor(orientation)`: which of Plotly's `node.x` / `node.y` is the position across a column.
 *   Checked in the browser for both orientations: Plotly keeps its numbers in the flow's own frame, so
 *   `node.y` runs across the columns for `h` (top to bottom) AND for `v` (left to right, scaled by the
 *   wrong side, so a value can exceed 1: only the order matters), while `node.x` is the column.
 * - `namesOf(nodes)` / `layersOf(nodes)`: the names and the names grouped by column.
 * - `visualNodes(bundle)`: `bundle.nodes` with the drawn column in `layer` (see above).
 * - `isAligned(bundle)`: the bars of the drawn bundle can be told apart (one `bundle.nodes` row per
 *   label); `isReorderable(bundle)`: and they can be moved (`arrangement` is not "fixed").
 */

/**
 * @param {string} [_orientation]  "h" or "v"
 * @returns {"y"}
 */
export function axisFor(_orientation) {
  return "y";
}

/**
 * The names grouped by layer, layers ascending, in figure order.
 * @param {{name: string, layer: number}[]} nodes
 * @returns {{layer: number, names: string[]}[]}
 */
export function layersOf(nodes) {
  const byLayer = new Map();
  for (const node of nodes) {
    if (!byLayer.has(node.layer)) {
      byLayer.set(node.layer, []);
    }
    byLayer.get(node.layer).push(node.name);
  }
  return Array.from(byLayer.keys())
    .sort((a, b) => a - b)
    .map((layer) => ({ layer, names: byLayer.get(layer) }));
}

/**
 * @param {{name: string, layer: number}[]} nodes
 * @returns {string[]}
 */
export function currentOrder(nodes) {
  return layersOf(nodes).flatMap((group) => group.names);
}

/**
 * @param {{name: string, layer: number}[]} nodes
 * @returns {string[]} the names in figure order
 */
export function namesOf(nodes) {
  return nodes.map((node) => node.name);
}

/**
 * @param {string[]} a
 * @param {string[]} b
 * @returns {boolean}
 */
export function sameOrder(a, b) {
  return a.length === b.length && a.every((name, index) => name === b[index]);
}

/**
 * @param {{nodes: {name: string, layer: number}[], coords: number[]}} input
 * @returns {string[] | null}
 */
export function orderFromPositions({ nodes, coords }) {
  const usable = Array.isArray(nodes) && Array.isArray(coords) && nodes.length > 0 && coords.length === nodes.length && coords.every((value) => typeof value === "number" && Number.isFinite(value));
  if (!usable) {
    return null;
  }
  const byLayer = new Map();
  nodes.forEach((node, index) => {
    if (!byLayer.has(node.layer)) {
      byLayer.set(node.layer, []);
    }
    byLayer.get(node.layer).push(index);
  });
  return Array.from(byLayer.keys())
    .sort((a, b) => a - b)
    .flatMap((layer) =>
      byLayer
        .get(layer)
        .sort((a, b) => coords[a] - coords[b] || a - b)
        .map((index) => nodes[index].name),
    );
}

/**
 * The rows of `bundle.nodes` with the column each node is drawn in (see the top of this file).
 * A node is in the last column when no drawn link leaves it, else in the column of its layer.
 * @param {{nodes?: {name: string, layer: number}[], figure?: {data?: {link?: {source?: number[]}}[]}}} bundle
 * @returns {{name: string, layer: number}[]}
 */
export function visualNodes(bundle) {
  const nodes = bundle?.nodes ?? [];
  const leaving = new Set(bundle?.figure?.data?.[0]?.link?.source ?? []);
  const last = nodes.reduce((most, node) => Math.max(most, node.layer), 0);
  return nodes.map((node, index) => ({ name: node.name, layer: leaving.has(index) ? node.layer : last }));
}

/**
 * @param {object | null | undefined} bundle
 * @returns {boolean} one `bundle.nodes` row per label of the drawn figure (and at least one)
 */
export function isAligned(bundle) {
  const labels = bundle?.figure?.data?.[0]?.node?.label;
  const nodes = bundle?.nodes;
  return Array.isArray(labels) && Array.isArray(nodes) && nodes.length > 0 && nodes.length === labels.length;
}

/**
 * @param {object | null | undefined} bundle
 * @returns {boolean}
 */
export function isReorderable(bundle) {
  return isAligned(bundle) && bundle.figure.data[0].arrangement !== "fixed";
}
