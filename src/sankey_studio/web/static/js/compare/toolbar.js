// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The strip above the compare grid: what is compared, the shared-colour note with its legend, the
 * "add a graph" control, and the cap message.
 *
 * - `colourNote(bundles)` builds the note that lists every category of the drawn graphs once, with
 *   the colour all cards use for it (the server draws a compare set with ONE category colour map);
 *   null when no graph has categories. The page places it just above the grid.
 * - `setLibrary(graphs)` fills the add menu (graphs not yet in the comparison). At the cap
 *   (`MAX_COMPARE`) the menu is replaced by `compare-limit-message`.
 *
 * Test ids: compare-limit-message, compare-add-select, compare-add, compare-shared-colours.
 */

import { announce } from "../core/a11y.js";
import { h, uid } from "../core/dom.js";
import { formatCount } from "../core/format.js";
import { icon } from "../core/icons.js";
import { MAX_COMPARE } from "../library/state.js";
import { swatch } from "../viewer/parts.js";

/**
 * The category colours of a set of bundles, first spelling and first colour winning.
 * @param {object[]} bundles
 * @returns {{name: string, color: string}[]}
 */
export function sharedCategories(bundles) {
  const seen = new Map();
  for (const bundle of bundles) {
    for (const item of bundle.categories ?? []) {
      if (item.kind === "category" && !seen.has(item.name)) {
        seen.set(item.name, item.color);
      }
    }
  }
  return Array.from(seen, ([name, color]) => ({ name, color }));
}

function colourNote(items) {
  if (items.length === 0) {
    return null;
  }
  const legend = h(
    "ul",
    { class: "legend", role: "list", "aria-label": "Category colours shared by all cards" },
    items.map((item) => h("li", { class: "legend-item" }, swatch(item.color), h("span", null, item.name))),
  );
  return h(
    "div",
    { class: "shared-colours", "data-testid": "compare-shared-colours" },
    h("p", { class: "text-sm text-muted" }, "Every card uses one colour map for categories, so a category looks the same in every graph."),
    legend,
  );
}

function addControl(onAdd) {
  const select = h("select", { class: "select", id: uid("compare-add"), "data-testid": "compare-add-select", disabled: true }, h("option", { value: "" }, "Loading graphs"));
  const button = h("button", { type: "button", class: "btn", disabled: true, "data-testid": "compare-add", on: { click: () => select.value && onAdd(select.value) } }, icon("plus", { size: 14 }), "Add");
  const el = h("div", { class: "compare-add" }, h("label", { class: "text-sm text-muted", for: select.id }, "Add a graph"), select, button);
  return { el, select, button };
}

/**
 * @param {{onAdd: (id: string) => void}} options
 * @returns {{el: HTMLElement, countEl: HTMLElement, colourNote: (bundles: object[]) => HTMLElement | null, setLibrary: (graphs: object[], inUse: string[]) => void, setCount: (count: number, inUse?: string[]) => void}}
 */
export function createCompareToolbar({ onAdd }) {
  const heading = h("p", { class: "compare-count text-strong", role: "status", tabindex: "-1" });
  const add = addControl(onAdd);
  const limit = h("p", { class: "compare-limit text-sm", role: "status", hidden: true, "data-testid": "compare-limit-message" }, icon("info", { size: 14 }), `You are comparing ${MAX_COMPARE} graphs, the most this page can draw. Remove one to add another.`);
  const el = h("section", { class: "compare-toolbar stack stack-sm", "aria-label": "Comparison" }, h("div", { class: "compare-toolbar-row" }, heading, add.el, limit));
  let library = null;
  let used = [];
  let count = 0;

  // the control is there from the first paint (disabled while the list loads), so nothing moves
  const refresh = () => {
    const full = count >= MAX_COMPARE;
    const choices = (library ?? []).filter((graph) => !used.includes(graph.id));
    limit.hidden = !full;
    add.el.hidden = full || (library !== null && choices.length === 0);
    if (library !== null) {
      add.select.replaceChildren(...choices.map((graph) => h("option", { value: graph.id }, graph.name)));
      add.select.disabled = false;
      add.button.disabled = false;
    }
  };
  return {
    el,
    /** The "Comparing N graphs" line: focusable, the place to land when no card is left. */
    countEl: heading,
    colourNote: (bundles) => colourNote(sharedCategories(bundles)),
    setLibrary(graphs, inUse) {
      library = graphs;
      used = inUse;
      refresh();
    },
    setCount(next, inUse = used) {
      const changed = next !== count;
      count = next;
      used = inUse;
      heading.textContent = next === 0 ? "No graphs in the comparison" : `Comparing ${formatCount(next, "graph")}`;
      refresh();
      if (changed && next >= MAX_COMPARE) {
        announce(`You are comparing ${MAX_COMPARE} graphs, the most this page can draw.`);
      }
    },
  };
}
