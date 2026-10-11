/**
 * The "Paste rows" dialog of the Manual tab: text copied from a spreadsheet or a CSV file becomes
 * rows of the links table (source, target, value and an optional category).
 *
 * Reading rules (`pastedRows`):
 * - a block where every line holds a tab is tab separated (what a spreadsheet copies), whatever
 *   else it contains; otherwise the delimiter is sniffed (comma, semicolon, tab or pipe);
 * - a value such as "3000,5" or "1.234,5" (comma decimals) becomes 3000.5 or 1234.5; an
 *   ambiguous "1,500" is left alone and shows as a value to fix;
 * - the first row is a header, and skipped, only when its value cell is not a number and either
 *   says "value", "amount", ... or the rows after it do have numbers.
 */

import { h } from "../../core/dom.js";
import { textArea } from "../../core/form.js";
import { openDialog } from "../../core/dialog.js";
import { parseNumber } from "../meta/util.js";
import { parseRecords, sniffDelimiter } from "./columns.js";

const MAX_PASTED = 100000; // read this many pasted rows so "N did not fit" is the real count
const VALUE_WORDS = /^(?:value|amount|flow|weight|total|quantity|qty|count|sum|size)$/i;
const DECIMAL_COMMA = /^[-+]?(?:\d+|\d{1,3}(?:\.\d{3})+),(?:\d{1,2}|\d{4,})$/;
const HEADER_NOTE = "The first row was skipped because it looks like a header.";

const isNumber = (text) => !Number.isNaN(parseNumber(text ?? ""));

function commaToPoint(text) {
  const clean = text.trim();
  return DECIMAL_COMMA.test(clean) ? clean.replaceAll(".", "").replace(",", ".") : text;
}

function delimiterOf(text) {
  const lines = text.split(/\r\n|\r|\n/).filter((line) => line.trim() !== "");
  return lines.length > 0 && lines.every((line) => line.includes("\t")) ? "\t" : sniffDelimiter(text);
}

function isHeader([first, ...rest]) {
  if (!first || isNumber(first[2])) {
    return false;
  }
  return VALUE_WORDS.test((first[2] ?? "").trim()) || rest.some((row) => isNumber(row[2]));
}

/**
 * Reads pasted text into table rows.
 * @param {string} text
 * @returns {{text: string, count: number, skippedHeader: boolean}}  `text` is tab separated, one row per line
 */
export function pastedRows(text) {
  const records = parseRecords(text, delimiterOf(text), MAX_PASTED).map((row) => row.slice(0, 4).map((cell, index) => (index === 2 ? commaToPoint(cell) : cell)));
  const skippedHeader = isHeader(records);
  const rows = skippedHeader ? records.slice(1) : records;
  return { text: rows.map((row) => row.join("\t")).join("\n"), count: rows.length, skippedHeader };
}

/**
 * Opens the dialog; "Add rows" appends what was read to `table` (a core row table).
 * @param {{pasteMatrix: Function, appendIndex: () => number}} table
 * @param {{info: (message: string) => void} | undefined} toast
 */
export function openPasteRows(table, toast) {
  const box = textArea({ code: true, rows: 8, wrap: "off", placeholder: "source,target,value,category\nSalary,Budget,3000,Income", "aria-label": "Rows to add" });
  const problem = h("p", { class: "field-error", role: "alert", hidden: true });
  const body = h("div", { class: "stack stack-sm" }, h("p", null, "Paste rows with the columns source, target, value and (optionally) category. Commas, semicolons and tabs all work, so you can copy straight from a spreadsheet. A table holds up to 5,000 rows."), box, problem);
  box.addEventListener("input", () => {
    problem.hidden = true;
  });
  openDialog({
    title: "Paste rows",
    body,
    initialFocus: () => box,
    actions: [
      { label: "Cancel", value: false },
      {
        label: "Add rows",
        kind: "primary",
        onClick: (close) => {
          const read = pastedRows(box.value);
          if (read.count === 0) {
            problem.textContent = read.skippedHeader ? "Only a header row was found. Paste the rows under it as well." : "There is nothing to add yet. Paste at least one row first.";
            problem.hidden = false;
            box.focus();
            return;
          }
          table.pasteMatrix(read.text, table.appendIndex(), 0);
          close(true);
          if (read.skippedHeader) {
            toast?.info(HEADER_NOTE);
          }
        },
      },
    ],
  });
}
