/**
 * The notice above the entries rows when the last refresh failed ("The rows below are the last ones
 * that loaded").
 *
 * `createStaleNotice({onRetry})` -> `{el, button, update(error)}`. `update` fills `el` from the failure
 * (`{code, message, status, details}`; the same wording as the chart's notice, ../chart/errors.js) and
 * keeps the nodes when the same failure repeats, so a focused "Try again" is not rebuilt under the
 * keyboard. A failure that passes by itself (server unreachable, busy, 5xx) gets the "Try again"
 * button; a bad setting needs an edit instead, so it gets none. `button` is the same node every time.
 */

import { h } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { describePreviewError, isTransient } from "../chart/errors.js";
import { sentence } from "../output-panel-kit.js";

/**
 * @param {{onRetry: () => void}} options
 * @returns {{el: HTMLElement, button: HTMLButtonElement, update: (error: object) => void}}
 */
export function createStaleNotice({ onRetry }) {
  const button = h("button", { type: "button", class: "btn btn-sm", on: { click: onRetry } }, "Try again");
  const el = h("div", { class: "notice out-notice", "data-kind": "warning", role: "alert" });
  let shown = "";
  return {
    el,
    button,
    update(error) {
      const key = `${error.code}|${error.message}`;
      if (key === shown && el.childNodes.length > 0) {
        return;
      }
      shown = key;
      el.replaceChildren(
        icon("alert", { size: 16 }),
        h(
          "div",
          { class: "notice-body" },
          h("strong", null, "The entries could not be updated. "),
          sentence(describePreviewError(error).message),
          " The rows below are the last ones that loaded.",
          isTransient(error) ? h("div", { class: "notice-actions" }, button) : null,
        ),
      );
    },
  };
}
