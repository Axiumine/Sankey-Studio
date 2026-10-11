/**
 * Form building blocks with the accessibility wiring done once: a visible `<label for>`, hint and
 * error text referenced by `aria-describedby`, `aria-invalid` on errors.
 *
 * Controls (all take the props of `h()` such as `name`, `value`, `placeholder`, `maxlength`,
 * `data-testid`, `on: {input, change}`; add `class` to extend the base class):
 * - `textInput(props)`, `numberInput(props)`, `passwordInput(props)`, `textArea(props)`
 *   (`code: true` for monospace), `selectInput({options, value, ...props})` where options are
 *   strings or `{value, label, disabled}`, `checkbox({label, checked, ...props})` -> `<label>`.
 * - `field({label, control, hint, error, class})` -> `{el, control, setError(msg), setHint(text)}`
 *   wraps one control; `setError("")` clears the error. Messages are text nodes.
 */

import { h, uid } from "./dom.js";
import { stripBidi } from "./text.js";

function withClass(base, props) {
  const extra = props?.class;
  return { ...props, class: [base, ...(Array.isArray(extra) ? extra : [extra])] };
}

/**
 * @param {object} [props]
 * @returns {HTMLInputElement}
 */
export function textInput(props) {
  return h("input", { type: "text", autocomplete: "off", spellcheck: "false", ...withClass("input", props) });
}

/**
 * @param {object} [props]
 * @returns {HTMLInputElement}
 */
export function numberInput(props) {
  return h("input", { type: "number", inputmode: "decimal", ...withClass("input", props) });
}

/**
 * A password input that never autofills (connection strings are secrets).
 * @param {object} [props]
 * @returns {HTMLInputElement}
 */
export function passwordInput(props) {
  return h("input", { type: "password", autocomplete: "new-password", ...withClass("input", props) });
}

/**
 * @param {{code?: boolean} & object} [props]
 * @returns {HTMLTextAreaElement}
 */
export function textArea(props = {}) {
  const { code, ...rest } = props;
  const element = h("textarea", { spellcheck: "false", ...withClass(code ? "textarea code" : "textarea", rest) });
  return element;
}

function optionNode(option) {
  const item = typeof option === "string" ? { value: option, label: option } : option;
  return h("option", { value: item.value, disabled: item.disabled === true }, item.label ?? item.value);
}

/**
 * @param {{options: (string | {value: string, label?: string, disabled?: boolean})[], value?: string} & object} props
 * @returns {HTMLSelectElement}
 */
export function selectInput(props) {
  const { options, ...rest } = props;
  return h("select", withClass("select", rest), options.map(optionNode));
}

/**
 * @param {{label: string, checked?: boolean} & object} props
 * @returns {HTMLLabelElement}
 */
export function checkbox(props) {
  const { label, ...rest } = props;
  const input = h("input", { type: "checkbox", ...rest });
  return h("label", { class: "check" }, input, h("span", null, label));
}

/**
 * Wraps a control with its label, hint and error line.
 * @param {{label: string, control: HTMLElement, hint?: string, error?: string, class?: string}} options
 * @returns {{el: HTMLElement, control: HTMLElement, setError: (message?: string) => void, setHint: (text?: string) => void}}
 */
export function field(options) {
  const control = options.control;
  const id = control.id || uid("field");
  control.id = id;
  const hint = h("p", { class: "hint", id: `${id}-hint`, hidden: !options.hint }, options.hint);
  const error = h("p", { class: "field-error", id: `${id}-error`, hidden: true });
  control.setAttribute("aria-describedby", `${hint.id} ${error.id}`);
  const el = h("div", { class: ["field", options.class] }, h("label", { for: id }, options.label), control, hint, error);
  const api = {
    el,
    control,
    setError(message) {
      error.textContent = stripBidi(message ?? "");
      error.hidden = !message;
      control.setAttribute("aria-invalid", message ? "true" : "false");
    },
    setHint(text) {
      hint.textContent = stripBidi(text ?? "");
      hint.hidden = !text;
    },
  };
  if (options.error) {
    api.setError(options.error);
  }
  return api;
}
