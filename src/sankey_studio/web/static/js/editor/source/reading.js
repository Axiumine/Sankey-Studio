/**
 * "Reading the data": the block under the text tabs (Text file, Paste, Upload) that tells the
 * server how to read the text: format (detected or chosen), column mapping for csv/tsv, and a
 * preview of the first rows. It shows only while the source is a text source.
 *
 * Format detection uses POST /api/v1/sources/detect on the first 4096 characters when the format
 * is "auto". The sample is the pasted text or the first lines of the chosen file
 * (GET /sources/files/{name}/preview). Everything is debounced and the newest request wins.
 * Test id: source-format.
 */

import { debounce } from "../../core/debounce.js";
import { h } from "../../core/dom.js";
import { field, selectInput } from "../../core/form.js";
import { bindSelect } from "../meta/bind.js";
import { delimiterFor, parseRecords } from "./columns.js";
import { createMapping } from "./mapping.js";

const FORMATS = [
  { value: "auto", label: "Detect automatically" },
  { value: "csv", label: "CSV (comma, semicolon or pipe separated)" },
  { value: "tsv", label: "TSV (tab separated, as copied from a spreadsheet)" },
  { value: "sankeymatic", label: "SankeyMATIC text (Source [value] Target)" },
  { value: "json", label: "JSON (a list of objects)" },
];
const NAMES = { csv: "CSV", tsv: "TSV", sankeymatic: "SankeyMATIC text", json: "JSON" };
const HELP = {
  sankeymatic: "One link per line: Salary [3000] Budget. Add | and a category at the end to categorise it: Budget [1200] Rent | Housing. Lines that start with // are comments.",
  json: "A list of objects with source, target and value (and an optional category), or one such object per line.",
};
const SAMPLE_CHARS = 20000;
const DETECT_CHARS = 4096;

class Reading {
  constructor({ store, api, files, fields }) {
    this.store = store;
    this.api = api;
    this.files = files;
    this.sequence = 0;
    this.detected = { sample: null, format: null };
    const control = selectInput({ options: FORMATS, "data-testid": "source-format" });
    this.format = field({ label: "Format", control, hint: "" });
    fields.format = this.format;
    this.mapping = createMapping({ store, fields });
    this.help = h("p", { class: "hint ed-format-help", hidden: true });
    this.preview = h("pre", { class: "ed-raw", tabindex: "0", "aria-label": "First lines of your data, scrollable", hidden: true });
    this.empty = h("p", { class: "hint", hidden: true }, "Your data will appear here as soon as there is some.");
    this.el = h("div", { class: "ed-reading stack stack-sm" }, h("h4", { class: "ed-subtitle" }, "How to read the data"), this.format.el, this.help, this.mapping.el, this.preview, this.empty);
    this.refresh = debounce(() => this.run(), 200);
    this.offs = [
      bindSelect(store, control, ["draft", "source", "format"], { fallback: "auto" }),
      store.subscribe((spec) => this.onSource(spec), { select: (state) => state.draft.source, immediate: true }),
      files.subscribe(() => this.refresh()),
    ];
  }

  onSource(spec) {
    this.el.hidden = spec.type !== "text";
    this.refresh();
  }

  async sampleOf(spec) {
    if (spec.origin !== "file") {
      return (spec.content ?? "").slice(0, SAMPLE_CHARS);
    }
    if (!spec.path) {
      return "";
    }
    try {
      return (await this.files.preview(spec.path)).join("\n");
    } catch {
      return "";
    }
  }

  async detect(sample) {
    if (sample.trim() === "") {
      return null;
    }
    if (this.detected.sample === sample) {
      return this.detected.format;
    }
    try {
      const answer = await this.api.post("/sources/detect", { sample: sample.slice(0, DETECT_CHARS) }, { quiet: true });
      this.detected = { sample, format: answer.format };
      return answer.format;
    } catch {
      return null; // detection is a convenience: the server detects again when it reads the data
    }
  }

  async run() {
    const spec = this.store.get().draft.source;
    this.el.hidden = spec.type !== "text";
    if (this.el.hidden) {
      return;
    }
    this.sequence += 1;
    const mine = this.sequence;
    const sample = await this.sampleOf(spec);
    const detected = spec.format === "auto" || spec.format == null ? await this.detect(sample) : null;
    if (mine !== this.sequence) {
      return;
    }
    const format = spec.format && spec.format !== "auto" ? spec.format : (detected ?? "csv");
    this.format.setHint(spec.format === "auto" || spec.format == null ? this.detectionHint(sample, detected) : "");
    this.show(format, sample, this.store.get().draft.source);
  }

  detectionHint(sample, detected) {
    if (sample.trim() === "") {
      return "The format is detected as soon as there is data.";
    }
    return detected ? `Detected: ${NAMES[detected]}. Choose a format to override it.` : "Could not detect the format. Choose one.";
  }

  show(format, sample, spec) {
    const delimited = format === "csv" || format === "tsv";
    const hasData = sample.trim() !== "";
    this.mapping.el.hidden = !(delimited && hasData);
    this.help.textContent = HELP[format] ?? "";
    this.help.hidden = !HELP[format];
    this.preview.hidden = delimited || !hasData;
    this.preview.textContent = delimited ? "" : sample.split(/\r\n|\r|\n/).slice(0, 8).join("\n");
    this.empty.hidden = hasData;
    if (delimited && hasData) {
      this.mapping.update(parseRecords(sample, delimiterFor(spec, format, sample), 8));
    }
  }

  dispose() {
    this.refresh.cancel();
    this.sequence += 1;
    this.offs.forEach((off) => off());
    this.mapping.dispose();
  }
}

/**
 * Builds the block.
 * @param {{store: object, api: object, files: ReturnType<typeof import("./files.js").createFiles>, fields: Record<string, object>}} options
 * @returns {{el: HTMLElement, dispose: () => void, refresh: () => void}}
 */
export function createReading(options) {
  const reading = new Reading(options);
  return { el: reading.el, dispose: () => reading.dispose(), refresh: () => reading.refresh() };
}
