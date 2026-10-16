// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * What the editor does with the bars of the drawn Sankey.
 *
 * - `eventsFor(bundle, {edits})` -> `() => ({click, move, start})`: the callbacks `draw(..., {nodeEvents})`
 *   asks at each event (core/chart-nodes.js). It closes over the bundle that was DRAWN, so a
 *   `pointNumber` can never index a newer bundle. A dragged bar becomes an order (node-order.js) and
 *   goes to `edits.reorder` (the engine stores it in `style.node_order`; rows follow best effort). A
 *   drag that ends in the order DRAWN when the press began (`start` reads it from the SVG) changes
 *   nothing; the array order of the figure is no baseline, because without a stored order Plotly
 *   lays the columns out by itself. When the SVG cannot be read every drag is stored.
 *   Nothing is returned for a chart whose nodes cannot be told apart (no `bundle.nodes`, or a count
 *   that differs from the labels) or whose bars cannot move (`arrangement: "fixed"`).
 * - `onNodeClick(bundle, info, {edits})`: a click on a bar opens the "Add a flow" dialog for that node
 *   (F2, node-flow.js); `info` is `{index, node, hasIn, hasOut, clientX, clientY}` with `node` the row
 *   of `bundle.nodes`. It does nothing when there is no such row or no edit engine.
 * - `markNodeOrder(surface, bundle)`: sets `data-node-order` on the chart (the node names in drawn
 *   order, joined by `|`), the wait signal of tests and scripts; `null` removes it.
 * - `mountNodeTools({store, tools, edits, surface})` -> `{dispose}`: the "Reset order" and "Order
 *   nodes" buttons in the chart header tools.
 */

import { openNodeFlow } from "./node-flow.js";
import { mountOrderDialog, visibleCoords } from "./order-dialog.js";
import { mountOrderReset } from "./order-reset.js";
import { axisFor, isAligned, isReorderable, namesOf, orderFromPositions, sameOrder, visualNodes } from "./node-order.js";

function traceOf(bundle) {
  return bundle?.figure?.data?.[0];
}

/**
 * F2: a click on a bar opens the "Add a flow" dialog for that node.
 * @param {object} bundle  the drawn bundle
 * @param {{index: number, node?: object | null}} info  `node` is the row of `bundle.nodes`
 * @param {{edits?: object}} [deps]
 * @returns {void}
 */
export function onNodeClick(bundle, info, deps = {}) {
  void bundle;
  void openNodeFlow({ edits: deps.edits, node: info?.node });
}

/**
 * The order the bars are drawn in right now, read from the SVG (null: it cannot be read).
 * Without a stored order Plotly lays the columns out by itself, so this can differ from the order of
 * the figure's arrays.
 */
function drawnOrder(bundle, surface) {
  const nodes = visualNodes(bundle);
  const coords = surface ? visibleCoords(surface, traceOf(bundle).orientation, nodes.length) : null;
  return coords && orderFromPositions({ nodes, coords });
}

/** `before` is the order drawn when the press began; a drag that ends in it changed nothing. */
function moved(bundle, edits, { positions, before }) {
  const nodes = visualNodes(bundle);
  const coords = positions[`${axisFor(traceOf(bundle).orientation)}s`];
  const order = orderFromPositions({ nodes, coords });
  if (!order || (before && sameOrder(order, before))) {
    return;
  }
  void edits.reorder(order);
}

/**
 * @param {object} bundle  the bundle that was drawn
 * @param {{edits: {reorder: (order: string[]) => Promise<object>}, click?: (bundle: object, info: object, options?: object) => void}} options
 * @returns {() => ({click?: Function, move?: Function})}
 */
export function eventsFor(bundle, options) {
  const nodes = bundle?.nodes ?? [];
  const click = (info) => (options.click ?? onNodeClick)(bundle, { ...info, node: nodes[info.index] ?? null }, options);
  let before = null; // the drawn order at the start of the gesture in progress
  const reorderable = isReorderable(bundle);
  const listeners = {
    click: isAligned(bundle) ? click : undefined,
    start: reorderable
      ? (surface) => {
          before = drawnOrder(bundle, surface);
        }
      : undefined,
    move: reorderable
      ? (positions) => {
          const start = before;
          before = null;
          moved(bundle, options.edits, { positions, before: start });
        }
      : undefined,
  };
  return () => listeners;
}

/**
 * @param {HTMLElement} surface  the chart div
 * @param {object | null} bundle  the bundle that was drawn (null: nothing is drawn)
 */
export function markNodeOrder(surface, bundle) {
  if (isAligned(bundle)) {
    surface.dataset.nodeOrder = namesOf(bundle.nodes).join("|");
  } else {
    delete surface.dataset.nodeOrder;
  }
}

/**
 * @param {{store: object, tools: HTMLElement, edits: object, surface: HTMLElement}} deps
 * @returns {{dispose: () => void}}
 */
export function mountNodeTools({ store, tools, edits, surface }) {
  const dialog = mountOrderDialog({ store, tools, edits, surface });
  const reset = mountOrderReset({ store, tools, edits });
  return {
    dispose: () => {
      dialog.dispose();
      reset.dispose();
    },
  };
}
