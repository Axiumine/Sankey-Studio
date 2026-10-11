/**
 * The pager under the entries table: "Rows 1-100 of 1,234", Previous, "Page 1 of 13", Next.
 *
 * `createPager({onPage, pageSize})` -> `{el, update({page, pages, total}), label, focusAfter(forward)}`.
 * `onPage(page)` is called with the wanted page (the owner clamps and loads). Test ids:
 * `entries-pager-prev`, `entries-pager-next`.
 */

import { h } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { icon } from "../../core/icons.js";

const whole = (value) => formatNumber(value, { maximumFractionDigits: 0 });

/**
 * @param {{onPage: (page: number) => void, pageSize: number}} options
 * @returns {object}
 */
export function createPager({ onPage, pageSize }) {
  let current = 1;
  const label = h("span", { class: "out-rows-label nums" });
  const page = h("span", { class: "nums" });
  const prev = h("button", { type: "button", class: "btn btn-sm", "data-testid": "entries-pager-prev", on: { click: () => onPage(current - 1) } }, icon("chevron-left"), "Previous");
  const next = h("button", { type: "button", class: "btn btn-sm", "data-testid": "entries-pager-next", on: { click: () => onPage(current + 1) } }, "Next", icon("chevron-right"));
  const el = h("div", { class: "table-foot out-pager" }, label, h("div", { class: "cluster" }, prev, page, next));
  return {
    el,
    label,
    update(state) {
      current = state.page;
      const first = state.total === 0 ? 0 : (state.page - 1) * pageSize + 1;
      const last = Math.min(state.total, state.page * pageSize);
      label.textContent = `Rows ${whole(first)}-${whole(last)} of ${whole(state.total)}`;
      page.textContent = `Page ${state.page} of ${state.pages}`;
      prev.disabled = state.page <= 1;
      next.disabled = state.page >= state.pages;
    },
    /** Puts focus on the button that was used, or on the other one when it just became disabled. */
    focusAfter(forward) {
      const wanted = forward ? [next, prev] : [prev, next];
      wanted.find((button) => !button.disabled)?.focus();
    },
  };
}
