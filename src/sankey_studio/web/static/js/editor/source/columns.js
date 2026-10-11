/**
 * Looking at delimited text in the browser: just enough to fill the column pickers and show the
 * first rows. The server does the real parsing; these helpers mirror its rules closely
 * (sources/formats/csv_rows.py, sniff.py) and are only used for hints and previews.
 */

export const ROLES = ["source", "target", "value", "category"];
const DELIMITERS = [",", ";", "\t", "|"];
const BOM = "﻿";
const SYNONYMS = {
  source: ["source", "from", "origin", "src", "start", "sender"],
  target: ["target", "to", "destination", "dest", "end", "receiver", "recipient"],
  value: ["value", "amount", "flow", "weight", "total", "quantity", "qty", "count", "sum", "size"],
};

const count = (text, char) => text.split(char).length - 1;

function consistency(lines, delimiter) {
  const first = count(lines[0] ?? "", delimiter);
  if (first === 0) {
    return [0, 0];
  }
  return [lines.filter((line) => count(line, delimiter) === first).length, first];
}

/**
 * The delimiter that splits the most lines into the same number of columns (comma on a tie).
 * @param {string} sample
 * @returns {string}
 */
export function sniffDelimiter(sample) {
  const lines = sample.replace(BOM, "").slice(0, 4096).split(/\r\n|\r|\n/).filter((line) => line.trim()).slice(0, 20);
  let best = DELIMITERS[0];
  let bestScore = consistency(lines, best);
  for (const delimiter of DELIMITERS.slice(1)) {
    const score = consistency(lines, delimiter);
    if (score[0] > bestScore[0] || (score[0] === bestScore[0] && score[1] > bestScore[1])) {
      [best, bestScore] = [delimiter, score];
    }
  }
  return best;
}

/**
 * The delimiter the server will use for a text source.
 * @param {{delimiter?: string | null}} spec
 * @param {string} format  "csv" | "tsv" (the effective format)
 * @param {string} sample
 * @returns {string}
 */
export function delimiterFor(spec, format, sample) {
  if (spec.delimiter) {
    return spec.delimiter;
  }
  return format === "tsv" ? "\t" : sniffDelimiter(sample);
}

/**
 * The first records of delimited text (quotes and doubled quotes understood), blank lines skipped.
 * @param {string} text
 * @param {string} delimiter
 * @param {number} [limit]
 * @returns {string[][]}
 */
export function parseRecords(text, delimiter, limit = 8) {
  const source = text.startsWith(BOM) ? text.slice(1) : text;
  const records = [];
  let row = [];
  let cell = "";
  let quoted = false;
  const endRecord = () => {
    row.push(cell);
    if (row.some((value) => value.trim() !== "")) {
      records.push(row);
    }
    row = [];
    cell = "";
  };
  for (let i = 0; i < source.length && records.length < limit; i += 1) {
    const char = source[i];
    if (quoted) {
      if (char === '"' && source[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
    } else if (char === '"' && cell === "") {
      quoted = true;
    } else if (char === delimiter) {
      row.push(cell);
      cell = "";
    } else if (char === "\n" || char === "\r") {
      i += char === "\r" && source[i + 1] === "\n" ? 1 : 0;
      endRecord();
    } else {
      cell += char;
    }
  }
  if (records.length < limit && (cell !== "" || row.length > 0)) {
    endRecord();
  }
  return records;
}

/** Header names compare ignoring case and outer spaces. */
export const key = (name) => String(name).trim().toLowerCase();

/**
 * Header names for roles whose default name is missing but a synonym is there
 * ({from, to, amount} -> source, target, value). Never assigns one column twice.
 * @param {string[]} cells  header cells
 * @returns {Partial<Record<"source"|"target"|"value", string>>}
 */
export function guessColumns(cells) {
  const names = cells.map(key);
  const guess = {};
  const taken = new Set();
  for (const role of ["source", "target", "value"]) {
    if (names.includes(role)) {
      taken.add(names.indexOf(role));
    }
  }
  for (const role of ["source", "target", "value"]) {
    if (names.includes(role)) {
      continue;
    }
    const index = names.findIndex((name, position) => !taken.has(position) && SYNONYMS[role].includes(name));
    if (index >= 0) {
      guess[role] = cells[index].trim();
      taken.add(index);
    }
  }
  return guess;
}

function indexOfRef(ref, cells, hasHeader) {
  if (typeof ref === "number") {
    return ref;
  }
  return hasHeader ? cells.findIndex((cell) => key(cell) === key(ref)) : -1;
}

/**
 * Which column each role reads from, as the server resolves it: -1 when none.
 * @param {object} spec  the text source (`source_column`, ..., `has_header`, `detect_category`)
 * @param {string[]} cells  first record (header cells when `has_header`)
 * @returns {Record<"source"|"target"|"value"|"category", number>}
 */
export function roleIndexes(spec, cells) {
  const hasHeader = spec.has_header !== false;
  const out = {};
  ROLES.forEach((role, position) => {
    const ref = spec[`${role}_column`];
    if (ref != null) {
      out[role] = indexOfRef(ref, cells, hasHeader);
    } else if (role === "category") {
      out[role] = hasHeader && spec.detect_category !== false ? cells.findIndex((cell) => key(cell) === "category") : -1;
    } else {
      out[role] = hasHeader ? cells.findIndex((cell) => key(cell) === role) : position;
    }
  });
  return out;
}
