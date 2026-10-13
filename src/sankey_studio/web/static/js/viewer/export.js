/**
 * The export panel of the viewer: image size options, SVG / PNG of the chart that is showing,
 * and the HTML / JSON / CSV downloads.
 *
 * Every button asks `GET /graphs/{id}/export` (core/download.js saves the attachment). When the
 * server cannot draw an image - 422 `export_too_large`, or 501 / 502 / 503 / 504 - the panel says
 * why in `export-fallback-note` and saves the chart the browser already drew with
 * `Plotly.downloadImage` instead (what is on screen; a transparent background is not possible
 * there). Other failures (no categories for a donut, a deleted graph) are toasts.
 *
 * File names: the server's own name (`Content-Disposition`) is kept as it is: `<name>.<ext>` for a
 * Sankey, `<name>-donut.<ext>` for a donut. A file the browser names itself follows the same rule
 * (core/download.js `chartStem`).
 *
 * Test ids: export-sankey-svg, export-sankey-png, export-donut-svg, export-donut-png (only the
 * pair of the active chart is shown), export-html, export-json, export-csv, export-width,
 * export-height, export-scale, export-transparent, export-theme, export-fallback-note.
 */

import { announce } from "../core/a11y.js";
import { reportError } from "../core/api.js";
import { downloadImage } from "../core/chart.js";
import { setBusy, h } from "../core/dom.js";
import { chartStem, cleanFilename, downloadExport, isClientFallback } from "../core/download.js";
import { formatNumber } from "../core/format.js";
import { checkbox, field, numberInput, selectInput } from "../core/form.js";
import { icon } from "../core/icons.js";
import { toast } from "../core/toast.js";

const LIMITS = { width: [200, 4000], height: [200, 4000], scale: [0.5, 4] };
const DEFAULTS = { width: 1200, scale: 2 };

const REASONS = {
  501: "This server cannot draw images (Chrome was not found).",
  502: "The server's image renderer failed.",
  503: "The server's image renderer is busy with another export.",
  504: "The server took too long to draw the image.",
};

function reasonFor(error) {
  if (error.code === "export_too_large") {
    return "That size is larger than the server can draw.";
  }
  return REASONS[error.status] ?? "The server could not draw the image.";
}

function inRange(value, [low, high]) {
  return Number.isFinite(value) && value >= low && value <= high;
}

class ExportPanel {
  /** @param {{graph: {id: string, name: string}, charts: {active: () => string, surface: (kind: string) => HTMLElement | null}, display?: () => object}} options  `display` returns the label switches the person changed (sent with every export) */
  constructor({ graph, charts, display }) {
    this.graph = graph;
    this.charts = charts;
    this.chosenDisplay = display ?? (() => ({}));
    this.heights = { sankey: 560, donut: 460 };
    this.kind = "sankey";
    this.buildControls();
    this.buildButtons();
    this.note = h("p", { class: "notice export-note", "data-kind": "info", role: "status", hidden: true, "data-testid": "export-fallback-note" });
    this.el = h(
      "section",
      { class: "card export-panel", "aria-labelledby": "export-title" },
      h(
        "div",
        { class: "card-body stack" },
        h("h2", { class: "section-title", id: "export-title" }, "Export"),
        this.optionsRow,
        this.size,
        this.imageGroup,
        this.dataGroup,
        this.note,
      ),
    );
    this.setActive("sankey");
  }

  buildControls() {
    this.width = numberInput({ value: DEFAULTS.width, min: LIMITS.width[0], max: LIMITS.width[1], step: 50, "data-testid": "export-width", inputmode: "numeric" });
    this.height = numberInput({ placeholder: "Auto", min: LIMITS.height[0], max: LIMITS.height[1], step: 50, "data-testid": "export-height", inputmode: "numeric" });
    this.scale = numberInput({ value: DEFAULTS.scale, min: LIMITS.scale[0], max: LIMITS.scale[1], step: 0.5, "data-testid": "export-scale" });
    this.transparent = checkbox({ label: "Transparent background", "data-testid": "export-transparent" });
    this.theme = selectInput({ options: [{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }], value: "light", "data-testid": "export-theme" });
    this.fields = {
      width: field({ label: "Width (px)", control: this.width }),
      height: field({ label: "Height (px)", control: this.height }),
      scale: field({ label: "Scale", control: this.scale }),
      theme: field({ label: "File colours", control: this.theme }),
    };
    this.optionsRow = h("div", { class: "export-options" }, this.fields.width.el, this.fields.height.el, this.fields.scale.el, this.fields.theme.el);
    this.size = h("div", { class: "export-size" }, this.transparent, h("p", { class: "hint", "aria-live": "polite" }));
    for (const input of [this.width, this.height, this.scale]) {
      input.addEventListener("input", () => this.showSize());
    }
  }

  /** One download button: `chart` is "sankey", "donut" or "active" (whatever is showing). */
  button(label, testid, format, chart) {
    const el = h("button", { type: "button", class: "btn", "data-testid": testid, on: { click: () => this.run(chart, el, format) } }, icon("download", { size: 14 }), label);
    return el;
  }

  buildButtons() {
    this.imageButtons = {
      sankey: [this.button("Sankey SVG", "export-sankey-svg", "svg", "sankey"), this.button("Sankey PNG", "export-sankey-png", "png", "sankey")],
      donut: [this.button("Donut SVG", "export-donut-svg", "svg", "donut"), this.button("Donut PNG", "export-donut-png", "png", "donut")],
    };
    this.imageTitle = h("h3", { class: "legend-title" }, "Image");
    this.imageGroup = h("div", { class: "export-group" }, this.imageTitle, h("div", { class: "export-buttons" }, [...this.imageButtons.sankey, ...this.imageButtons.donut]));
    this.csvButton = this.button("CSV", "export-csv", "csv", "active");
    this.dataButtons = [this.button("HTML", "export-html", "html", "active"), this.button("JSON", "export-json", "json", "active"), this.csvButton];
    this.dataTitle = h("h3", { class: "legend-title" }, "Data");
    this.dataGroup = h(
      "div",
      { class: "export-group" },
      this.dataTitle,
      h("div", { class: "export-buttons" }, this.dataButtons),
    );
  }

  /** Tells the panel which chart is showing; the image buttons and titles follow. */
  setActive(kind) {
    this.kind = kind;
    const donut = kind === "donut";
    this.imageButtons.sankey.forEach((el) => { el.hidden = donut; });
    this.imageButtons.donut.forEach((el) => { el.hidden = !donut; });
    this.imageTitle.textContent = donut ? "Donut image" : "Sankey image";
    this.dataTitle.textContent = donut ? "Donut data" : "Sankey data";
    this.csvButton.title = donut ? "The categories, their values and shares, as CSV" : "Every link (source, target, value, category) as CSV";
    this.dataButtons[0].title = donut ? "The donut as an interactive web page" : "The Sankey as an interactive web page";
    this.dataButtons[1].title = donut ? "The donut figure data as JSON" : "The Sankey figure data as JSON";
    this.showSize();
  }

  /** Remembers the drawn heights (the default image heights) and refreshes the size line. */
  setHeights({ sankey, donut }) {
    this.heights = {
      sankey: Number.isFinite(sankey) ? sankey : this.heights.sankey,
      donut: Number.isFinite(donut) ? donut : this.heights.donut,
    };
    this.showSize();
  }

  readOptions() {
    const width = Number(this.width.value);
    const heightText = this.height.value.trim();
    const height = heightText === "" ? null : Number(heightText);
    const scale = Number(this.scale.value);
    const bad = {
      width: !inRange(width, LIMITS.width) && `Enter a width from ${LIMITS.width[0]} to ${LIMITS.width[1]}.`,
      height: height !== null && !inRange(height, LIMITS.height) && `Leave empty, or enter a height from ${LIMITS.height[0]} to ${LIMITS.height[1]}.`,
      scale: !inRange(scale, LIMITS.scale) && `Enter a scale from ${LIMITS.scale[0]} to ${LIMITS.scale[1]}.`,
    };
    for (const [name, message] of Object.entries(bad)) {
      this.fields[name].setError(message || "");
    }
    const first = Object.entries(bad).find(([, message]) => message);
    if (first) {
      this[first[0]].focus();
      return null;
    }
    return { width: Math.round(width), height: height === null ? null : Math.round(height), scale, transparent: this.transparent.querySelector("input").checked, theme: this.theme.value };
  }

  showSize() {
    const width = Number(this.width.value);
    const height = this.height.value.trim() === "" ? this.heights[this.kind] : Number(this.height.value);
    const scale = Number(this.scale.value);
    const hint = this.size.querySelector(".hint");
    const ok = [width, height, scale].every(Number.isFinite);
    hint.textContent = ok ? `Image size: ${formatNumber(Math.round(width * scale), { maximumFractionDigits: 0 })} × ${formatNumber(Math.round(height * scale), { maximumFractionDigits: 0 })} px.` : "";
  }

  async run(which, button, format) {
    const chart = which === "active" ? this.charts.active() : which;
    const image = format === "svg" || format === "png";
    const options = image ? this.readOptions() : { theme: this.theme.value };
    if (!options) {
      return;
    }
    this.note.hidden = true;
    setBusy(button, true);
    try {
      const query = { ...this.chosenDisplay(), chart, format, theme: options.theme, width: options.width, height: options.height, scale: options.scale, transparent: options.transparent || null };
      const saved = await downloadExport(`/graphs/${this.graph.id}/export`, { query, chart, fallbackName: `${cleanFilename(this.graph.name, "graph")}.${format}` });
      toast.success(`Saved ${saved.filename}.`);
    } catch (error) {
      await this.handleFailure(error, { chart, format, options });
    } finally {
      setBusy(button, false);
    }
  }

  async handleFailure(error, request) {
    const image = request.format === "svg" || request.format === "png";
    if (!image || !isClientFallback(error)) {
      reportError(error, toast);
      return;
    }
    const surface = this.charts.surface(request.chart);
    if (!surface) {
      reportError(error, toast);
      return;
    }
    try {
      const { options } = request;
      const name = chartStem(cleanFilename(this.graph.name, "graph"), request.chart);
      await downloadImage(surface, { format: request.format, filename: name, width: options.width, height: options.height ?? undefined, scale: options.scale });
      const extra = options.transparent ? " A transparent background is only possible with the server image." : "";
      this.note.textContent = `${reasonFor(error)} Your browser drew the image instead, as it looks on screen.${extra}`;
      this.note.hidden = false;
      announce("Saved from your browser instead of the server.");
    } catch {
      toast.error("The image could not be saved.");
    }
  }
}

/**
 * Builds the export panel.
 * @param {{graph: {id: string, name: string}, charts: object, display?: () => object}} options
 * @returns {ExportPanel}
 */
export function createExportPanel(options) {
  return new ExportPanel(options);
}
