/**
 * Cell, action-button and clipboard helpers of the row editor (row-table.js).
 *
 * Kept apart so the table logic stays readable: building one cell (input or select plus its error
 * line), the per-row buttons, the datalists that feed suggestions, and parsing a block pasted
 * from a spreadsheet.
 */

import { h, uid } from "../../core/dom.js";
import { selectInput, textInput } from "../../core/form.js";
import { icon } from "../../core/icons.js";
import { stripBidi } from "../../core/text.js";

/**
 * A small icon-only button with an accessible name.
 * @param {string} name  icon name
 * @param {string} label
 * @param {() => void} onClick
 * @returns {HTMLButtonElement}
 */
export function iconButton(name, label, onClick) {
  return h("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": label, title: label, on: { click: onClick } }, icon(name, { size: 14 }));
}

/**
 * One datalist per column that has suggestions.
 * @param {{key: string, suggest?: () => string[]}[]} columns
 * @returns {Map<string, HTMLDataListElement>}
 */
export function makeDatalists(columns) {
  const lists = new Map();
  for (const column of columns.filter((c) => c.suggest)) {
    lists.set(column.key, h("datalist", { id: uid("rows-list") }));
  }
  return lists;
}

/**
 * Refills a column's datalist (called when a cell of the column gets focus).
 * @param {HTMLDataListElement | undefined} list
 * @param {{suggest?: () => string[]}} column
 */
export function fillList(list, column) {
  if (list && column.suggest) {
    list.replaceChildren(...column.suggest().slice(0, 300).map((text) => h("option", { value: text })));
  }
}

/**
 * Builds the `<td>` of one cell and registers its control and error line on `row`.
 * @param {{values: object, controls: object, notes: object}} row
 * @param {object} column
 * @param {{list?: HTMLDataListElement, on: Record<string, EventListener>}} wiring  `on` holds the
 *   event handlers (keydown, paste, and `edit` for input/change)
 * @returns {HTMLTableCellElement}
 */
export function buildCell(row, column, wiring) {
  const common = { value: row.values[column.key] ?? "", "data-key": column.key };
  const { edit, ...events } = wiring.on;
  const control = column.kind === "select"
    ? selectInput({ ...common, options: column.options, on: { ...events, change: edit } })
    : textInput({
      ...common,
      inputmode: column.inputmode ?? null,
      maxlength: column.maxlength ?? null,
      placeholder: column.placeholder ?? null,
      list: wiring.list?.id ?? null,
      on: { ...events, input: edit },
    });
  const error = h("p", { class: "field-error ed-cell-error", id: uid("cell-error"), hidden: true });
  control.setAttribute("aria-describedby", error.id);
  row.controls[column.key] = control;
  row.notes[column.key] = error;
  return h("td", { "data-label": column.label, class: column.className ?? null }, control, error);
}

/**
 * Shows or clears the error line of one cell.
 * @param {{controls: object, notes: object}} row
 * @param {string} key
 * @param {string} message
 */
export function showCellError(row, key, message) {
  row.notes[key].textContent = stripBidi(message);
  row.notes[key].hidden = !message;
  row.controls[key].setAttribute("aria-invalid", message ? "true" : "false");
}

/**
 * Splits a block copied from a spreadsheet into lines of cells (tab separated).
 * @param {string} text
 * @returns {string[][]}
 */
export function parseMatrix(text) {
  return text.replace(/\r\n?/g, "\n").replace(/\n$/, "").split("\n").map((line) => line.split("\t").map((cell) => cell.trim()));
}

/**
 * Sets a cell's text; for a select the text must match an option's value or label.
 * @param {{values: object, controls: object}} row
 * @param {object} column
 * @param {string} text
 */
export function setCellText(row, column, text) {
  let next = text;
  if (column.kind === "select") {
    const match = column.options.find((o) => o.value === text || o.label.toLowerCase() === text.toLowerCase());
    if (!match) {
      return;
    }
    next = match.value;
  }
  row.controls[column.key].value = next;
  row.values[column.key] = next;
}

/**
 * Puts pasted lines into the rows, from (rowIndex, columnIndex) on, adding rows while there is room.
 * @param {{rows: object[], columns: object[], addRow: () => (object | null)}} table  `addRow` returns null when the table is full
 * @param {string[][]} lines  from `parseMatrix`
 * @param {number} rowIndex
 * @param {number} columnIndex
 * @returns {number}  how many lines found a row (the rest did not fit)
 */
export function placeMatrix(table, lines, rowIndex, columnIndex) {
  let placed = 0;
  for (const [offset, cells] of lines.entries()) {
    const row = table.rows[rowIndex + offset] ?? table.addRow();
    if (!row) {
      break;
    }
    placed += 1;
    cells.forEach((cell, shift) => {
      const column = table.columns[columnIndex + shift];
      if (column) {
        setCellText(row, column, cell);
      }
    });
  }
  return placed;
}

/**
 * The visible note about a table that cannot take more rows ("" when there is room).
 * @param {number} limit
 * @param {number} rows  rows in the table
 * @param {number} dropped  pasted rows that did not fit
 * @returns {string}
 */
export function limitNote(limit, rows, dropped) {
  const count = (n) => `${n.toLocaleString("en-US")} ${n === 1 ? "row" : "rows"}`;
  if (dropped > 0) {
    return `A table holds at most ${count(limit)}. ${count(dropped)} of the pasted data did not fit and ${dropped === 1 ? "was" : "were"} left out.`;
  }
  return rows >= limit ? `The table is full: it holds at most ${count(limit)}.` : "";
}

/**
 * Where rows pasted "at the end" go: right after the last row that has something in it, so a
 * trailing blank row (a new table starts with one) is filled instead of left on top.
 * @param {{values: Record<string, unknown>}[]} rows
 * @returns {number}
 */
export function appendIndex(rows) {
  let end = rows.length;
  while (end > 0 && Object.values(rows[end - 1].values).every((value) => String(value).trim() === "")) {
    end -= 1;
  }
  return end;
}
