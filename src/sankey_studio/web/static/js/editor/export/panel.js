/**
 * The export panel: download the chart as SVG/PNG (Sankey and donut) or the data as HTML/JSON/CSV.
 *
 * - A saved graph without unsaved edits is exported by `GET /graphs/{id}/export`; an unsaved or
 *   edited one by `POST /export` with the draft, so the file always matches the screen. Both go through
 *   core/api.js `blob()` (./transport.js); file names follow one scheme (./names.js: Sankey `Name.ext`,
 *   donut `Name-donut.ext`), also for the images the browser draws itself.
 * - Images: width, height (blank = the chart's own), scale, transparent. The server draws them
 *   (Chrome); when it cannot (422 export_too_large, 501/502/503/504) the browser draws the figure on
 *   screen with Plotly and the `export-fallback-note` says why. html/json/csv never need Chrome.
 * - A graph with nothing to draw (zero nodes) has nothing to export: every button waits.
 * - One export at a time (the server allows one image at a time too): the clicked button shows
 *   progress, the others wait. Donut buttons need a donut; every button needs a chart.
 * - File colours (`export-theme`): Light (default), Dark or the same as the preview. Every request carries
 *   it as `theme=`, so a dark editor does not hand out dark files unless asked to.
 * Test ids: `export-sankey-svg`, `export-sankey-png`, `export-donut-svg`, `export-donut-png`,
 * `export-html`, `export-json`, `export-csv`, `export-width`, `export-height`, `export-scale`,
 * `export-transparent`, `export-theme`, `export-fallback-note`, plus `export-data-chart` (which chart html/json/csv
 * describe).
 */

import { announce } from "../../core/a11y.js";
import { ApiError, isAbort, reportError } from "../../core/api.js";
import { isClientFallback, saveBlob } from "../../core/download.js";
import { h, setBusy, uid } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { icon } from "../../core/icons.js";
import { effectiveTheme } from "../../core/theme.js";
import { hasDrawing, present, slot } from "../output-panel-kit.js";
import { browserFailure, clientImage, fallbackReason, figureForTheme } from "./fallback.js";
import { exportFileName, stemOf } from "./names.js";
import { DEFAULTS, PIXEL_CAP, SCALE_MAX, SCALE_MIN, SIZE_MAX, SIZE_MIN, imageQuery, pixelSize, readSize } from "./params.js";
import { loadPrefs, savePrefs } from "./prefs.js";
import { createThemeField, resolveTheme } from "./theme.js";
import { fetchExport } from "./transport.js";

const IMAGES = [
  { chart: "sankey", format: "svg", testid: "export-sankey-svg" },
  { chart: "sankey", format: "png", testid: "export-sankey-png" },
  { chart: "donut", format: "svg", testid: "export-donut-svg" },
  { chart: "donut", format: "png", testid: "export-donut-png" },
];
const FILES = [
  { format: "html", label: "HTML page", testid: "export-html" },
  { format: "json", label: "JSON figure", testid: "export-json" },
  { format: "csv", label: "CSV data", testid: "export-csv" },
];

function sizeField(options, errorId) {
  const id = uid("export-field");
  const input = h("input", { id, class: "input nums", type: "number", inputmode: "numeric", min: options.min, max: options.max, step: options.step, placeholder: options.placeholder ?? null, value: options.value, "aria-describedby": errorId, "data-testid": options.testid });
  const el = h("div", { class: "field out-size-field" }, h("label", { for: id }, options.label), input);
  return { el, input };
}

class ExportPanel {
  constructor(container, ctx) {
    this.container = container;
    this.store = ctx.store;
    this.toast = ctx.toast;
    this.theme = () => ctx.previewTheme?.resolve?.() ?? effectiveTheme();
    this.busy = null;
    this.buttons = new Map();
    this.build(loadPrefs());
    this.unsubscribe = [this.store.subscribe(() => this.sync(), { select: (state) => state.bundle }), this.store.subscribe(() => this.sync(), { select: (state) => state.draft?.style?.height }), this.store.subscribe(() => this.sync(), { select: (state) => state.status.previewing })];
    this.sync();
  }

  build(prefs) {
    const titleId = uid("export-title");
    this.sizeError = h("p", { class: "field-error", id: uid("export-size-error"), hidden: true });
    const errorId = this.sizeError.id;
    const width = sizeField({ label: "Width (px)", testid: "export-width", min: SIZE_MIN, max: SIZE_MAX, step: 50, value: prefs.width ?? DEFAULTS.width }, errorId);
    const height = sizeField({ label: "Height (px)", testid: "export-height", min: SIZE_MIN, max: SIZE_MAX, step: 50, placeholder: "Auto", value: prefs.height ?? DEFAULTS.height }, errorId);
    const scale = sizeField({ label: "Scale", testid: "export-scale", min: SCALE_MIN, max: SCALE_MAX, step: 0.5, value: prefs.scale ?? DEFAULTS.scale }, errorId);
    this.fields = { width, height, scale };
    this.transparent = h("input", { type: "checkbox", checked: prefs.transparent === true, "data-testid": "export-transparent", on: { change: () => this.sync() } });
    this.themeField = createThemeField(prefs.theme, () => this.sync());
    this.size = h("p", { class: "out-note nums" });
    this.status = h("p", { class: "out-note", role: "status" });
    this.note = h("div", { class: "notice out-fallback", "data-kind": "info", "data-testid": "export-fallback-note", role: "status" });
    this.noteSlot = slot();
    this.dataChart = h("select", { class: "select", "aria-label": "Chart for HTML, JSON and CSV", "data-testid": "export-data-chart" }, h("option", { value: "sankey" }, "Sankey chart"), h("option", { value: "donut" }, "Donut chart"));
    for (const field of Object.values(this.fields)) {
      field.input.addEventListener("input", () => this.sync());
    }
    this.hint = h("p", { class: "out-note", hidden: true });
    this.card = h(
      "section",
      { class: "card out-card out-export", "aria-labelledby": titleId },
      h("div", { class: "card-header" }, h("h2", { class: "card-title", id: titleId }, "Export")),
      h(
        "div",
        { class: "card-body out-stack" },
        h(
          "fieldset",
          { class: "out-fieldset" },
          h("legend", null, "Export options"),
          h("div", { class: "out-size-grid" }, width.el, height.el, scale.el),
          this.sizeError,
          h("div", { class: "out-options-row" }, this.themeField.el, h("label", { class: "check" }, this.transparent, h("span", null, "Transparent background"))),
          this.themeField.hint,
          this.size,
        ),
        this.group("Sankey", IMAGES.filter((item) => item.chart === "sankey")),
        this.group("Donut", IMAGES.filter((item) => item.chart === "donut")),
        this.hint,
        h("div", { class: "out-group is-stacked", role: "group", "aria-label": "Data and web page" }, h("span", { class: "out-group-label" }, "Web page and data files for"), h("div", { class: "cluster" }, this.dataChart, FILES.map((file) => this.button(file, file.format.toUpperCase())))),
        this.status,
        this.noteSlot,
      ),
    );
    this.container.replaceChildren(this.card);
  }

  group(label, items) {
    return h("div", { class: "out-group", role: "group", "aria-label": `${label} image` }, h("span", { class: "out-group-label" }, label), h("div", { class: "cluster" }, items.map((item) => this.button(item, item.format.toUpperCase()))));
  }

  button(spec, text) {
    const name = spec.chart ? `Download the ${spec.chart} chart as ${spec.format.toUpperCase()}` : `Download as ${spec.label}`;
    const button = h("button", { type: "button", class: "btn", "aria-label": name, "data-testid": spec.testid, on: { click: () => this.run(spec, button) } }, icon("download", { size: 15 }), text);
    this.buttons.set(spec.testid, { button, spec });
    return button;
  }

  figureHeight() {
    const state = this.store.get();
    const high = Number(state.bundle?.figure?.layout?.height ?? state.draft?.style?.height);
    return Number.isFinite(high) && high > 0 ? high : 560;
  }

  readSize() {
    const raw = Object.fromEntries(Object.entries(this.fields).map(([key, field]) => [key, field.input.value]));
    return { raw, ...readSize(raw) };
  }

  /** Re-evaluates what can be clicked, the size line and the saved preferences. */
  sync() {
    const state = this.store.get();
    this.reveal(state);
    const hasChart = hasDrawing(state.bundle);
    const donut = Boolean(state.bundle?.donut_available);
    const size = this.readSize();
    for (const [key, field] of Object.entries(this.fields)) {
      field.input.setAttribute("aria-invalid", String(Boolean(size.errors[key])));
    }
    this.sizeError.textContent = Object.values(size.errors).join(" ");
    this.sizeError.hidden = size.ok;
    for (const { button, spec } of this.buttons.values()) {
      const unavailable = !hasChart || (spec.chart === "donut" && !donut);
      button.disabled = unavailable || this.busy !== null;
    }
    this.dataChart.querySelector('option[value="donut"]').disabled = !donut;
    if (!donut) {
      this.dataChart.value = "sankey";
    }
    this.hint.hidden = hasChart && donut;
    this.hint.textContent = hasChart ? "Donut downloads need at least one categorised entry." : this.emptyHint(state.bundle);
    this.size.textContent = size.ok ? this.sizeText(size.values) : "";
    savePrefs({ ...size.raw, transparent: this.transparent.checked, theme: this.themeField.select.value });
  }

  /**
   * The card waits for the first chart (until then every button is disabled anyway), so it does not
   * jump down when the chart's numbers, legend and category table arrive above it.
   */
  reveal(state) {
    this.ready ||= !(state.status.previewing && !state.bundle);
    this.card.hidden = !this.ready;
  }

  emptyHint(bundle) {
    return bundle ? "Nothing to export yet: the chart has no links to draw." : "Nothing to export yet. Add some data and the chart appears.";
  }

  sizeText(values) {
    const out = pixelSize(values, this.figureHeight());
    const base = `Images come out ${formatNumber(out.width, { maximumFractionDigits: 0 })} x ${formatNumber(out.height, { maximumFractionDigits: 0 })} px.`;
    return out.total > PIXEL_CAP ? `${base} That is over the server's 36 million pixel limit, so your browser will draw it.` : base;
  }

  /** The colours of the downloaded files: the File colours choice, or the preview's colours. */
  fileTheme() {
    return resolveTheme(this.themeField.select.value, this.theme);
  }

  /** The route and query of one download. */
  request(spec, size) {
    const state = this.store.get();
    const isImage = spec.format === "svg" || spec.format === "png";
    const chart = spec.chart ?? this.dataChart.value;
    const query = { chart, format: spec.format, theme: this.fileTheme(), ...(isImage ? imageQuery(size.values, this.transparent.checked) : {}) };
    return { graphId: this.fromDraft(state) ? null : state.meta.id, draft: state.draft, query };
  }

  /** An unsaved or edited graph is exported from the draft (POST /export), a saved one by its id. */
  fromDraft(state) {
    return !(state.meta.id && !state.status.dirty);
  }

  async run(spec, button) {
    const size = this.readSize();
    if (!size.ok && (spec.format === "svg" || spec.format === "png")) {
      const bad = Object.keys(size.errors)[0];
      this.fields[bad].input.focus();
      return;
    }
    this.begin(button, spec);
    try {
      const request = this.request(spec, size);
      const { blob, filename } = await fetchExport(request);
      const named = this.fileName(filename, spec, request.graphId === null);
      saveBlob(blob, named);
      this.finish(`Downloaded ${named}`);
    } catch (error) {
      await this.failed(error, spec, size);
    } finally {
      setBusy(button, false);
      this.busy = null;
      this.sync();
    }
  }

  /** The name of a download: the server's, kept to one scheme (./names.js) and named after the graph when it is a draft. */
  fileName(filename, spec, fromDraft) {
    return exportFileName({ filename, chart: spec.chart ?? this.dataChart.value, graphName: this.store.get().meta.name, fromDraft });
  }

  begin(button, spec) {
    this.busy = spec.testid;
    present(this.noteSlot, this.note, false);
    this.status.textContent = `Preparing ${spec.format.toUpperCase()}...`;
    setBusy(button, true);
    this.sync();
  }

  finish(message) {
    this.status.textContent = message;
    announce(message);
  }

  async failed(error, spec, size) {
    const image = spec.format === "svg" || spec.format === "png";
    const state = this.store.get();
    const chart = spec.chart ?? this.dataChart.value;
    const onScreen = chart === "donut" ? state.bundle?.donut : state.bundle?.figure;
    if (!(image && isClientFallback(error) && onScreen)) {
      this.status.textContent = "";
      reportError(error, this.toast);
      return;
    }
    try {
      const figure = await figureForTheme({ onScreen, chart, theme: this.fileTheme(), previewTheme: this.theme(), draft: state.draft });
      const filename = stemOf(this.fileName(this.browserFileName(state, spec), spec, this.fromDraft(state)));
      await clientImage({ figure, format: spec.format, filename, size: { width: size.values.width, height: size.values.height ?? this.figureHeight(), scale: size.values.scale, transparent: this.transparent.checked } });
      this.note.replaceChildren(icon("info", { size: 16 }), h("div", { class: "notice-body" }, fallbackReason(error)));
      present(this.noteSlot, this.note, true);
      this.finish(`Downloaded ${spec.chart} ${spec.format.toUpperCase()} made by your browser`);
    } catch (fallbackError) {
      this.status.textContent = "";
      this.reportFallback(error, fallbackError);
    }
  }

  /** What the server would have called the file: the graph's name, or the style title of an edited graph. */
  browserFileName(state, spec) {
    const title = this.fromDraft(state) ? state.draft?.style?.title : state.meta.name;
    return `${title || "graph"}.${spec.format}`;
  }

  /** The browser could not draw the image either: say so in a sentence of its own (not "cannot reach the server"). */
  reportFallback(serverError, fallbackError) {
    if (fallbackError instanceof ApiError || isAbort(fallbackError)) {
      reportError(fallbackError, this.toast);
      return;
    }
    this.toast?.error(browserFailure(serverError));
  }

  dispose() {
    for (const off of this.unsubscribe) {
      off();
    }
    this.container.replaceChildren();
  }
}

/**
 * Builds the export panel into `container`.
 * @param {HTMLElement} container
 * @param {{store: object, toast?: object}} ctx
 * @returns {{dispose: () => void}}
 */
export function createExportPanel(container, ctx) {
  const panel = new ExportPanel(container, ctx);
  return { dispose: () => panel.dispose() };
}
