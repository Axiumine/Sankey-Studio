// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The chart card of the viewer: tabs Sankey | Donut, the Plotly charts, and everything that is
 * their HTML twin (legend list, category table, links table, donut hint).
 *
 * - The Donut tab exists only when the bundle says `donut_available`; otherwise a hint explains
 *   how to categorise entries (`donut-hint`). A donut whose basis selects nothing
 *   (`donut_empty_reason: "basis_empty"`) shows a hint inside its panel instead.
 * - Figures are the server's, drawn as given (core/chart.js `draw`). Dark mode is a new request
 *   with `?theme=`; `update(bundle, theme)` then redraws in place (Plotly.react), so nothing jumps.
 *   The donut is drawn when its tab is first opened (a hidden chart has no size to draw at).
 *
 * - At the right of the tab row sit the chart tools: the display menu (display-menu.js), the
 *   switches for the values and percentages printed on the charts (`display.onChange(key, on)` is
 *   the page's), and whatever the page adds with `addTool` (the export menu, export-menu.js).
 *
 * Test ids: chart-tab-sankey, chart-tab-donut, sankey-chart, donut-chart, donut-hint,
 * category-details (and the ones of display-menu.js, parts.js and links-table.js).
 */

import { announce } from "../core/a11y.js";
import { createChartFrame, disposeChart, draw, withoutLegend } from "../core/chart.js";
import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { stripBidi } from "../core/text.js";
import { errorState, loadingState } from "../core/states.js";
import { createTabs } from "../core/tabs.js";
import { createDisplayMenu } from "./display-menu.js";
import { CHART_CONFIG_OVERRIDE, fitFigure } from "./figure.js";
import { createLinksTable } from "./links-table.js";
import { categoryTable, legendList, tableDisclosure, valueSuffix } from "./parts.js";

const DEFAULT_HEIGHT = 560;
const BASIS_NOTES = {
  all: "The donut adds up every link, so a flow that passes through several steps counts once at each step.",
  initial: "The donut counts only the links that start at a source node.",
  terminal: "The donut counts only the links that end at a final node.",
};

function slot(testid, height) {
  const { frame, surface } = createChartFrame({ height });
  surface.dataset.testid = testid;
  const overlay = h("div", { class: "chart-overlay" }, loadingState({ label: "Drawing the chart", block: true }));
  frame.append(overlay);
  return { frame, surface, overlay, drawn: false };
}

function figureHeight(figure) {
  const height = figure?.layout?.height;
  return Number.isFinite(height) ? height : DEFAULT_HEIGHT;
}

function donutHint(bundle) {
  const text = bundle.donut_available
    ? "The donut basis you chose (first or last step of the flow) leaves no categorised links to draw. Change the basis under Style in the editor."
    : "Want a donut? Give your links a category: add a category column to the data, or set categories in the entries table of the editor. The Donut tab appears as soon as one link has a category.";
  return h("p", { class: "chart-hint", "data-testid": "donut-hint" }, icon("pie-chart", { size: 16 }), h("span", null, text));
}

class Charts {
  /** @param {{bundle: object, graph: {id: string, name: string}, display: {values: object, onChange: (key: string, on: boolean) => void}, onTab?: (id: string) => void}} options */
  constructor({ bundle, graph, display, onTab }) {
    this.graph = graph;
    this.bundle = bundle;
    this.theme = "light";
    this.onTab = onTab;
    this.sankey = slot("sankey-chart", figureHeight(bundle.figure));
    this.donut = bundle.donut_available ? slot("donut-chart", figureHeight(bundle.donut)) : null;
    this.legendHolder = h("div", { class: "legend-block" });
    this.categoryHolder = h("div", { class: "stack stack-sm" });
    this.links = createLinksTable(graph);
    this.menu = createDisplayMenu({ values: display.values, donut: this.donut !== null, onChange: display.onChange });
    this.tools = h("div", { class: "chart-tools" }, this.menu.el);
    this.tabs = createTabs({ label: "Chart type", tabs: this.tabList(), actions: this.tools, onSelect: (id) => this.selected(id) });
    this.el = h("div", { class: "card chart-card" }, h("div", { class: "card-body" }, h("h2", { class: "visually-hidden" }, "Chart"), this.tabs.el));
  }

  tabList() {
    const hint = this.donut ? null : donutHint(this.bundle);
    const sankeyPanel = h("div", { class: "chart-panel" }, this.sankey.frame, this.legendHolder, hint, this.links.el);
    const tabs = [{ id: "sankey", label: "Sankey", content: sankeyPanel, testid: "chart-tab-sankey" }];
    if (this.donut) {
      const panel = h("div", { class: "chart-panel" }, this.donut.frame, this.categoryHolder);
      tabs.push({ id: "donut", label: "Donut", content: panel, testid: "chart-tab-donut" });
    }
    return tabs;
  }

  selected(id) {
    const changed = this.shown !== undefined && this.shown !== id;
    this.shown = id;
    this.onTab?.(id);
    if (id === "donut" && this.donut && !this.donut.drawn) {
      this.drawDonut();
    }
    if (changed) {
      announce(id === "donut" ? "Donut chart" : "Sankey chart");
    }
  }

  /** Adds a control (an icon button with its popover) after the display menu, at the right of the tab row. */
  addTool(el) {
    this.tools.append(el);
  }

  /** Remembers the donut basis ("all", "initial", "terminal") for the note under the donut. */
  setBasis(basis) {
    this.basis = basis;
  }

  /** The tab that is showing: "sankey" or "donut". */
  active() {
    return this.tabs.selected() ?? "sankey";
  }

  /** The Plotly div of a chart (for the client-side image fallback), or null. */
  surface(kind) {
    return (kind === "donut" ? this.donut : this.sankey)?.surface ?? null;
  }

  async drawSlot(target, figure, label) {
    target.frame.style.setProperty("--chart-h", `${figureHeight(figure)}px`);
    try {
      await draw(target.surface, fitFigure(figure), { theme: this.theme, label: stripBidi(label), config: CHART_CONFIG_OVERRIDE });
      target.drawn = true;
      target.overlay?.remove();
      target.overlay = null;
    } catch {
      target.overlay?.remove();
      target.overlay = h("div", { class: "chart-overlay" }, errorState({ title: "The chart could not be drawn", message: "The chart library did not load. Reload the page to try again.", compact: true }));
      target.frame.append(target.overlay);
    }
  }

  drawDonut() {
    const { name } = this.graph;
    return this.drawSlot(this.donut, this.bundle.donut, `Donut chart of the categories in ${name}`);
  }

  /**
   * Shows a (new) bundle: redraws the charts, legend and tables.
   * @param {object} bundle
   * @param {string} theme  "light" or "dark", the colours the bundle was drawn with
   */
  async update(bundle, theme) {
    this.bundle = bundle;
    this.theme = theme;
    const suffix = valueSuffix(bundle.figure);
    const { stats } = bundle;
    const label = `Sankey diagram of ${this.graph.name}: ${stats.nodes} nodes and ${stats.links} links. The links table below has the same data.`;
    this.legendHolder.replaceChildren(...(bundle.legend.length > 0 ? [h("h3", { class: "legend-title" }, "Legend"), legendList(bundle.legend, { suffix })] : []));
    this.links.update(bundle, suffix);
    const jobs = [this.drawSlot(this.sankey, withoutLegend(bundle.figure), label)];
    if (this.donut) {
      this.categoryHolder.replaceChildren(...this.donutExtras(bundle, suffix));
      if (this.donut.drawn || this.active() === "donut") {
        jobs.push(this.drawDonut());
      }
    }
    await Promise.all(jobs);
  }

  donutExtras(bundle, suffix) {
    if (bundle.categories.length === 0) {
      return [donutHint(bundle)];
    }
    const basis = BASIS_NOTES[this.basis];
    const table = categoryTable(bundle.categories, { suffix, caption: `Categories of ${this.graph.name}, as a table` });
    // the holder is rebuilt on every redraw (theme, display switch): a block the person opened stays open
    const open = this.categoryHolder.querySelector("details")?.open ?? false;
    return [
      ...(basis ? [h("p", { class: "hint donut-basis" }, basis)] : []),
      tableDisclosure({ testid: "category-details", label: "Table view of the categories", open }, table),
    ];
  }

  /** Puts a display switch back to `on` (the redraw with the other value failed). */
  setSwitch(key, on) {
    this.menu.set(key, on);
  }

  dispose() {
    this.menu.dispose();
    disposeChart(this.sankey.surface);
    if (this.donut) {
      disposeChart(this.donut.surface);
    }
  }
}

/**
 * Builds the chart card (call `update` to fill it).
 * @param {{bundle: object, graph: {id: string, name: string}, display: {values: object, onChange: (key: string, on: boolean) => void}, onTab?: (id: string) => void}} options
 * @returns {Charts}
 */
export function createCharts(options) {
  return new Charts(options);
}
