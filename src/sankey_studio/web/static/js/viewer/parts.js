// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Read-only building blocks that show a RenderBundle as HTML: the legend list, the category table
 * (the accessible twin of the donut), the stats strip, the warnings list and the "Table view"
 * disclosure that holds a table. The compare page reuses them.
 *
 * Colours: a swatch takes its colour from the server (`legend[].color`, `categories[].color`); text
 * is always ink. Every label is a text node. Test ids: legend / legend-item, category-table /
 * category-row, stats, warnings / warning-item (and the one `tableDisclosure` is given).
 */

import { h } from "../core/dom.js";
import { formatNumber, formatPercent } from "../core/format.js";
import { icon } from "../core/icons.js";

/**
 * A CSS colour the browser accepts, else the muted token.
 * @param {unknown} color
 * @returns {string}
 */
export function swatchColor(color) {
  return typeof color === "string" && CSS.supports("color", color) ? color : "var(--muted)";
}

/**
 * A colour chip (decorative; the label next to it carries the meaning).
 * @param {unknown} color
 * @returns {HTMLElement}
 */
export function swatch(color) {
  return h("span", { class: "swatch", style: { background: swatchColor(color) }, "aria-hidden": "true" });
}

/**
 * The unit text of the Sankey trace (`style.value_suffix`), shown after values. The server
 * escapes it for Plotly (`<` is `&lt;`); this undoes that, so the DOM text is what the person typed.
 * @param {{data?: {valuesuffix?: string}[]}} figure
 * @returns {string}
 */
export function valueSuffix(figure) {
  const escaped = String(figure?.data?.[0]?.valuesuffix ?? "");
  return escaped.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

function amount(value, suffix) {
  return `${formatNumber(value)}${suffix}`;
}

/**
 * The in-figure legend as an HTML list.
 * @param {{label: string, color: string, kind: string, value: number | null}[]} items
 * @param {{suffix?: string}} [options]
 * @returns {HTMLElement}
 */
export function legendList(items, options = {}) {
  const suffix = options.suffix ?? "";
  return h(
    "ul",
    { class: "legend", role: "list", "aria-label": "Legend", "data-testid": "legend" },
    items.map((item) =>
      h(
        "li",
        { class: "legend-item", "data-testid": "legend-item", "data-kind": item.kind },
        swatch(item.color),
        h("span", { class: "legend-label" }, item.label),
        item.value == null ? null : h("span", { class: "legend-value nums text-muted" }, amount(item.value, suffix)),
      ),
    ),
  );
}

/**
 * A closed `<details>` whose summary reads as a link: the HTML twin of a chart (a table) stays out
 * of sight until the person asks for it. The links table and the category table share it.
 * @param {{testid: string, label: string, open?: boolean}} options
 * @param {...(Node | null)} children  what shows when the block is open
 * @returns {HTMLElement}
 */
export function tableDisclosure({ testid, label, open = false }, ...children) {
  return h("details", { class: "table-view", "data-testid": testid, open }, h("summary", null, label), ...children);
}

const KIND_NOTES = {
  uncategorized: "Entries without a category",
  other: "Smaller categories combined",
};

function categoryRow(item, suffix) {
  const note = KIND_NOTES[item.kind];
  return h(
    "tr",
    { "data-testid": "category-row", "data-category": item.name, "data-kind": item.kind },
    h("th", { scope: "row" }, h("span", { class: "cell-key" }, swatch(item.color), h("span", null, item.name)), note ? h("span", { class: "cell-note text-muted" }, note) : null),
    h("td", { class: "num" }, amount(item.value, suffix)),
    h("td", { class: "num" }, formatPercent(item.share)),
  );
}

/**
 * The donut as a table: category, value, share, plus a total row.
 * @param {{name: string, color: string, value: number, share: number, kind: string}[]} categories
 * @param {{suffix?: string, caption?: string}} [options]
 * @returns {HTMLElement}
 */
export function categoryTable(categories, options = {}) {
  const suffix = options.suffix ?? "";
  const total = categories.reduce((sum, item) => sum + item.value, 0);
  return h(
    "div",
    { class: "table-wrap", role: "region", tabindex: "0", "aria-label": options.caption ?? "Categories as a table" },
    h(
      "table",
      { class: "table category-table", "data-testid": "category-table" },
      h("caption", { class: "visually-hidden" }, options.caption ?? "Categories as a table"),
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Category"), h("th", { scope: "col", class: "num" }, "Value"), h("th", { scope: "col", class: "num" }, "Share"))),
      h("tbody", null, categories.map((item) => categoryRow(item, suffix))),
      h("tfoot", null, h("tr", null, h("th", { scope: "row" }, "Total"), h("td", { class: "num" }, amount(total, suffix)), h("td", { class: "num" }, formatPercent(total > 0 ? 1 : 0)))),
    ),
  );
}

function tile(label, value) {
  return h("div", { class: "stat" }, h("div", { class: "stat-label" }, label), h("div", { class: "stat-value nums" }, value));
}

/**
 * The numbers strip: flow in/out and categories.
 * @param {{total_in: number, total_out: number, category_count: number}} stats
 * @param {{suffix?: string}} [options]
 * @returns {HTMLElement}
 */
export function statsStrip(stats, options = {}) {
  const suffix = options.suffix ?? "";
  return h(
    "div",
    { class: "stat-grid", role: "group", "aria-label": "Graph statistics", "data-testid": "stats" },
    tile("Total in", amount(stats.total_in, suffix)),
    tile("Total out", amount(stats.total_out, suffix)),
    tile("Categories", formatNumber(stats.category_count, { maximumFractionDigits: 0 })),
  );
}

/**
 * The warnings of the render (skipped rows, cut links, broken cycles), or null when there are none.
 * @param {string[]} warnings
 * @returns {HTMLElement | null}
 */
export function warningsList(warnings) {
  if (warnings.length === 0) {
    return null;
  }
  return h(
    "section",
    { class: "notice viewer-warnings", "data-kind": "warning", "data-testid": "warnings", "aria-label": "Warnings" },
    icon("alert", { size: 18 }),
    h(
      "div",
      { class: "notice-body" },
      h("p", { class: "text-strong" }, warnings.length === 1 ? "One thing to know" : `${warnings.length} things to know`),
      h("ul", { class: "warning-list", role: "list" }, warnings.map((text) => h("li", { "data-testid": "warning-item" }, text))),
    ),
  );
}
