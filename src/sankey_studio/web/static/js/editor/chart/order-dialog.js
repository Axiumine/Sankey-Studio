// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * "Order nodes": the keyboard and single-pointer twin of dragging a bar (WCAG 2.1.1, 2.5.7).
 *
 * `mountOrderDialog({store, tools, edits, surface}) -> {button, dispose}` adds the button
 * `chart-order-open` ("Order nodes") to the chart header tools. It opens the modal `order-dialog`:
 * the nodes of the drawn chart, column by column, each with `order-up` and `order-down` buttons
 * (their accessible names name the node). Every press calls the SAME `edits.reorder` as a drag, with the
 * whole order, so the order is stored in the graph (and the rows follow when the engine can).
 * "Done" closes. The list is the order the chart is DRAWN in, read from the SVG (the automatic layout
 * is not always the order of the data); it keeps its own order while a new preview is on its way and
 * starts again only when the set of nodes changes.
 * The button is disabled while there is nothing to order or the nodes cannot move ("Dragging nodes:
 * Fixed").
 */

import { announce } from "../../core/a11y.js";
import { openDialog } from "../../core/dialog.js";
import { h } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { addTool } from "./order-reset.js";
import { currentOrder, isReorderable, layersOf, orderFromPositions, visualNodes } from "./node-order.js";

const INTRO = "Move a node up or down inside its column. Each change is saved with this graph, like dragging the node in the chart.";
const WAIT = "No nodes to order yet.";
const FIXED = "The nodes cannot move while Dragging nodes is set to Fixed.";

/**
 * Where each bar of the drawn chart stands across its column, indexed by `pointNumber`.
 * @param {ParentNode} surface  the chart div
 * @param {string | undefined} orientation  "h" or "v"
 * @param {number} count  how many nodes the bundle lists
 * @returns {number[] | null}  null when the drawing cannot be read
 */
export function visibleCoords(surface, orientation, count) {
  const coords = new Array(count).fill(Number.NaN);
  for (const bar of surface.querySelectorAll(".sankey-node")) {
    const index = bar.__data__?.node?.pointNumber;
    const box = bar.querySelector(".node-rect")?.getBoundingClientRect();
    if (Number.isInteger(index) && index >= 0 && index < count && box) {
      coords[index] = orientation === "v" ? box.left + box.width / 2 : box.top + box.height / 2;
    }
  }
  return coords.every(Number.isFinite) ? coords : null;
}

/**
 * The columns to list: the nodes as drawn, grouped by drawn column.
 * @param {object} bundle  the drawn bundle (`isReorderable`)
 * @param {ParentNode} surface
 * @returns {{layer: number, names: string[]}[]}
 */
export function listColumns(bundle, surface) {
  const nodes = visualNodes(bundle);
  const orientation = bundle.figure.data[0].orientation;
  const coords = visibleCoords(surface, orientation, nodes.length);
  const order = (coords && orderFromPositions({ nodes, coords })) || currentOrder(nodes);
  const layerOf = new Map(nodes.map((node) => [node.name, node.layer]));
  return layersOf(order.map((name) => ({ name, layer: layerOf.get(name) })));
}

function sameNames(columns, bundle) {
  const names = new Set(columns.flatMap((column) => column.names));
  const fresh = visualNodes(bundle);
  return fresh.length === names.size && fresh.every((node) => names.has(node.name));
}

class OrderList {
  constructor(columns, edits) {
    this.columns = columns;
    this.edits = edits;
    this.el = h("div", { class: "order-list stack" });
    this.buttons = [];
    this.render();
  }

  render() {
    this.buttons = [];
    const total = this.columns.length;
    this.el.replaceChildren(h("p", { class: "text-muted text-sm" }, INTRO), ...this.columns.map((column, c) => this.column(column, c, total)));
  }

  column(column, c, total) {
    const rows = column.names.map((name, i) => this.row(name, c, i, column.names.length));
    return h("section", { class: "order-column stack stack-sm" }, h("h3", { class: "order-column-title text-strong" }, `Column ${c + 1} of ${total}`), h("ol", { class: "order-nodes list-reset stack stack-sm" }, rows));
  }

  row(name, c, i, count) {
    const up = this.button("order-up", "Up", `Move ${name} up`, i === 0, () => this.shift(c, i, -1));
    const down = this.button("order-down", "Down", `Move ${name} down`, i === count - 1, () => this.shift(c, i, 1));
    (this.buttons[c] ??= [])[i] = { up, down };
    return h("li", { class: "order-node cluster cluster-between" }, h("span", { class: "order-node-name grow" }, name), h("span", { class: "order-node-moves cluster" }, up, down));
  }

  button(testid, text, label, disabled, onClick) {
    return h("button", { type: "button", class: "btn btn-sm", "aria-label": label, disabled, "data-testid": testid, on: { click: onClick } }, text);
  }

  /** Swaps a node with its neighbour in the column, keeps the focus on it and stores the order. */
  shift(c, i, delta) {
    const names = this.columns[c].names;
    const name = names[i];
    [names[i], names[i + delta]] = [names[i + delta], names[i]];
    this.render();
    const pair = this.buttons[c][i + delta];
    const first = delta < 0 ? pair.up : pair.down;
    (first.disabled ? (delta < 0 ? pair.down : pair.up) : first).focus();
    announce(`${name} moved to position ${i + delta + 1} of ${names.length}`);
    void this.edits.reorder(this.columns.flatMap((column) => column.names));
  }
}

function reason(bundle) {
  if (!bundle?.nodes?.length) {
    return WAIT;
  }
  return isReorderable(bundle) ? "" : FIXED;
}

/**
 * @param {{store: object, tools: HTMLElement, edits: {reorder: Function}, surface: HTMLElement}} deps
 * @returns {{button: HTMLButtonElement, dispose: () => void}}
 */
export function mountOrderDialog({ store, tools, edits, surface }) {
  const button = h("button", { type: "button", class: "btn btn-sm", "data-testid": "chart-order-open", on: { click: () => open() } }, icon("sort", { size: 14 }), "Order nodes");
  let dialog = null;
  let stop = null;
  const sync = (bundle) => {
    const why = reason(bundle);
    button.disabled = why !== "";
    button.title = why || "Change the order of the nodes with buttons instead of dragging";
  };
  function open() {
    const bundle = store.get().bundle;
    if (dialog || reason(bundle)) {
      return;
    }
    const list = new OrderList(listColumns(bundle, surface), edits);
    dialog = openDialog({
      title: "Order nodes",
      body: list.el,
      testid: "order-dialog",
      actions: [{ label: "Done", value: true, kind: "primary" }],
      initialFocus: (el) => el.querySelector('[data-testid="order-up"]:not([disabled]), [data-testid="order-down"]:not([disabled])'),
    });
    stop = store.subscribe(
      (fresh) => {
        if (isReorderable(fresh) && !sameNames(list.columns, fresh)) {
          list.columns = listColumns(fresh, surface);
          list.render();
        }
      },
      { select: (state) => state.bundle },
    );
    void dialog.result.then(() => {
      stop();
      dialog = null;
    });
  }
  addTool(tools, button);
  const off = store.subscribe(sync, { select: (state) => state.bundle, immediate: true });
  return {
    button,
    dispose: () => {
      off();
      stop?.();
      dialog?.close();
      button.remove();
    },
  };
}
