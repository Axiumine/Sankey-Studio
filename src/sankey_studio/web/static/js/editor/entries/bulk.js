/**
 * "Categorise all entries matching this filter".
 *
 * One click adds ONE glob rule (`*search text*` over source or target names, wildcard characters
 * of the text escaped) instead of thousands of per-entry rows. Rules rank below the data's own
 * categories and below single-entry choices (unless the Transform panel's "rules win" is on), so
 * the note says so. The rules themselves are listed and edited in the Transform panel; the toast
 * that confirms the new rule has an Undo button.
 *
 * `createBulk({onApply})` -> `{el, category, button, update({query, total, loading}), setBusy(bool)}`;
 * `onApply(categoryText)` is called by the button; the owner reports problems through its
 * `category-error` line. The row is hidden while the search box is empty.
 * Test ids: `categorise-all-matching`, `categorise-category` (the category input).
 */

import { h, setBusy as busyState, uid } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { icon } from "../../core/icons.js";
import { CATEGORY_DATALIST_ID } from "./rows.js";

/**
 * @param {{onApply: (categoryText: string) => void}} handlers
 * @returns {object}
 */
export function createBulk({ onApply }) {
  const inputId = uid("bulk-category");
  const count = h("p", { class: "out-bulk-count", role: "status" });
  const note = h("p", { class: "out-note" });
  const category = h("input", {
    id: inputId,
    class: "input",
    type: "text",
    list: CATEGORY_DATALIST_ID,
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "Category, e.g. Housing",
    "data-testid": "categorise-category",
    on: {
      keydown: (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          onApply(category.value);
        }
      },
    },
  });
  const button = h("button", { type: "button", class: "btn btn-primary", "data-testid": "categorise-all-matching", on: { click: () => onApply(category.value) } }, icon("filter", { size: 15 }), "Categorise all entries matching this filter");
  const el = h(
    "div",
    { class: "out-bulk" },
    count,
    h("div", { class: "out-bulk-form" }, h("div", { class: "field" }, h("label", { for: inputId }, "Give them all this category"), category), button),
    note,
  );
  return {
    el,
    category,
    button,
    setBusy: (busy) => busyState(button, busy),
    update({ query, total, loading }) {
      const text = query.trim();
      if (text === "") {
        return;
      }
      count.textContent = loading ? `Looking for entries matching "${text}"...` : `${formatNumber(total, { maximumFractionDigits: 0 })} ${total === 1 ? "entry matches" : "entries match"} "${text}".`;
      note.textContent = `This adds one rule: every entry whose source or target name contains "${text}" gets the category. Categories you set by hand always win, and so do categories in your data unless "Rules win over categories in the data" is on under Transform.`;
    },
  };
}
