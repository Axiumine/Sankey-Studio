// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * One card of the compare grid.
 *
 * A card shows: the graph name (link to the viewer), a Sankey/Donut switch, a remove button, the
 * chart, and a summary table (the accessible numbers of the graph). The chart is drawn lazily
 * (when the card comes near the viewport) and the donut only when it is first asked for. The
 * figures are the server's; viewer/figure.js only sets the height and drops the repeated title, so
 * a grid of cards stays compact (colours and everything else are untouched).
 *
 * Other card kinds: a placeholder for a graph that no longer exists (`compare-missing`) and a
 * card with the server's message for a graph that cannot be built.
 *
 * Test ids: compare-card (data-graph-id, data-chart), compare-card-toggle (one switch per card,
 * `role=switch`, aria-checked = the donut is showing), compare-missing, compare-remove.
 */

import { createChartFrame, disposeChart, draw } from "../core/chart.js";
import { h } from "../core/dom.js";
import { formatNumber } from "../core/format.js";
import { icon } from "../core/icons.js";
import { errorState, loadingState } from "../core/states.js";
import { stripBidi } from "../core/text.js";
import { graphHref } from "../library/data.js";
import { CHART_CONFIG_OVERRIDE, fitFigure } from "../viewer/figure.js";
import { valueSuffix } from "../viewer/parts.js";

function title(graph) {
  return h("h2", { class: "compare-card-title" }, h("a", { class: "card-link", href: graphHref(graph.id), title: graph.name }, graph.name));
}

function removeButton(graph, onRemove) {
  return h(
    "button",
    { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": `Remove “${graph.name}” from the comparison`, title: "Remove from the comparison", "data-testid": "compare-remove", on: { click: () => onRemove(graph) } },
    icon("x", { size: 14 }),
  );
}

function summaryTable(graph, bundle) {
  const { stats } = bundle;
  const suffix = valueSuffix(bundle.figure);
  const whole = (value) => formatNumber(value, { maximumFractionDigits: 0 });
  const rows = [
    ["Nodes", whole(stats.nodes)],
    ["Links", stats.drawn_links < stats.links ? `${whole(stats.links)} (${whole(stats.drawn_links)} drawn)` : whole(stats.links)],
    ["Total in", `${formatNumber(stats.total_in)}${suffix}`],
    ["Total out", `${formatNumber(stats.total_out)}${suffix}`],
    ["Layers", whole(stats.layers)],
    ["Categories", whole(stats.category_count)],
  ];
  return h(
    "table",
    { class: "summary-table" },
    h("caption", { class: "visually-hidden" }, `Summary of ${graph.name}`),
    h("tbody", null, rows.map(([label, value]) => h("tr", null, h("th", { scope: "row" }, label), h("td", { class: "num" }, value)))),
  );
}

function warningsBlock(warnings) {
  if (warnings.length === 0) {
    return null;
  }
  return h(
    "details",
    { class: "compare-warnings" },
    h("summary", null, icon("alert", { size: 14 }), warnings.length === 1 ? "1 warning" : `${warnings.length} warnings`),
    h("ul", { class: "warning-list", role: "list" }, warnings.map((text) => h("li", null, text))),
  );
}

function plot(testid, height) {
  const { frame, surface } = createChartFrame({ height });
  surface.dataset.testid = testid;
  frame.append(h("div", { class: "chart-overlay" }, loadingState({ label: "Drawing the chart", block: true })));
  return { frame, surface, drawn: false };
}

/** A card with a chart. */
class ChartCard {
  /** @param {{graph: object, bundle: object, height: number, chart: string, theme: string, onRemove: Function}} options */
  constructor({ graph, bundle, height, chart, theme, onRemove }) {
    this.graph = graph;
    this.theme = theme;
    this.bundle = bundle;
    this.height = height;
    this.sankey = plot("sankey-chart", height);
    this.donut = bundle.donut_available ? plot("donut-chart", height) : null;
    this.toggle = this.buildToggle();
    this.el = h(
      "article",
      { class: "card compare-card", "data-testid": "compare-card", "data-graph-id": graph.id, "data-chart": "sankey" },
      h("header", { class: "compare-card-head" }, title(graph), this.toggle, removeButton(graph, onRemove)),
      this.sankey.frame,
      this.donut ? this.donut.frame : null,
      h("div", { class: "compare-card-body" }, summaryTable(graph, bundle), warningsBlock(bundle.warnings)),
    );
    this.show(chart === "donut" && this.donut ? "donut" : "sankey");
  }

  buildToggle() {
    const toggle = h(
      "button",
      {
        type: "button",
        class: "chart-switch",
        role: "switch",
        "aria-checked": "false",
        "aria-disabled": this.donut ? null : "true",
        "aria-label": `Show the donut chart of “${this.graph.name}”`,
        title: this.donut ? "Switch between the Sankey and the donut" : "No categories, so there is no donut chart",
        "data-testid": "compare-card-toggle",
        on: { click: () => this.donut && this.show(this.chart === "donut" ? "sankey" : "donut") },
      },
      h("span", { class: "chart-switch-option", "data-chart": "sankey" }, "Sankey"),
      h("span", { class: "chart-switch-option", "data-chart": "donut" }, "Donut"),
    );
    return toggle;
  }

  /** The chart showing: "sankey" or "donut". */
  get chart() {
    return this.el.dataset.chart;
  }

  /** Shows one chart (drawing it when the card was already drawn once). */
  show(chart) {
    this.el.dataset.chart = chart;
    this.sankey.frame.hidden = chart !== "sankey";
    if (this.donut) {
      this.donut.frame.hidden = chart !== "donut";
    }
    this.toggle.setAttribute("aria-checked", String(chart === "donut"));
    if (this.ready) {
      this.paint();
    }
  }

  /** Draws the visible chart now (called when the card scrolls near the viewport and after a theme change). */
  async paint(theme) {
    this.ready = true;
    this.theme = theme ?? this.theme;
    const target = this.chart === "donut" && this.donut ? this.donut : this.sankey;
    const figure = target === this.donut ? this.bundle.donut : this.bundle.figure;
    const label = `${target === this.donut ? "Donut chart" : "Sankey diagram"} of ${this.graph.name}`;
    try {
      await draw(target.surface, fitFigure(figure, { height: this.height }), { theme: this.theme, label: stripBidi(label), config: CHART_CONFIG_OVERRIDE });
      target.drawn = true;
      target.frame.querySelector(".chart-overlay")?.remove();
    } catch {
      target.frame.querySelector(".chart-overlay")?.remove();
      target.frame.append(h("div", { class: "chart-overlay" }, errorState({ title: "The chart could not be drawn", message: "The chart library did not load.", compact: true })));
    }
  }

  /** Swaps in a new bundle (shared colours changed or the theme switched). */
  update(bundle, theme) {
    this.bundle = bundle;
    this.theme = theme;
    if (this.ready) {
      this.paint();
    }
  }

  dispose() {
    disposeChart(this.sankey.surface);
    if (this.donut) {
      disposeChart(this.donut.surface);
    }
  }
}

/**
 * @param {object} options  see ChartCard
 * @returns {ChartCard}
 */
export function createChartCard(options) {
  return new ChartCard(options);
}

/**
 * The placeholder for a graph that was deleted (or cannot be found).
 * @param {{id: string, name?: string}} graph
 * @param {(graph: object) => void} onRemove
 * @returns {HTMLElement}
 */
export function missingCard(graph, onRemove) {
  return h(
    "article",
    { class: "card compare-card compare-missing", "data-testid": "compare-missing", "data-graph-id": graph.id },
    h("div", { class: "compare-missing-body" },
      h("div", { class: "state-icon" }, icon("trash", { size: 22 })),
      h("p", { class: "state-title" }, "This graph is gone"),
      h("p", { class: "text-muted" }, graph.name ? `“${graph.name}” was deleted or can no longer be found.` : "A graph in this comparison was deleted or can no longer be found."),
      h("button", { type: "button", class: "btn", "data-testid": "compare-remove", on: { click: () => onRemove(graph) } }, icon("x", { size: 14 }), "Remove from the comparison"),
    ),
  );
}

/**
 * The card of a graph that exists but cannot be drawn (a cycle, an unreadable source).
 * @param {{id: string, name: string}} graph
 * @param {{message: string}} problem
 * @param {(graph: object) => void} onRemove
 * @returns {HTMLElement}
 */
export function brokenCard(graph, problem, onRemove) {
  return h(
    "article",
    { class: "card compare-card", "data-testid": "compare-card", "data-graph-id": graph.id, "data-chart": "none" },
    h("header", { class: "compare-card-head" }, title(graph), removeButton(graph, onRemove)),
    errorState({ title: "This graph cannot be drawn", message: problem.message, compact: true }),
    h("div", { class: "compare-card-body" }, h("a", { class: "btn btn-sm", href: graphHref(graph.id, "/edit") }, icon("edit", { size: 14 }), "Fix it in the editor")),
  );
}
