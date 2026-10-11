/**
 * Accessible data table with optional sorting and paging.
 *
 * `createTable(config)` returns `{el, update(patch), destroy()}`.
 *
 * config
 * - caption (required): the table's accessible name (a visually hidden <caption>, also the
 *   label of the scroll region).
 * - columns: `[{key, label, sortable, numeric, rowHeader, render(row, index), value(row)}]`.
 *   Cells are text (`textContent`) unless `render` returns a Node. `numeric` right-aligns with
 *   tabular figures; `rowHeader` makes the cell a `<th scope="row">`. Headers are
 *   `<th scope="col">`; sortable ones hold a button and carry `aria-sort`.
 * - rows, rowProps(row, index) (attributes for the <tr>, e.g. data-testid), empty (text or Node).
 * - mode "client" (default): the table sorts and pages `rows` itself.
 *   mode "server": `rows` is the current page as delivered; `total`, `page` and `sort` are
 *   shown as given, `onChange({page, sort})` fires on interaction and the owner calls
 *   `update({rows, total, page})` when the data arrived.
 * - pageSize (0 = no paging), page (1-based), sort `{key, dir: "asc"|"desc"}`, total (server).
 * - testids: `{table, row, prev, next, total}` become data-testid values; labels:
 *   `{prev, next}` for the pager buttons.
 *
 * `update({rows, total, page, sort})` re-renders (a pager button, sort button or scroll region that had
 * keyboard focus keeps it). Page changes are announced to screen readers.
 */

import { announce } from "./a11y.js";
import { h, uid } from "./dom.js";
import { icon } from "./icons.js";

const DASH = "–";

function cellValue(column, row) {
  return column.value ? column.value(row) : row[column.key];
}

function compare(a, b) {
  if (a == null && b == null) {
    return 0;
  }
  if (a == null) {
    return 1;
  }
  if (b == null) {
    return -1;
  }
  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

function sortRows(rows, columns, sort) {
  const column = columns.find((c) => c.key === sort?.key);
  if (!column) {
    return rows;
  }
  const sign = sort.dir === "desc" ? -1 : 1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => sign * compare(cellValue(column, a.row), cellValue(column, b.row)) || a.index - b.index)
    .map((item) => item.row);
}

function renderCell(column, row, index) {
  const content = column.render ? column.render(row, index) : cellValue(column, row);
  const shown = content == null || content === "" ? DASH : content;
  const props = { class: column.numeric ? "num" : null };
  return column.rowHeader ? h("th", { ...props, scope: "row" }, shown) : h("td", props, shown);
}

function ariaSort(sort, column) {
  if (!column.sortable) {
    return null;
  }
  if (sort?.key !== column.key) {
    return "none";
  }
  return sort.dir === "desc" ? "descending" : "ascending";
}

function headerCell(column, state, requestSort) {
  const sorted = ariaSort(state.sort, column);
  const label = column.label ?? column.key;
  if (!column.sortable) {
    return h("th", { scope: "col", class: column.numeric ? "num" : null }, label);
  }
  const arrow = sorted === "ascending" ? "arrow-up" : sorted === "descending" ? "arrow-down" : "sort";
  const button = h(
    "button",
    { type: "button", class: "sort-button", on: { click: () => requestSort(column.key) } },
    label,
    icon(arrow, { size: 14 }),
  );
  return h("th", { scope: "col", "aria-sort": sorted, class: column.numeric ? "num" : null }, button);
}

function pageCount(state) {
  const total = state.total ?? state.rows.length;
  return state.pageSize > 0 ? Math.max(1, Math.ceil(total / state.pageSize)) : 1;
}

function visibleRows(state) {
  if (state.mode === "server") {
    return state.rows;
  }
  const sorted = sortRows(state.rows, state.columns, state.sort);
  if (state.pageSize <= 0) {
    return sorted;
  }
  const start = (state.page - 1) * state.pageSize;
  return sorted.slice(start, start + state.pageSize);
}

function footer(state, goTo) {
  const total = state.total ?? state.rows.length;
  if (state.pageSize <= 0 && state.mode !== "server") {
    return null;
  }
  const first = total === 0 ? 0 : (state.page - 1) * state.pageSize + 1;
  const last = Math.min(total, state.page * state.pageSize);
  const pages = pageCount(state);
  const ids = state.testids;
  const labels = { prev: "Previous page", next: "Next page", ...state.labels };
  return h(
    "div",
    { class: "table-foot" },
    h("span", { "data-testid": ids.total ?? null }, total === 0 ? "No rows" : `Rows ${first}–${last} of ${total}`),
    h(
      "div",
      { class: "cluster" },
      h("button", { type: "button", class: "btn btn-sm", "data-pager": "prev", "data-testid": ids.prev ?? null, disabled: state.page <= 1, on: { click: () => goTo(state.page - 1) } }, icon("chevron-left"), labels.prev),
      h("span", { class: "nums" }, `Page ${state.page} of ${pages}`),
      h("button", { type: "button", class: "btn btn-sm", "data-pager": "next", "data-testid": ids.next ?? null, disabled: state.page >= pages, on: { click: () => goTo(state.page + 1) } }, labels.next, icon("chevron-right")),
    ),
  );
}

/** What had keyboard focus inside the table before a re-render, so it can be given back. */
function focusMemo(el) {
  const active = document.activeElement;
  if (!active || !el.contains(active)) {
    return null;
  }
  if (active.dataset.pager) {
    return { pager: active.dataset.pager };
  }
  const buttons = Array.from(el.querySelectorAll(".sort-button"));
  const index = buttons.indexOf(active);
  if (index >= 0) {
    return { sort: index };
  }
  return active.classList.contains("table-wrap") ? { wrap: true } : null;
}

function restoreFocus(el, memo) {
  if (!memo) {
    return;
  }
  if (memo.pager) {
    focusPager(el, memo.pager);
  } else if (memo.sort !== undefined) {
    el.querySelectorAll(".sort-button")[memo.sort]?.focus();
  } else {
    el.querySelector(".table-wrap")?.focus();
  }
}

function focusPager(el, preferred) {
  const other = preferred === "prev" ? "next" : "prev";
  const target = [preferred, other]
    .map((name) => el.querySelector(`[data-pager="${name}"]:not([disabled])`))
    .find(Boolean);
  (target ?? el.querySelector(".table-wrap"))?.focus();
}

function buildTable(state, captionId, requestSort) {
  const { columns, testids } = state;
  const rows = visibleRows(state);
  const body = rows.length === 0
    ? h("tr", null, h("td", { colspan: columns.length, class: "text-muted" }, state.empty))
    : rows.map((row, index) => h("tr", state.rowProps ? state.rowProps(row, index) : null, columns.map((c) => renderCell(c, row, index))));
  return h(
    "table",
    { class: "table", "data-testid": testids.table ?? null },
    h("caption", { id: captionId, class: "visually-hidden" }, state.caption),
    h("thead", null, h("tr", null, columns.map((c) => headerCell(c, state, requestSort)))),
    h("tbody", null, body),
  );
}

/**
 * Creates a table block (scroll region, table and pager).
 * @param {object} config  see the file header
 * @returns {{el: HTMLElement, update: (patch: object) => void, destroy: () => void}}
 */
export function createTable(config) {
  const state = {
    mode: "client", pageSize: 0, page: 1, sort: null, total: null, rows: [], testids: {}, empty: "Nothing to show.",
    ...config,
  };
  const captionId = uid("table-caption");
  const el = h("div", { class: "table-block" });

  const render = () => {
    const memo = focusMemo(el); // an update() after a click rebuilds the buttons: keep the focus
    state.page = Math.min(Math.max(1, state.page), pageCount(state));
    const region = h(
      "div",
      { class: "table-wrap", role: "region", "aria-labelledby": captionId, tabindex: "0" },
      buildTable(state, captionId, requestSort),
    );
    el.replaceChildren(region, ...[footer(state, goTo)].filter(Boolean));
    restoreFocus(el, memo);
  };
  const notify = () => state.onChange?.({ page: state.page, sort: state.sort });
  const goTo = (page) => {
    const before = state.page;
    state.page = page;
    render();
    announce(`Page ${state.page} of ${pageCount(state)}`);
    notify();
    focusPager(el, page < before ? "prev" : "next");
  };
  const requestSort = (key) => {
    const dir = state.sort?.key === key && state.sort.dir === "asc" ? "desc" : "asc";
    state.sort = { key, dir };
    state.page = 1;
    render();
    announce(`Sorted by ${state.columns.find((c) => c.key === key)?.label ?? key}, ${dir === "asc" ? "ascending" : "descending"}`);
    notify();
    el.querySelector('th[aria-sort="ascending"] .sort-button, th[aria-sort="descending"] .sort-button')?.focus();
  };

  render();
  return {
    el,
    update(patch) {
      Object.assign(state, patch);
      render();
    },
    destroy() {
      el.replaceChildren();
    },
  };
}
