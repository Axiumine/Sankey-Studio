// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Column mapping for delimited text (csv / tsv): which column is the source, target, value and
 * the optional category, whether the first row is a header, the delimiter and the encoding.
 *
 * Maps 1:1 to `TextSource`: has_header, source_column, target_column, value_column,
 * category_column (a header name, or a 0-based index when there is no header), detect_category,
 * delimiter, encoding. "Automatic" removes the key, so the server looks for columns called
 * source/target/value (or uses the first three). When the header uses other words (from, to,
 * amount) they are matched for the person once, with a visible note.
 * Test ids: source-column-source|target|value|category, source-no-category-switch.
 */

import { h } from "../../core/dom.js";
import { checkbox, field, selectInput, textInput } from "../../core/form.js";
import { bindText } from "../meta/bind.js";
import { applyDerived } from "../meta/dirty.js";
import { guessColumns, key, roleIndexes } from "./columns.js";

const SRC = ["draft", "source"];
const LABELS = { source: "Source", target: "Target", value: "Value", category: "Category" };
const CANDIDATES = [",", ";", "\t", "|"];
const showDelimiter = (char) => (char === "\t" ? "Tab" : `"${char}"`);
const ENCODINGS = ["utf-8", "utf-8-sig", "utf-16", "cp1252", "latin-1", "iso-8859-15"];
const CATEGORY_HINT = "Optional. Automatic uses a column called category when there is one.";
const CATEGORY_HINT_HEADERLESS = "Optional. Automatic uses the fourth column when there is one.";

function autoLabel(spec, role, cells) {
  if (cells.length === 0) {
    return "Automatic";
  }
  const index = roleIndexes({ ...spec, [`${role}_column`]: undefined }, cells)[role];
  if (index < 0 || index >= cells.length) {
    return "Auto (none found)";
  }
  return `Auto (${spec.has_header === false ? `col ${index + 1}` : cells[index].trim()})`;
}

function optionsFor(cells, hasHeader, current, auto = "Automatic") {
  const options = [{ value: "", label: auto }];
  const seen = new Set();
  cells.forEach((cell, index) => {
    const name = cell.trim();
    const value = hasHeader ? name : String(index);
    if ((hasHeader && (name === "" || seen.has(name.toLowerCase()))) || seen.has(value)) {
      return;
    }
    seen.add(hasHeader ? name.toLowerCase() : value);
    options.push({ value, label: hasHeader ? name : `Column ${index + 1}` });
  });
  if (current != null && !options.some((option) => option.value === String(current))) {
    options.push({ value: String(current), label: `${current} (not in the data)` });
  }
  return options;
}

function renderOptions(select, options) {
  select.replaceChildren(...options.map((option) => h("option", { value: option.value }, option.label)));
}

function sampleTable(records, spec) {
  const hasHeader = spec.has_header !== false;
  const head = records[0] ?? [];
  const roles = roleIndexes(spec, head);
  const width = Math.min(Math.max(...records.map((row) => row.length), 0), 12);
  const columns = Array.from({ length: width }, (_, index) => index);
  const roleOf = (index) => Object.keys(roles).find((role) => roles[role] === index);
  const header = columns.map((index) => {
    const role = roleOf(index);
    return h("th", { scope: "col" }, role ? h("span", { class: "ed-role" }, LABELS[role]) : null, hasHeader ? (head[index] ?? "") : `Column ${index + 1}`);
  });
  const body = records.slice(hasHeader ? 1 : 0, hasHeader ? 6 : 5).map((row) => h("tr", null, columns.map((index) => h("td", null, row[index] ?? ""))));
  return h("div", { class: "ed-sample", tabindex: "0", role: "region", "aria-label": "First rows of your data, scrollable" }, h("table", { class: "table ed-sample-table" }, h("caption", { class: "visually-hidden" }, "First rows of your data"), h("thead", null, h("tr", null, header)), h("tbody", null, body)));
}

class Mapping {
  constructor(store, fields) {
    this.store = store;
    this.fields = fields;
    this.cells = [];
    this.guessedFor = "";
    this.matched = "";
    this.selects = {};
    this.rendered = {};
    this.offs = [];
    this.note = h("p", { class: "hint ed-mapping-note", hidden: true });
    this.sample = h("div", { class: "ed-sample-slot" });
    this.header = this.buildHeader();
    this.pickers = ["source", "target", "value", "category"].map((role) => this.buildPicker(role));
    this.noCategory = this.buildNoCategory();
    this.advanced = this.buildAdvanced();
    this.el = h(
      "div",
      { class: "ed-mapping stack stack-sm" },
      this.header.label,
      h("div", { class: "ed-grid ed-grid-3" }, this.pickers.slice(0, 3).map((picker) => picker.el)),
      this.pickers[3].el,
      this.noCategory.label,
      this.note,
      this.advanced.el,
      this.sample,
    );
  }

  spec() {
    return this.store.get().draft.source;
  }

  buildHeader() {
    const label = checkbox({ label: "The first row is a header", "data-testid": "source-has-header" });
    const input = label.querySelector("input");
    input.addEventListener("change", () => {
      this.guessedFor = ""; // the picks are cleared below: the next look at the header guesses them again
      this.store.batch(() => {
        this.store.patch([...SRC, "has_header"], input.checked);
        for (const role of Object.keys(LABELS)) {
          this.store.remove([...SRC, `${role}_column`]);
        }
      });
    });
    this.offs.push(this.store.subscribe((value) => {
      input.checked = value !== false;
    }, { select: (state) => state.draft.source.has_header, immediate: true }));
    return { label, input };
  }

  buildPicker(role) {
    const select = selectInput({ options: [{ value: "", label: "Automatic" }], "data-testid": `source-column-${role}` });
    const f = field({ label: `${LABELS[role]} column`, control: select, hint: role === "category" ? CATEGORY_HINT : null });
    this.selects[role] = select;
    this.fields[`${role}_column`] = f;
    select.addEventListener("change", () => this.choose(role, select.value));
    if (role === "category") {
      // the server reads the fourth column when there is no header row: the hint follows the checkbox
      this.offs.push(this.store.subscribe((value) => f.setHint(value === false ? CATEGORY_HINT_HEADERLESS : CATEGORY_HINT), { select: (state) => state.draft.source.has_header, immediate: true }));
    }
    this.offs.push(this.store.subscribe(() => this.showChoice(role), { select: (state) => state.draft.source[`${role}_column`], immediate: true }));
    return f;
  }

  choose(role, value) {
    const path = [...SRC, `${role}_column`];
    if (value === "") {
      this.store.remove(path);
    } else {
      this.store.patch(path, this.spec().has_header === false ? Number(value) : value);
    }
  }

  showChoice(role) {
    const current = this.spec()[`${role}_column`];
    const select = this.selects[role];
    const wanted = current == null ? "" : String(current);
    if (!Array.from(select.options).some((option) => option.value === wanted)) {
      renderOptions(select, optionsFor(this.cells, this.spec().has_header !== false, current, autoLabel(this.spec(), role, this.cells)));
    }
    select.value = wanted;
  }

  buildNoCategory() {
    const label = checkbox({ label: "This data has no category column", role: "switch", "data-testid": "source-no-category-switch" });
    const input = label.querySelector("input");
    input.addEventListener("change", () => {
      this.store.batch(() => {
        this.store.patch([...SRC, "detect_category"], !input.checked);
        if (input.checked) {
          this.store.remove([...SRC, "category_column"]);
        }
      });
    });
    this.offs.push(this.store.subscribe((value) => {
      input.checked = value === false;
      this.selects.category.disabled = input.checked;
    }, { select: (state) => state.draft.source.detect_category, immediate: true }));
    return { label, input };
  }

  buildAdvanced() {
    const delimiter = field({ label: "Delimiter", control: textInput({ maxlength: 1, placeholder: "Automatic", class: "ed-narrow" }), hint: "One character. Leave empty to detect it." });
    const encoding = field({ label: "Text encoding", control: textInput({ maxlength: 32, placeholder: "utf-8", list: "source-encodings" }), hint: "For files saved by older programs, try cp1252." });
    const list = h("datalist", { id: "source-encodings" }, ENCODINGS.map((value) => h("option", { value })));
    this.fields.delimiter = delimiter;
    this.fields.encoding = encoding;
    this.offs.push(bindText(this.store, delimiter.control, [...SRC, "delimiter"], { removeEmpty: true }), bindText(this.store, encoding.control, [...SRC, "encoding"], { removeEmpty: true }));
    const showEncoding = this.store.subscribe((origin) => {
      encoding.el.hidden = origin !== "file";
    }, { select: (state) => state.draft.source.origin, immediate: true });
    this.offs.push(showEncoding);
    const summary = h("summary", null, "More reading options");
    const el = h("details", { class: "ed-advanced" }, summary, h("div", { class: "form-grid ed-grid" }, delimiter.el, encoding.el, list));
    // a delimiter that is set must not hide in a closed box: it changes how every row is read
    this.offs.push(this.store.subscribe((value) => {
      summary.textContent = value ? `More reading options (delimiter ${showDelimiter(value)})` : "More reading options";
      el.open = el.open || Boolean(value);
    }, { select: (state) => state.draft.source.delimiter, immediate: true }));
    return { el };
  }

  /** Called with the first records of the data; refreshes the pickers, the note and the preview. */
  update(records) {
    const spec = this.spec();
    const hasHeader = spec.has_header !== false;
    this.cells = records[0] ?? [];
    this.applyGuess(spec, hasHeader);
    const fresh = this.spec();
    for (const role of Object.keys(this.selects)) {
      const options = optionsFor(this.cells, hasHeader, fresh[`${role}_column`], autoLabel(fresh, role, this.cells));
      const signature = options.map((option) => `${option.value}\u0000${option.label}`).join("\u0001");
      if (this.rendered[role] !== signature) {
        this.rendered[role] = signature;
        renderOptions(this.selects[role], options);
      }
      this.showChoice(role);
    }
    this.sample.replaceChildren(records.length > 0 ? sampleTable(records, fresh) : "");
    this.explain(fresh);
  }

  applyGuess(spec, hasHeader) {
    const signature = this.cells.join("\u0000");
    if (!hasHeader || this.cells.length === 0) {
      this.matched = "";
      return;
    }
    if (signature === this.guessedFor) {
      return;
    }
    const seenBefore = this.guessedFor !== ""; // the first header of a session keeps the picks a saved graph holds
    this.guessedFor = signature;
    this.matched = "";
    const stale = seenBefore ? this.stalePicks(spec) : [];
    const guess = guessColumns(this.cells);
    const roles = Object.keys(guess).filter((role) => spec[`${role}_column`] == null || stale.includes(role));
    applyDerived(this.store, () => {
      stale.forEach((role) => this.store.remove([...SRC, `${role}_column`]));
      roles.forEach((role) => this.store.patch([...SRC, `${role}_column`], guess[role]));
    });
    this.matched = roles.map((role) => `${guess[role]} as ${LABELS[role].toLowerCase()}`).join(", ");
  }

  /** Roles whose chosen column is not in the new header (other data was pasted or picked). */
  stalePicks(spec) {
    const names = this.cells.map(key);
    return Object.keys(LABELS).filter((role) => typeof spec[`${role}_column`] === "string" && !names.includes(key(spec[`${role}_column`])));
  }

  /** A chosen delimiter that leaves the first row in one piece although it holds another delimiter. */
  delimiterNote(spec) {
    const other = this.cells.length === 1 ? CANDIDATES.find((char) => char !== spec.delimiter && this.cells[0].includes(char)) : null;
    if (!spec.delimiter || !other) {
      return "";
    }
    return `The delimiter is set to ${showDelimiter(spec.delimiter)}, so each row reads as one column, but the first row contains ${showDelimiter(other)}. Change or clear the delimiter under "More reading options".`;
  }

  pickNote(missing) {
    if (this.cells.length > 0 && missing.length > 0) {
      return `No column is chosen yet for ${missing.map((role) => LABELS[role].toLowerCase()).join(", ")}. Pick it above.`;
    }
    return this.matched ? `Matched by name: ${this.matched}. Change it above if that is wrong.` : "";
  }

  explain(spec) {
    const indexes = roleIndexes(spec, this.cells);
    const missing = ["source", "target", "value"].filter((role) => indexes[role] < 0 || indexes[role] >= this.cells.length);
    const text = this.delimiterNote(spec) || this.pickNote(missing);
    this.note.textContent = text;
    this.note.hidden = !text;
  }

  dispose() {
    this.offs.forEach((off) => off());
  }
}

/**
 * Builds the mapping block.
 * @param {{store: object, fields: Record<string, object>}} options  `fields` receives the field objects (for server errors)
 * @returns {{el: HTMLElement, update: (records: string[][]) => void, dispose: () => void}}
 */
export function createMapping({ store, fields }) {
  const mapping = new Mapping(store, fields);
  return { el: mapping.el, update: (records) => mapping.update(records), dispose: () => mapping.dispose() };
}
