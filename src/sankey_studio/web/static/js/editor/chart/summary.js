// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The facts under the chart: stats strip, HTML legend, the category table (the donut as numbers,
 * obligatory for light-mode contrast) and the warnings list.
 *
 * `createSummary()` -> `{el, update(bundle | null)}`. Every element exists from the start and is
 * hidden while it has nothing to say, so the panel never reflows when a bundle arrives.
 * Test ids: `stats`, `legend` (+ `legend-item`), `category-table` (+ `category-row`), `warnings`
 * (+ `warning-item`). All text goes through `h()`, so user strings (category and node names, source
 * warnings) can never become markup; colours only appear on swatches.
 */

import { h, uid } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { formatNumber, formatPercent } from "../../core/format.js";
import { swatch } from "../output-panel-kit.js";
import { plainText } from "./errors.js";

const WARNINGS_SHOWN = 3;
const WARNINGS_MAX = 100;
const LEGEND_TITLES = { category: "Categories", layer: "Columns", node: "Nodes" };
const HEX_RE = /^#[0-9a-f]{6}$/i;

function statItem(label, value, hint) {
  return h("div", { class: "out-stat", title: hint ?? null }, h("dt", null, label), h("dd", null, value));
}

function statItems(stats) {
  const cut = stats.drawn_links < stats.links;
  const items = [
    statItem("Nodes", formatNumber(stats.nodes, { maximumFractionDigits: 0 })),
    statItem(
      "Links",
      cut ? `${formatNumber(stats.drawn_links, { maximumFractionDigits: 0 })} of ${formatNumber(stats.links, { maximumFractionDigits: 0 })}` : formatNumber(stats.links, { maximumFractionDigits: 0 }),
      cut ? "The chart draws only the largest links; the table and exports keep all of them." : "Number of source to target links",
    ),
    statItem("Total in", formatNumber(stats.total_in), "Flow that starts the diagram (nodes that only send)"),
    statItem("Total out", formatNumber(stats.total_out), "Flow that ends the diagram (nodes that only receive)"),
    statItem("Columns", formatNumber(stats.layers, { maximumFractionDigits: 0 })),
  ];
  if (stats.category_count > 0) {
    items.push(statItem("Categories", formatNumber(stats.category_count, { maximumFractionDigits: 0 })));
  }
  return items;
}

function legendItem(item) {
  const value = typeof item.value === "number" ? h("span", { class: "out-legend-value nums" }, formatNumber(item.value)) : null;
  return h("li", { class: "legend-item out-legend-item", "data-testid": "legend-item", "data-kind": item.kind }, swatch(item.color, item.kind), h("span", { class: "out-legend-label" }, item.label), value);
}

/** The `#rrggbb` form a colour input takes; anything else (null) makes the input show its default. */
function hexColor(color) {
  return HEX_RE.test(color ?? "") ? color.toLowerCase() : null;
}

/**
 * The swatch of a category row. A real category's swatch is a colour input laid over it: a tap (or
 * Enter) opens the browser's colour picker, and the pick is saved as that category's colour. Other
 * and Uncategorized keep a plain swatch, because their colours are fixed.
 */
function categorySwatch(row, onPick) {
  if (row.kind !== "category") {
    return swatch(row.color, row.kind);
  }
  const input = h("input", {
    type: "color",
    class: "out-colour-input",
    "data-testid": "category-colour",
    "aria-label": `Change the colour of ${row.name}`,
    title: "Change colour",
    value: hexColor(row.color),
    on: { change: (event) => onPick(row.name, event.target.value) },
  });
  return h("span", { class: "out-colour" }, swatch(row.color, row.kind), input);
}

function categoryRow(row, onPick) {
  return h(
    "tr",
    { "data-testid": "category-row", "data-kind": row.kind },
    h("th", { scope: "row" }, h("span", { class: "out-cat-name" }, categorySwatch(row, onPick), h("span", null, row.name))),
    h("td", { class: "num" }, formatNumber(row.value)),
    h("td", { class: "num" }, formatPercent(row.share, 1)),
  );
}

function categoryTable(categories, captionId, onPick) {
  const total = categories.reduce((sum, row) => sum + row.value, 0);
  const share = categories.reduce((sum, row) => sum + row.share, 0);
  return h(
    "table",
    { class: "table out-cat-table", "data-testid": "category-table" },
    h("caption", { id: captionId, class: "visually-hidden" }, "Totals by category: the donut chart as a table"),
    h("thead", null, h("tr", null, h("th", { scope: "col" }, "Category"), h("th", { scope: "col", class: "num" }, "Value"), h("th", { scope: "col", class: "num" }, "Share"))),
    h("tbody", null, categories.map((row) => categoryRow(row, onPick))),
    h("tfoot", null, h("tr", null, h("th", { scope: "row" }, "Total"), h("td", { class: "num" }, formatNumber(total)), h("td", { class: "num" }, formatPercent(Math.min(share, 1), 1)))),
  );
}

class Summary {
  constructor(store) {
    this.store = store;
    this.captionId = uid("cat-caption");
    this.stats = h("dl", { class: "out-stats", "data-testid": "stats", "aria-label": "Chart statistics" });
    this.legendTitle = h("h3", { class: "out-subtitle" });
    this.legendList = h("ul", { class: "legend out-legend", "data-testid": "legend", "aria-label": "Legend" });
    this.legend = h("div", { class: "out-block", hidden: true }, this.legendTitle, this.legendList);
    this.categories = h("div", { class: "out-block", hidden: true });
    this.warnings = h("div", { class: "out-warnings", "data-testid": "warnings", hidden: true });
    this.expanded = false;
    this.lastWarnings = [];
    this.lastKey = "";
    this.renderedKey = "";
    this.el = h("div", { class: "out-summary" }, this.warnings, this.stats, this.legend, this.categories);
  }

  update(bundle) {
    this.stats.hidden = !bundle;
    this.stats.replaceChildren(...(bundle ? statItems(bundle.stats) : []));
    this.updateLegend(bundle?.legend ?? []);
    this.updateCategories(bundle?.categories ?? []);
    this.updateWarnings(bundle?.warnings ?? []);
  }

  updateLegend(items) {
    this.legend.hidden = items.length === 0;
    this.legendTitle.textContent = LEGEND_TITLES[items[0]?.kind] ?? "Legend";
    this.legendList.replaceChildren(...items.map(legendItem));
  }

  updateCategories(categories) {
    this.categories.hidden = categories.length === 0;
    if (categories.length === 0) {
      this.categories.replaceChildren();
      return;
    }
    this.categories.replaceChildren(
      h("h3", { class: "out-subtitle" }, "Totals by category"),
      h("p", { class: "out-note" }, "The donut chart as numbers. Colours never carry the meaning alone."),
      h("div", { class: "table-wrap", role: "region", tabindex: "0", "aria-labelledby": this.captionId }, categoryTable(categories, this.captionId, (name, color) => this.setCategoryColour(name, color))),
    );
  }

  /** Saves a category colour in the draft; the preview redraws, and the table follows the new bundle. */
  setCategoryColour(name, color) {
    this.store.patch(["draft", "style", "category_colors", name], color);
  }

  updateWarnings(warnings) {
    const key = warnings.join("\n");
    if (key !== this.lastKey) {
      this.expanded = false;
    }
    const signature = `${key}\n${this.expanded}`;
    if (signature === this.renderedKey) {
      return;
    }
    this.lastKey = key;
    this.renderedKey = signature;
    this.lastWarnings = warnings;
    this.warnings.hidden = warnings.length === 0;
    if (warnings.length === 0) {
      this.warnings.replaceChildren();
      return;
    }
    const capped = warnings.slice(0, WARNINGS_MAX);
    const shown = this.expanded ? capped : capped.slice(0, WARNINGS_SHOWN);
    this.warnings.replaceChildren(
      icon("alert", { size: 16 }),
      h("div", { class: "out-warnings-body" }, h("ul", { class: "out-warning-list" }, shown.map((text) => h("li", { "data-testid": "warning-item" }, plainText(text)))), this.moreButton(warnings.length - shown.length, warnings.length)),
    );
  }

  moreButton(hidden, total) {
    if (hidden <= 0 && !this.expanded) {
      return null;
    }
    const label = this.expanded ? "Show fewer warnings" : `Show ${hidden} more ${hidden === 1 ? "warning" : "warnings"}${total > WARNINGS_MAX ? " (first 100)" : ""}`;
    return h("button", { type: "button", class: "link-button out-more", "aria-expanded": String(this.expanded), on: { click: () => this.toggle() } }, label);
  }

  toggle() {
    this.expanded = !this.expanded;
    this.updateWarnings(this.lastWarnings);
    this.warnings.querySelector(".out-more")?.focus();
  }
}

/**
 * Creates the summary block. Its category colour squares write `draft.style.category_colors`.
 * @param {{store: object}} ctx  the editor store
 * @returns {{el: HTMLElement, update: (bundle: object | null) => void}}
 */
export function createSummary({ store }) {
  const summary = new Summary(store);
  return { el: summary.el, update: (bundle) => summary.update(bundle) };
}
