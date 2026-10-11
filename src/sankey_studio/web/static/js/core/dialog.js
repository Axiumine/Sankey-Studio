/**
 * Modal dialogs: `role="dialog"` + `aria-modal`, a focus trap, Esc to close, click on the
 * backdrop to close, the rest of the app made inert, body scroll locked, focus restored to the
 * element that opened it.
 *
 * - `openDialog({title, body, actions, wide, testid, initialFocus})` -> `{el, close(value), result}`.
 *   `body` is a Node or text; `actions` is `[{label, value, kind: "primary"|"danger"|"default",
 *   testid, onClick(close)}]`. `result` resolves to the clicked action's `value`, or `undefined`
 *   when closed with Esc/backdrop/`close()`. An `onClick` that does not call `close` keeps the
 *   dialog open (e.g. a form that failed validation).
 * - `confirmDialog({title, message, confirmLabel, cancelLabel, danger, testid, confirmTestid})`
 *   -> `Promise<boolean>`. A dangerous confirmation focuses Cancel first. Default test ids:
 *   `confirm-dialog`, `confirm-dialog-confirm`, `confirm-dialog-cancel` (pass `confirmTestid`
 *   such as "delete-confirm" to rename the confirm button).
 */

import { h, trapFocus, uid, focusable } from "./dom.js";

let open = 0;

function setInert(on) {
  const app = document.getElementById("app");
  if (app) {
    app.toggleAttribute("inert", on);
  }
  document.documentElement.classList.toggle("is-modal", on);
}

function actionButton(action, close) {
  const kind = action.kind ?? "default";
  const classes = ["btn", kind === "primary" ? "btn-primary" : null, kind === "danger" ? "btn-danger" : null];
  const click = () => (action.onClick ? action.onClick(close) : close(action.value));
  return h(
    "button",
    { type: "button", class: classes, "data-testid": action.testid ?? null, on: { click } },
    action.label,
  );
}

function pickFocus(dialog, options, buttons) {
  const preferred = options.initialFocus?.(dialog);
  const first = buttons.find((b) => b.dataset.initial === "true");
  (preferred ?? first ?? focusable(dialog)[0] ?? dialog).focus();
}

/**
 * Opens a modal dialog.
 * @param {{title: string, body?: Node|string, actions?: object[], wide?: boolean, testid?: string, initialFocus?: (dialog: HTMLElement) => HTMLElement | null}} options
 * @returns {{el: HTMLElement, close: (value?: unknown) => void, result: Promise<unknown>}}
 */
export function openDialog(options) {
  const titleId = uid("dialog-title");
  const bodyId = uid("dialog-body");
  let finish = null;
  const result = new Promise((resolve) => {
    finish = resolve;
  });
  let release = null;
  let backdrop = null;
  const close = (value) => {
    if (!backdrop) {
      return;
    }
    backdrop.remove();
    backdrop = null;
    open -= 1;
    if (open === 0) {
      setInert(false);
    }
    release();
    finish(value);
  };
  const buttons = (options.actions ?? []).map((action) => actionButton(action, close));
  buttons.forEach((button, index) => {
    if (options.actions[index].initial) {
      button.dataset.initial = "true";
    }
  });
  const dialog = h(
    "div",
    { class: ["dialog", options.wide ? "dialog-wide" : null], role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, "aria-describedby": options.body ? bodyId : null, tabindex: "-1", "data-testid": options.testid ?? null },
    h("div", { class: "dialog-header" }, h("h2", { class: "dialog-title", id: titleId }, options.title)),
    options.body ? h("div", { class: "dialog-body", id: bodyId }, options.body) : null,
    buttons.length ? h("div", { class: "dialog-actions" }, buttons) : null,
  );
  backdrop = h("div", { class: "dialog-backdrop", on: { mousedown: (event) => { if (event.target === backdrop) { close(undefined); } } } }, dialog);
  const opener = document.activeElement;
  document.body.append(backdrop);
  open += 1;
  setInert(true);
  release = trapFocus(dialog, { onEscape: () => close(undefined), returnFocus: opener });
  pickFocus(dialog, options, buttons);
  return { el: dialog, close, result };
}

/**
 * Asks a yes/no question. Resolves true only when the confirm button was pressed.
 * @param {{title: string, message: string, confirmLabel?: string, cancelLabel?: string, danger?: boolean, testid?: string, confirmTestid?: string}} options
 * @returns {Promise<boolean>}
 */
export async function confirmDialog(options) {
  const danger = options.danger === true;
  const dialog = openDialog({
    title: options.title,
    body: h("p", null, options.message),
    testid: options.testid ?? "confirm-dialog",
    actions: [
      { label: options.cancelLabel ?? "Cancel", value: false, testid: "confirm-dialog-cancel", initial: danger },
      {
        label: options.confirmLabel ?? "Confirm",
        value: true,
        kind: danger ? "danger" : "primary",
        testid: options.confirmTestid ?? "confirm-dialog-confirm",
        initial: !danger,
      },
    ],
  });
  return (await dialog.result) === true;
}
