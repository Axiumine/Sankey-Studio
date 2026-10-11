/**
 * Two-way bindings between form controls and the editor store.
 *
 * Each `bindX(store, control, path, options)` writes the control's value to `path` (an array of
 * keys such as ["draft", "style", "height"]) when the user edits it and writes the store's value
 * back into the control when the store changes from elsewhere. A control the user is typing in is
 * never overwritten with an equal value, so the caret never jumps. Every binding returns the
 * unsubscribe callback (collect them in a core/dom.js `createScope`).
 *
 * "Empty means default": text and number bindings can remove the key instead of storing an empty
 * value, so the server's default applies and the saved graph stays small.
 */

import { announce } from "../../core/a11y.js";
import { h } from "../../core/dom.js";
import { charCount, checkRange, clipText, getIn, parseNumber } from "./util.js";

function showValue(control, text) {
  if (control.value !== text) {
    control.value = text;
  }
}

/**
 * Text control <-> string at `path`. With `removeEmpty`, an empty control removes the key. With
 * `max`, text beyond that many characters (as the server counts them) is cut off and `onWrite`
 * hears about it, so a long paste is never shortened without a word.
 * @param {object} store
 * @param {HTMLInputElement | HTMLTextAreaElement} control
 * @param {(string|number)[]} path
 * @param {{removeEmpty?: boolean, max?: number, onWrite?: (text: string, cut: boolean) => void}} [options]
 * @returns {() => void}
 */
export function bindText(store, control, path, options = {}) {
  control.addEventListener("input", () => {
    const cut = options.max !== undefined && cutToMax(control, options.max);
    if (control.value === "" && options.removeEmpty) {
      store.remove(path);
    } else {
      store.patch(path, control.value);
    }
    options.onWrite?.(control.value, cut);
  });
  return store.subscribe((value) => showValue(control, value == null ? "" : String(value)), {
    select: (state) => getIn(state, path),
    immediate: true,
  });
}

/**
 * An `onWrite` for `bindText` with `max`: tells the person (on the field and to screen readers)
 * when text was cut at the limit, and clears the note on the next edit that fits.
 * @param {{setError: (message?: string) => void}} field
 * @param {number} max
 * @returns {(text: string, cut: boolean) => void}
 */
export function cutNotice(field, max) {
  return (_, cut) => {
    const message = cut ? `Only the first ${max.toLocaleString("en-US")} characters fit, so the rest was cut off.` : "";
    field.setError(message);
    if (message) {
      announce(message);
    }
  };
}

function cutToMax(control, max) {
  if (control.value.length <= max || charCount(control.value) <= max) {
    return false;
  }
  const caret = control.selectionStart ?? max;
  control.value = clipText(control.value, max);
  control.setSelectionRange(Math.min(caret, control.value.length), Math.min(caret, control.value.length));
  return true;
}

/**
 * Number control <-> number at `path`. Empty removes the key (the default applies); an invalid or
 * out-of-range entry is NOT written and is reported on the field instead.
 * @param {object} store
 * @param {{control: HTMLInputElement, setError: (message?: string) => void}} field  from core/form.js `field()`
 * @param {(string|number)[]} path
 * @param {{min?: number, max?: number, int?: boolean}} [range]
 * @returns {() => void}
 */
export function bindNumber(store, field, path, range = {}) {
  const control = field.control;
  control.addEventListener("input", () => {
    const text = control.value.trim();
    if (text === "") {
      field.setError("");
      store.remove(path);
      return;
    }
    const n = parseNumber(text);
    const problem = checkRange(n, range);
    field.setError(problem);
    if (!problem) {
      store.patch(path, n);
    }
  });
  return store.subscribe(
    (value) => {
      const typed = control.value.trim();
      const same = value != null && typed !== "" && parseNumber(typed) === value;
      if (!same && !(value == null && typed === "")) {
        showValue(control, value == null ? "" : String(value));
        field.setError("");
      }
    },
    { select: (state) => getIn(state, path), immediate: true },
  );
}

/**
 * Select <-> string at `path`; a missing value shows `fallback`.
 * @param {object} store
 * @param {HTMLSelectElement} select
 * @param {(string|number)[]} path
 * @param {{fallback?: string}} [options]
 * @returns {() => void}
 */
export function bindSelect(store, select, path, options = {}) {
  select.addEventListener("change", () => store.patch(path, select.value));
  return store.subscribe((value) => showValue(select, String(value ?? options.fallback ?? "")), {
    select: (state) => getIn(state, path),
    immediate: true,
  });
}

/**
 * Checkbox <-> boolean at `path`; a missing value shows `fallback` (default false).
 * @param {object} store
 * @param {HTMLInputElement} input
 * @param {(string|number)[]} path
 * @param {{fallback?: boolean, invert?: boolean}} [options]  `invert` shows the opposite of the stored value
 * @returns {() => void}
 */
export function bindCheck(store, input, path, options = {}) {
  const flip = options.invert === true;
  input.addEventListener("change", () => store.patch(path, flip ? !input.checked : input.checked));
  return store.subscribe(
    (value) => {
      const stored = typeof value === "boolean" ? value : options.fallback === true;
      input.checked = flip ? !stored : stored;
    },
    { select: (state) => getIn(state, path), immediate: true },
  );
}

/**
 * A group of toggle buttons where exactly one is pressed (orientation, find/aggregate).
 * `onChange(value)` fires on user choice; `set(value)` updates the display only.
 * @param {{label: string, options: {value: string, label: string, title?: string}[], value?: string, onChange?: (value: string) => void, testid?: string}} config
 * @returns {{el: HTMLElement, set: (value: string) => void, value: () => string, buttons: HTMLButtonElement[]}}
 */
export function createSegmented(config) {
  let current = config.value ?? config.options[0].value;
  const buttons = config.options.map((option) =>
    h(
      "button",
      { type: "button", "aria-pressed": "false", title: option.title ?? null, "data-value": option.value, on: { click: () => choose(option.value) } },
      option.label,
    ),
  );
  const el = h("div", { class: "segmented ed-segmented", role: "group", "aria-label": config.label, "data-testid": config.testid ?? null }, buttons);
  const paint = () => buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.value === current)));
  function choose(value) {
    if (value === current) {
      return;
    }
    current = value;
    paint();
    config.onChange?.(value);
  }
  paint();
  return {
    el,
    buttons,
    value: () => current,
    set(value) {
      current = value;
      paint();
    },
  };
}
