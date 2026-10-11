/**
 * The entries table body: one keyed `<tr>` per (source, target) pair.
 *
 * Why keyed: a category cell is a text input that people tab through quickly. A refetch must
 * update numbers and labels in place and never rebuild an input that has focus or unsaved text,
 * otherwise typing into row 2 while row 1's save comes back would lose the caret.
 *
 * `createRowsView({onCommit, onNext})` -> `{el, update(rows), setPending(entry, bool), setInvalid(entry, bool),
 * setValue(entry, patch, {keepText}), rowOf(entry), focusInput(entry), neighbour(entry, step), size()}` where
 * - `el` is the `<table data-testid="entries-table">` (with `thead` and `tbody`),
 * - `onCommit(entry, text, input)` is called for Enter, blur and a picked datalist option,
 * - `onNext(entry, step)` asks for the neighbouring row's input (+1 Enter, -1 Shift+Enter).
 * A row is `{source, target, value, category, mixed, overridden}` (an `EntryRow` of POST /entries).
 * Test ids: `entries-table`, `entries-row` (data-source, data-target), `category-cell` (the input),
 * `category-clear`. Cells are built with `h()`, so every name is a text node.
 */

import { h } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { icon } from "../../core/icons.js";
import { pairLabel } from "../output-panel-kit.js";

const DATALIST_ID = "category-datalist";

function keyOf(entry) {
  return `${entry.source}\u0000${entry.target}`;
}

function badgeFor(row) {
  if (row.mixed) {
    return { text: "Mixed", title: "This pair has several categories in the data. The biggest one is shown; typing a category sets them all." };
  }
  if (row.overridden && row.category == null) {
    return { text: "None, on purpose", title: "You cleared this entry, so it stays uncategorised even if the data or a rule has a category for it." };
  }
  return null;
}

class RowsView {
  constructor(options) {
    this.options = options;
    this.rows = new Map();
    this.tbody = h("tbody");
    this.el = h(
      "table",
      { class: "table out-entries", "data-testid": "entries-table" },
      h("caption", { class: "visually-hidden" }, "Entries: one row per source to target flow, with an optional category"),
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Source"), h("th", { scope: "col" }, "Target"), h("th", { scope: "col", class: "num" }, "Value"), h("th", { scope: "col" }, "Category (optional)"))),
      this.tbody,
    );
  }

  build(row) {
    const label = pairLabel(row.source, row.target);
    const input = h("input", {
      class: "input out-cat-input",
      type: "text",
      list: DATALIST_ID,
      autocomplete: "off",
      spellcheck: "false",
      placeholder: "Add a category",
      "aria-label": `Category for ${label}`,
      "data-testid": "category-cell",
    });
    const clear = h("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm out-cat-clear", "aria-label": `Clear category of ${label}`, "data-testid": "category-clear" }, icon("x", { size: 14 }));
    const meta = h("span", { class: "out-cat-meta" });
    const cells = {
      source: h("td", { "data-label": "Source" }),
      target: h("td", { "data-label": "Target" }),
      value: h("td", { class: "num", "data-label": "Value" }),
    };
    const tr = h(
      "tr",
      { "data-testid": "entries-row", "data-source": row.source, "data-target": row.target },
      cells.source,
      cells.target,
      cells.value,
      h("td", { class: "out-cat-cell", "data-label": "Category" }, h("div", { class: "out-cat-field" }, input, clear), meta),
    );
    const item = { tr, input, clear, meta, cells, row: null };
    this.wire(item);
    return item;
  }

  wire(item) {
    const entry = () => ({ source: item.tr.dataset.source, target: item.tr.dataset.target });
    const commit = () => this.options.onCommit(entry(), item.input.value, item.input);
    item.input.addEventListener("input", () => {
      item.input.dataset.touched = "true";
      item.input.setAttribute("aria-invalid", "false");
    });
    item.input.addEventListener("change", commit);
    item.input.addEventListener("blur", commit);
    item.input.addEventListener("keydown", (event) => this.onKey(event, item, entry));
    item.clear.addEventListener("click", () => {
      item.input.value = "";
      item.input.dataset.touched = "true";
      commit();
      item.input.focus();
    });
  }

  onKey(event, item, entry) {
    const input = item.input;
    if (event.isComposing || event.keyCode === 229) {
      return; // Enter confirms an IME candidate here, it is not a commit
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      input.dataset.arrows = "true";
    } else if (event.key.length === 1) {
      delete input.dataset.arrows;
    }
    if (event.key === "Enter") {
      this.onEnter(event, item, entry);
    } else if (event.key === "Escape" && input.dataset.touched === "true") {
      event.preventDefault();
      event.stopPropagation();
      input.value = item.row?.category ?? "";
      delete input.dataset.touched;
    }
  }

  /**
   * Enter commits and moves on. After the arrow keys the browser may still be applying a datalist
   * suggestion, so then the commit waits one tick; without them the typed text is final and the
   * commit and the focus move happen at once (fast typing must land in the right row).
   */
  onEnter(event, item, entry) {
    const input = item.input;
    const viaSuggestions = input.dataset.arrows === "true";
    delete input.dataset.arrows;
    const go = () => {
      this.options.onCommit(entry(), input.value, input);
      this.options.onNext(entry(), event.shiftKey ? -1 : 1);
    };
    if (viaSuggestions) {
      setTimeout(go, 0);
    } else {
      go();
    }
  }

  paint(item, row) {
    item.row = row;
    item.cells.source.textContent = row.source;
    item.cells.target.textContent = row.target;
    item.cells.value.textContent = formatNumber(row.value);
    this.paintInput(item, row);
    const badge = badgeFor(row);
    item.meta.replaceChildren(...(badge ? [h("span", { class: "badge", title: badge.title }, badge.text)] : []));
    item.clear.disabled = row.category == null && !row.overridden;
    item.tr.dataset.category = row.category ?? "";
    item.tr.toggleAttribute("data-categorised", row.category != null);
  }

  paintInput(item, row) {
    const editing = document.activeElement === item.input || item.input.dataset.touched === "true";
    if (!editing) {
      item.input.value = row.category ?? "";
    }
  }

  /** Shows `rows` (an EntriesPage page), reusing the elements of rows that are still there. */
  update(rows) {
    const next = new Map();
    const focused = document.activeElement;
    for (const row of rows) {
      const key = keyOf(row);
      const item = this.rows.get(key) ?? this.build(row);
      this.paint(item, row);
      next.set(key, item);
    }
    this.rows = next;
    const wanted = Array.from(next.values()).map((item) => item.tr);
    this.reorder(wanted);
    if (focused instanceof HTMLElement && focused !== document.activeElement && this.el.contains(focused)) {
      focused.focus({ preventScroll: true }); // moving a row blurs its input: give the caret back
    }
  }

  reorder(wanted) {
    wanted.forEach((tr, index) => {
      if (this.tbody.children[index] !== tr) {
        this.tbody.insertBefore(tr, this.tbody.children[index] ?? null);
      }
    });
    while (this.tbody.children.length > wanted.length) {
      this.tbody.lastElementChild.remove();
    }
  }

  item(entry) {
    return this.rows.get(keyOf(entry));
  }

  /**
   * Makes a row show `patch` (an optimistic edit, or a roll back). The input text is reset to the
   * row's category unless `keepText` is set: a rejected edit keeps what the person typed so they can
   * fix it.
   */
  setValue(entry, patch, { keepText = false } = {}) {
    const item = this.item(entry);
    if (!item) {
      return;
    }
    if (keepText) {
      item.input.dataset.touched = "true"; // paint() must not overwrite the text that was refused
    } else {
      delete item.input.dataset.touched;
    }
    this.paint(item, { ...item.row, ...patch });
  }

  setPending(entry, pending) {
    this.item(entry)?.tr.toggleAttribute("aria-busy", pending);
  }

  setInvalid(entry, invalid) {
    const input = this.item(entry)?.input;
    if (input) {
      input.setAttribute("aria-invalid", String(invalid));
    }
  }

  rowOf(entry) {
    return this.item(entry)?.row ?? null;
  }

  focusInput(entry) {
    const item = this.item(entry);
    item?.input.focus();
    return Boolean(item);
  }

  /** The entry `step` rows away from `entry` (null at the ends). */
  neighbour(entry, step) {
    const keys = Array.from(this.rows.keys());
    const at = keys.indexOf(keyOf(entry)) + step;
    const item = this.rows.get(keys[at]);
    return item ? { source: item.tr.dataset.source, target: item.tr.dataset.target } : null;
  }

  size() {
    return this.rows.size;
  }
}

/**
 * Creates the table view.
 * @param {{onCommit: (entry: object, text: string, input: HTMLInputElement) => void, onNext: (entry: object, step: number) => void}} options
 * @returns {RowsView}
 */
export function createRowsView(options) {
  return new RowsView(options);
}

/** The id of the shared `<datalist>` the category inputs point at. */
export const CATEGORY_DATALIST_ID = DATALIST_ID;
