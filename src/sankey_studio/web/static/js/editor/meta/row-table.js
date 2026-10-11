/**
 * An editable table of rows: the editor for manual links, merge pairs and category rules.
 *
 * - Rows live here as text. Only COMPLETE rows (`toItem` returns an item) are committed to the
 *   store through `onCommit(items)`, so a half-typed row never produces a server error; it stays
 *   in the table, marked "Not drawn yet".
 * - `setItems(items)` replaces every row from the store (a loaded graph); call it only when the
 *   items differ from `committed()`, or the rows you are typing in would be rebuilt.
 * - Keyboard: Enter moves to the same column of the next row (and adds a row at the end), Tab
 *   works as usual, a multi-cell paste (tab separated, as copied from a spreadsheet) fills cells
 *   and rows from the cell you pasted into.
 * - Narrow screens turn each row into a small card (CSS), so nothing scrolls sideways.
 * - A server error can be placed on a cell with `setCellError(index, key, message)` (an empty
 *   message clears it), where `index` is the index in the committed items.
 *
 * config: `{caption, columns, toItem, toValues, validate(values, {index, all}), badges, onCommit,
 * maxRows, addLabel, emptyMessage, incompleteHint, reorder, footnote, testids: {table, row, add}}`; a column is
 * `{key, label, kind: "text" | "select", options, suggest, maxlength, placeholder, inputmode,
 * className}`.
 */

import { announce } from "../../core/a11y.js";
import { h, uid } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { appendIndex, buildCell, fillList, iconButton, limitNote, makeDatalists, parseMatrix, placeMatrix, showCellError } from "./row-cells.js";

const isBlank = (values) => Object.values(values).every((v) => String(v).trim() === "");

class RowTable {
  constructor(config) {
    this.config = config;
    this.limit = config.maxRows ?? Infinity;
    this.batching = false;
    this.dropped = 0; // pasted rows that did not fit, until the next edit that removes rows
    this.rows = [];
    this.map = [];
    this.last = [];
    this.lists = makeDatalists(config.columns);
    this.body = h("tbody");
    this.empty = h("p", { class: "ed-rows-empty" }, config.emptyMessage ?? "");
    this.add = h("button", { type: "button", class: "btn btn-sm", "data-testid": config.testids?.add ?? null, on: { click: () => this.addRow(true) } }, icon("plus", { size: 14 }), config.addLabel ?? "Add row");
    this.count = h("span", { class: "ed-rows-count", "aria-live": "polite" });
    this.full = h("p", { class: "hint ed-rows-full", hidden: true });
    this.table = this.buildTable();
    const scroll = h("div", { class: "ed-rows-scroll", tabindex: "0", role: "region", "aria-label": `${config.caption} (scrollable)` }, this.table);
    const note = h("p", { class: "hint", hidden: !config.footnote }, config.footnote);
    this.el = h("div", { class: "ed-rows-wrap" }, scroll, this.empty, h("div", { class: "ed-rows-foot" }, this.add, this.count), this.full, note, Array.from(this.lists.values()));
    this.layout();
  }

  buildTable() {
    const { config } = this;
    const heads = config.columns.map((c) => h("th", { scope: "col", class: c.className ?? null }, c.label));
    const actions = h("th", { scope: "col", class: "ed-rows-actions" }, h("span", { class: "visually-hidden" }, "Row actions"));
    return h("table", { class: "table ed-rows", "data-testid": config.testids?.table ?? null }, h("caption", { class: "visually-hidden" }, config.caption), h("thead", null, h("tr", null, heads, actions)), this.body);
  }

  committed() {
    return this.last;
  }

  setItems(items) {
    this.dropped = 0;
    this.rows = items.map((item) => this.makeRow(this.config.toValues(item)));
    this.last = items;
    this.map = items.map((_, index) => index);
    this.layout();
  }

  addRow(focus, values = {}) {
    if (this.rows.length >= this.limit) {
      announce(`Limit reached: at most ${this.limit} rows.`);
      return null;
    }
    const blank = Object.fromEntries(this.config.columns.map((c) => [c.key, c.kind === "select" ? c.options[0].value : ""]));
    const row = this.makeRow({ ...blank, ...values });
    this.rows.push(row);
    if (!this.batching) {
      this.layout();
    }
    if (focus) {
      row.controls[this.config.columns[0].key].focus();
    }
    return row;
  }

  makeRow(values) {
    const row = { id: uid("row"), values: { ...values }, controls: {}, errors: {}, notes: {}, server: new Set() };
    const cells = this.config.columns.map((column) => buildCell(row, column, { list: this.lists.get(column.key), on: this.handlers(row, column) }));
    row.state = h("span", { class: "ed-row-flag", hidden: true, title: this.config.incompleteHint ?? "Not drawn yet: fill in every column." }, icon("alert", { size: 14 }), h("span", { class: "ed-row-flag-text" }, "Not drawn yet"));
    row.badgeText = h("span", { class: "ed-row-flag-text" });
    row.badge = h("span", { class: "ed-row-flag", hidden: true }, icon("copy", { size: 14 }), row.badgeText);
    row.buttons = this.actionButtons(row);
    const actions = h("td", { class: "ed-rows-actions" }, h("div", { class: "ed-row-actions" }, row.state, row.badge, Object.values(row.buttons)));
    row.el = h("tr", { class: "ed-row", "data-testid": this.config.testids?.row ?? null }, cells, actions);
    return row;
  }

  handlers(row, column) {
    return {
      edit: () => {
        row.values[column.key] = row.controls[column.key].value;
        this.commit();
      },
      keydown: (event) => this.onKey(event, row, column),
      paste: (event) => this.onPaste(event, row, column),
      focus: () => fillList(this.lists.get(column.key), column),
    };
  }

  actionButtons(row) {
    const buttons = {};
    if (this.config.reorder) {
      buttons.up = iconButton("arrow-up", "Move up", () => this.move(row, -1));
      buttons.down = iconButton("arrow-down", "Move down", () => this.move(row, 1));
    }
    buttons.remove = iconButton("trash", "Remove row", () => this.removeRow(row));
    return buttons;
  }

  cellError(row, key, message) {
    if ((row.errors[key] ?? "") === message) {
      return;
    }
    row.errors[key] = message;
    showCellError(row, key, message);
  }

  /** Validates every row, commits the complete ones; `structural` when rows were added/moved/removed. */
  commit(structural = false) {
    const items = [];
    this.map = [];
    const all = this.rows.map((row) => row.values);
    this.rows.forEach((row, rowIndex) => {
      const problems = this.config.validate?.(row.values, { index: rowIndex, all }) ?? {};
      row.server.clear();
      for (const column of this.config.columns) {
        this.cellError(row, column.key, problems[column.key] ?? "");
      }
      const item = Object.keys(problems).length === 0 ? this.config.toItem(row.values) : null;
      if (item) {
        this.map.push(rowIndex);
        items.push(item);
      }
    });
    this.last = items;
    if (structural) {
      this.layout();
    } else {
      this.paint();
    }
    this.config.onCommit(items);
  }

  /** Rebuilds the row list after a structural change. */
  layout() {
    this.body.replaceChildren(...this.rows.map((row) => row.el));
    this.rows.forEach((row, index) => this.relabel(row, index));
    this.paint();
  }

  relabel(row, index) {
    for (const column of this.config.columns) {
      row.controls[column.key].setAttribute("aria-label", `${column.label}, row ${index + 1}`);
    }
    row.buttons.remove.setAttribute("aria-label", `Remove row ${index + 1}`);
    if (row.buttons.up) {
      row.buttons.up.setAttribute("aria-label", `Move row ${index + 1} up`);
      row.buttons.down.setAttribute("aria-label", `Move row ${index + 1} down`);
      row.buttons.up.disabled = index === 0;
      row.buttons.down.disabled = index === this.rows.length - 1;
    }
  }

  /** Updates the per-row state, badges and counters (no DOM moves, so focus stays put). */
  paint() {
    const notes = this.config.badges?.(this.rows.map((row) => row.values)) ?? [];
    let filled = 0;
    this.rows.forEach((row, index) => {
      const blank = isBlank(row.values);
      const ready = blank || (this.config.toItem(row.values) !== null && Object.values(row.errors).every((e) => !e));
      filled += blank ? 0 : 1;
      row.state.hidden = ready;
      row.el.dataset.state = ready ? "ready" : "partial";
      row.badgeText.textContent = notes[index] ?? "";
      row.badge.title = notes[index] ?? "";
      row.badge.hidden = !notes[index];
    });
    this.empty.hidden = this.rows.length > 0;
    this.table.hidden = this.rows.length === 0;
    this.count.textContent = filled !== this.last.length ? `${this.last.length} of ${filled} rows drawn` : "";
    this.add.disabled = this.rows.length >= this.limit;
    this.full.textContent = limitNote(this.limit, this.rows.length, this.dropped);
    this.full.hidden = !this.full.textContent;
  }

  removeRow(row) {
    const index = this.rows.indexOf(row);
    this.rows.splice(index, 1);
    this.dropped = 0;
    this.commit(true);
    const next = this.rows[Math.min(index, this.rows.length - 1)];
    (next ? next.controls[this.config.columns[0].key] : this.add).focus();
    announce(`Row ${index + 1} removed`);
  }

  move(row, delta) {
    const index = this.rows.indexOf(row);
    const target = index + delta;
    if (target < 0 || target >= this.rows.length) {
      return;
    }
    this.rows.splice(index, 1);
    this.rows.splice(target, 0, row);
    this.commit(true);
    const button = delta < 0 ? row.buttons.up : row.buttons.down;
    (button.disabled ? row.buttons.remove : button).focus();
    announce(`Row moved to position ${target + 1}`);
  }

  focusCell(rowIndex, key) {
    this.rows[rowIndex]?.controls[key].focus();
  }

  onKey(event, row, column) {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || column.kind === "select") {
      return;
    }
    event.preventDefault();
    const index = this.rows.indexOf(row);
    if (index < this.rows.length - 1) {
      this.focusCell(index + 1, column.key);
    } else {
      this.addRow(false)?.controls[column.key].focus();
    }
  }

  onPaste(event, row, column) {
    const text = event.clipboardData?.getData("text") ?? "";
    if (!/[\t\n]/.test(text.replace(/\n$/, ""))) {
      return;
    }
    event.preventDefault();
    this.pasteMatrix(text, this.rows.indexOf(row), this.config.columns.indexOf(column));
  }

  /** Fills cells from a tab separated block, starting at (rowIndex, columnIndex). Rows that do not fit are reported. */
  pasteMatrix(text, rowIndex, columnIndex) {
    const lines = parseMatrix(text);
    this.batching = true;
    const grid = { rows: this.rows, columns: this.config.columns, addRow: () => this.addRow(false) };
    const placed = placeMatrix(grid, lines, rowIndex, columnIndex);
    this.batching = false;
    this.dropped = lines.length - placed;
    this.commit(true);
    const noun = (n) => `${n.toLocaleString("en-US")} ${n === 1 ? "row" : "rows"}`;
    announce(`Pasted ${noun(placed)}${this.dropped > 0 ? `. ${noun(this.dropped)} did not fit` : ""}`);
  }

  /** Shows (or clears, with an empty message) a server error on one cell; `index` counts committed items. */
  setCellError(index, key, message) {
    const row = this.rows[this.map[index]];
    if (!row?.controls[key]) {
      return;
    }
    if (message === "") {
      if (row.server.delete(key)) {
        this.cellError(row, key, "");
      }
    } else if (!row.errors[key]) {
      this.cellError(row, key, message);
      row.server.add(key);
    }
  }
}

/**
 * Creates the row editor; see the file header.
 * @param {object} config
 * @returns {{el: HTMLElement, table: HTMLTableElement, addButton: HTMLButtonElement, setItems: (items: object[]) => void, committed: () => object[], addRow: (focus?: boolean, values?: object) => unknown, pasteMatrix: (text: string, rowIndex: number, columnIndex: number) => void, focusCell: (rowIndex: number, key: string) => void, setCellError: (index: number, key: string, message: string) => void, rowCount: () => number, appendIndex: () => number}}
 */
export function createRowTable(config) {
  const table = new RowTable(config);
  return {
    el: table.el,
    table: table.table,
    addButton: table.add,
    setItems: (items) => table.setItems(items),
    committed: () => table.committed(),
    addRow: (focus = false, values = {}) => table.addRow(focus, values),
    pasteMatrix: (text, rowIndex, columnIndex) => table.pasteMatrix(text, rowIndex, columnIndex),
    focusCell: (rowIndex, key) => table.focusCell(rowIndex, key),
    setCellError: (index, key, message) => table.setCellError(index, key, message),
    rowCount: () => table.rows.length,
    appendIndex: () => appendIndex(table.rows),
  };
}
