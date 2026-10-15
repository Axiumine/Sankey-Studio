/**
 * The viewer page: header, numbers, warnings and the chart card of one saved graph. The export
 * panel lives in a popover that a download icon in the chart card opens (export-menu.js).
 *
 * Load: `GET /graphs/{id}/render?theme=<shown theme>`. A switch of the colour theme asks again with
 * the other `?theme=` and redraws in place; the previous drawing stays until the new one arrives,
 * and an older answer never replaces a newer one. A 404 means the graph was deleted after the page
 * was served (link back to the library); a build error (cycle, unreadable source) shows the
 * server's message with a link to the editor.
 *
 * The display menu (display-menu.js) switches the values and percentages on the charts. A switch the
 * person changed is sent with the render request (`chosen`); one they did not touch keeps what the
 * saved style says. The saved graph is never changed. If the redraw fails the switch goes back.
 *
 * The header (name, description, tags, revision) starts from the graph summary the server embedded
 * in the page. When the person arrives by the Back button, or the browser restores the page from its
 * back/forward cache, that summary may predate an edit made meanwhile, so it is read again
 * (`GET /graphs/{id}`) and the heading, the title and the header are redrawn.
 */

import { isAbort, reportError } from "../core/api.js";
import { lockWriteControls, setHeading } from "../core/boot.js";
import { setBusy, h } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { emptyState, errorState, loadingState } from "../core/states.js";
import { createChartFrame } from "../core/chart.js";
import { effectiveTheme, onThemeChange } from "../core/theme.js";
import { toast } from "../core/toast.js";
import { duplicateGraph, graphHref } from "../library/data.js";
import { onRestored, reachedByHistory } from "../library/freshness.js";
import { displayName, withDisplayName } from "../library/names.js";
import { createCharts } from "./charts.js";
import { DEFAULT_VIEW, fetchGraph, fetchRender, fetchViewStyle } from "./data.js";
import { createExportMenu } from "./export-menu.js";
import { graphHeader } from "./header.js";
import { statsStrip, valueSuffix, warningsList } from "./parts.js";

class ViewerPage {
  /** @param {{graph: object, root: HTMLElement, actionsRoot: HTMLElement}} options */
  constructor({ graph, root, actionsRoot }) {
    this.graph = withDisplayName(graph);
    this.root = root;
    this.running = null;
    this.parts = null;
    this.view = null; // the saved style as far as the viewer needs it (fetchViewStyle), once read
    this.chosen = {}; // display switches changed on this page: {node_values?, donut_percent?, donut_value?}
    this.body = h("div", { class: "viewer-body stack" });
    this.header = graphHeader(this.graph);
    root.replaceChildren(this.header, this.body);
    actionsRoot.replaceChildren(this.actions());
    lockWriteControls(actionsRoot);
  }

  actions() {
    const edit = h("a", { class: "btn", href: graphHref(this.graph.id, "/edit"), "data-testid": "graph-edit" }, icon("edit", { size: 14 }), "Edit");
    const copy = h(
      "button",
      { type: "button", class: "btn", "data-writes": true, "data-testid": "graph-duplicate", on: { click: () => this.duplicate(copy) } },
      icon("copy", { size: 14 }),
      "Duplicate",
    );
    return h("div", { class: "cluster", role: "group", "aria-label": "Graph actions" }, edit, copy);
  }

  async duplicate(button) {
    setBusy(button, true);
    try {
      const made = await duplicateGraph(this.graph.id);
      toast.success(`Created “${displayName(made.name)}”.`, { timeout: 12000, action: { label: "Open copy", onClick: () => location.assign(graphHref(made.id)) } });
    } catch (error) {
      reportError(error, toast);
    } finally {
      setBusy(button, false);
    }
  }

  start() {
    setHeading(this.graph.name); // a name with nothing to show reads "Untitled graph" in the heading and the tab title
    onThemeChange(({ effective }) => this.load(effective));
    onRestored(() => {
      this.refreshHeader();
      this.retry();
    });
    if (reachedByHistory()) {
      this.refreshHeader();
    }
    return this.retry();
  }

  /** Reads the graph again and redraws what the embedded summary showed. A failure keeps the old header. */
  async refreshHeader() {
    const fresh = await fetchGraph(this.graph.id);
    if (!fresh) {
      return;
    }
    Object.assign(this.graph, withDisplayName(fresh)); // the chart and export parts hold this same object
    const header = graphHeader(this.graph);
    this.header.replaceWith(header);
    this.header = header;
    setHeading(this.graph.name);
  }

  /** Shows the loading frame and asks for the bundle in the colours now on screen. */
  retry() {
    this.disposeParts(); // a restored page redraws: free the old Plotly instance, its observer and window listener
    this.parts = null;
    const { frame } = createChartFrame({ height: 560 });
    frame.append(h("div", { class: "chart-overlay" }, loadingState({ label: "Loading the graph", block: true })));
    // same boxes as the finished page (numbers strip, chart card): nothing moves when the data arrives
    this.body.replaceChildren(
      h("div", { class: "skeleton viewer-stats-skeleton", "aria-hidden": "true" }),
      h("div", { class: "card chart-card" }, h("div", { class: "card-body" }, h("div", { class: "tabs-skeleton" }), frame)),
    );
    return this.load(effectiveTheme());
  }

  /** Switches the display option `key` and redraws; a failed redraw puts the switch back. */
  async choose(key, on) {
    const before = this.shownValues()[key];
    this.chosen = { ...this.chosen, [key]: on };
    if (!(await this.load(effectiveTheme(), "The chart could not be redrawn."))) {
      this.chosen = { ...this.chosen, [key]: before };
      this.parts?.charts.setSwitch(key, before);
    }
  }

  /** The switches as the menu shows them: what the person changed over the saved style. */
  shownValues() {
    return { ...(this.view ?? DEFAULT_VIEW).values, ...this.chosen };
  }

  /** Draws the graph for `theme`; resolves to false when the request failed (not when it was replaced). */
  async load(theme, failed = `The ${theme} colours could not be loaded.`) {
    this.running?.abort();
    const mine = new AbortController();
    this.running = mine;
    try {
      const wantView = this.view === null && !this.parts;
      const [bundle, view] = await Promise.all([
        fetchRender(this.graph.id, theme, mine.signal, this.chosen),
        wantView ? fetchViewStyle(this.graph.id, mine.signal) : this.view,
      ]);
      this.view = view;
      await this.show(bundle, theme);
    } catch (error) {
      if (!isAbort(error)) {
        this.fail(error, failed);
        return false;
      }
    }
    return true;
  }

  fail(error, failed) {
    const failure = reportError(error);
    if (this.parts) {
      toast.error(`${failed} ${failure.friendly}`);
      return;
    }
    if (failure.status === 404) {
      this.body.replaceChildren(emptyState({
        title: "This graph no longer exists",
        message: "It was deleted after this page opened. Go back to the library to pick another one.",
        icon: "trash",
        actions: [h("a", { class: "btn btn-primary", href: "/" }, "Back to the library")],
        testid: "viewer-missing",
      }));
      return;
    }
    const retry = errorState({ title: "The graph could not be drawn", message: failure.friendly, onRetry: () => this.retry() });
    const edit = h("a", { class: "btn", href: graphHref(this.graph.id, "/edit") }, "Open in the editor");
    retry.querySelector(".state-actions")?.append(edit);
    this.body.replaceChildren(retry);
  }

  async show(bundle, theme) {
    if (this.parts?.hasDonut !== bundle.donut_available) {
      this.build(bundle);
    }
    const { charts, exporter } = this.parts;
    charts.setBasis(this.view?.basis ?? null);
    const suffix = valueSuffix(bundle.figure);
    this.parts.stats.replaceChildren(statsStrip(bundle.stats, { suffix }));
    this.parts.warnings.replaceChildren(...[warningsList(bundle.warnings)].filter(Boolean));
    exporter.setHeights({ sankey: bundle.figure?.layout?.height, donut: bundle.donut?.layout?.height });
    await charts.update(bundle, theme);
  }

  /** Frees what the current parts hold (the Plotly instances, the open popovers). */
  disposeParts() {
    this.parts?.charts.dispose();
    this.parts?.exporter.dispose();
  }

  build(bundle) {
    this.disposeParts();
    const stats = h("div", { class: "viewer-stats" });
    const warnings = h("div", { class: "viewer-warnings-slot" });
    const display = { values: this.shownValues(), onChange: (key, on) => this.choose(key, on) };
    const charts = createCharts({ bundle, graph: this.graph, display, onTab: (id) => this.parts?.exporter.setActive(id) });
    const exporter = createExportMenu({ graph: this.graph, charts, display: () => this.chosen });
    charts.addTool(exporter.el);
    this.parts = { charts, exporter, stats, warnings, hasDonut: bundle.donut_available };
    this.body.replaceChildren(stats, warnings, charts.el);
  }
}

/**
 * Starts the viewer.
 * @param {{graph: object, root: HTMLElement, actionsRoot: HTMLElement}} options
 * @returns {ViewerPage}
 */
export function startViewer(options) {
  const page = new ViewerPage(options);
  page.start();
  return page;
}

