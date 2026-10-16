// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Previous / next pager of the library (test ids library-pager-prev, library-pager-next).
 *
 * `createPager({onPage})` returns `{el, update({page, total, pageSize}), hide()}`. The nav is hidden when
 * everything fits on one page. A button that becomes disabled by the click hands its focus to the
 * other one, so keyboard users are not dropped at the top of the document.
 */

import { h } from "../core/dom.js";
import { formatNumber } from "../core/format.js";
import { icon } from "../core/icons.js";

/**
 * @param {{onPage: (page: number) => void}} options
 * @returns {{el: HTMLElement, update: (info: {page: number, total: number, pageSize: number}) => void, hide: () => void}}
 */
export function createPager({ onPage }) {
  let page = 1;
  const status = h("span", { class: "nums pager-status" });
  const prev = h("button", { type: "button", class: "btn btn-sm", "data-testid": "library-pager-prev", on: { click: () => onPage(page - 1) } }, icon("chevron-left"), "Previous");
  const next = h("button", { type: "button", class: "btn btn-sm", "data-testid": "library-pager-next", on: { click: () => onPage(page + 1) } }, "Next", icon("chevron-right"));
  const el = h("nav", { class: "pager", "aria-label": "Pages of graphs", hidden: true }, prev, status, next);

  return {
    el,
    /** Takes the pager away (the list failed to load: there is no page to move from). */
    hide() {
      el.hidden = true;
    },
    update(info) {
      const pages = Math.max(1, Math.ceil(info.total / info.pageSize));
      const focused = [prev, next].find((button) => button === document.activeElement);
      page = Math.min(Math.max(1, info.page), pages);
      status.textContent = `Page ${formatNumber(page, { maximumFractionDigits: 0 })} of ${formatNumber(pages, { maximumFractionDigits: 0 })}`;
      prev.disabled = page <= 1;
      next.disabled = page >= pages;
      el.hidden = pages <= 1;
      if (focused?.disabled) {
        (focused === next ? prev : next).focus();
      }
    },
  };
}
