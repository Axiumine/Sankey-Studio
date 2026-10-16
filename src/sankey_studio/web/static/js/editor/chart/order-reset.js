// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The "Reset order" button of the chart header (`chart-reset-order`).
 *
 * Shown while the graph keeps a node order (`draft.style.node_order` is not empty): it sends the
 * chart back to the automatic layout. `mountOrderReset({store, tools, edits}) -> {button, dispose}`
 * adds the button to the chart header tools (`ctx.chartTools`, before the gear) and keeps it in step with the store.
 */

import { h } from "../../core/dom.js";
import { icon } from "../../core/icons.js";

const LABEL = "Reset order";
const GEAR = '[data-testid="chart-settings-button"]';
const HINT = "Go back to the automatic order of the nodes";

/**
 * Puts a button into the chart header tools just before the chart settings gear (the gear stays the
 * last tool: its popover opens under it and must keep the room at the right edge).
 * @param {HTMLElement} tools
 * @param {HTMLElement} button
 */
export function addTool(tools, button) {
  tools.insertBefore(button, tools.querySelector(GEAR));
}

/**
 * @param {{store: object, tools: HTMLElement, edits: {resetOrder: () => Promise<object>}}} deps
 * @returns {{button: HTMLButtonElement, dispose: () => void}}
 */
export function mountOrderReset({ store, tools, edits }) {
  const button = h(
    "button",
    { type: "button", class: "btn btn-sm", hidden: true, title: HINT, "data-testid": "chart-reset-order", on: { click: () => void edits.resetOrder() } },
    icon("refresh", { size: 14 }),
    LABEL,
  );
  const sync = (order) => {
    button.hidden = !(Array.isArray(order) && order.length > 0);
  };
  addTool(tools, button);
  const off = store.subscribe(sync, { select: (state) => state.draft?.style?.node_order, immediate: true });
  return {
    button,
    dispose: () => {
      off();
      button.remove();
    },
  };
}
