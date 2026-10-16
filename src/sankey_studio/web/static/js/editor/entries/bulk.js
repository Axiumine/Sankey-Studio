// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
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
 * `applyBulk(panel, text)` is what the owner's `onApply` runs (moved here from the panel to keep
 * that file under its line cap): it checks the rule, adds it through the committer and toasts.
 * Test ids: `categorise-all-matching`, `categorise-category` (the category input).
 */

import { h, setBusy as busyState, uid } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { icon } from "../../core/icons.js";
import { bulkProblem, describeRule } from "./edits.js";
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

/**
 * Adds the rule "names containing the search text get this category" (the panel's `onApply`).
 * @param {{toolbar: {values: () => {q: string}}, state: object, bulk: ReturnType<typeof createBulk>, committer: {addRule: Function, undoRule: Function}, names: {add: Function}, toast?: {show: Function}, showError: (message: string) => void, clearError: () => void}} panel
 * @param {string} text  the category typed next to the button
 * @returns {Promise<void>}
 */
export async function applyBulk(panel, text) {
  const query = panel.toolbar.values().q;
  const problem = bulkProblem(panel.state, query);
  if (panel.bulk.button.disabled) {
    return; // a rule is being added: Enter held down or pressed twice must not add copies
  }
  if (problem) {
    panel.showError(problem);
    return;
  }
  panel.bulk.setBusy(true);
  const result = await panel.committer.addRule(query, text);
  panel.bulk.setBusy(false);
  if (!result.ok) {
    panel.showError(result.message);
    panel.bulk.category.focus();
    return;
  }
  panel.clearError();
  panel.bulk.category.value = "";
  panel.names.add(result.rule.category);
  panel.toast?.show(`Rule added: ${describeRule(result.rule)} get "${result.rule.category}". You can edit it under Transform.`, {
    kind: "success",
    action: { label: "Undo", onClick: () => panel.committer.undoRule(result.rule) },
  });
}
