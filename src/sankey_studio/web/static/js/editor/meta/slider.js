/**
 * A number field with a slider beside it, bound to one store path.
 *
 * The number input is the real control (typed values, keyboard, test id); the slider is a
 * pointer shortcut and is hidden from assistive technology and the tab order so nobody meets the
 * same setting twice. An empty number input removes the key, so the server default applies and
 * the placeholder shows that default.
 *
 * `createSlider({store, path, label, min, max, step, int, fallback, unit, hint, testid})` ->
 * `{field, unbind}`; `field` is a core/form.js field (`field.el` goes into the page).
 */

import { h } from "../../core/dom.js";
import { field as makeField, numberInput } from "../../core/form.js";
import { bindNumber } from "./bind.js";
import { getIn } from "./util.js";

/**
 * Builds the field and binds it.
 * @param {object} config
 * @returns {{field: ReturnType<typeof makeField>, unbind: () => void}}
 */
export function createSlider(config) {
  const { store, path, min, max, step = 1, fallback } = config;
  const control = numberInput({ min, max, step, placeholder: String(fallback), "data-testid": config.testid ?? null });
  const field = makeField({ label: config.unit ? `${config.label} (${config.unit})` : config.label, control, hint: config.hint });
  const range = h("input", { type: "range", class: "ed-range", min, max, step, tabindex: "-1", "aria-hidden": "true" });
  const row = h("div", { class: "ed-slider" }, range);
  control.replaceWith(row);
  row.append(control);
  range.addEventListener("input", () => {
    field.setError("");
    store.patch(path, Number(range.value));
  });
  const offNumber = bindNumber(store, field, path, { min, max, int: config.int === true });
  const offRange = store.subscribe(
    (value) => {
      range.value = String(typeof value === "number" ? value : fallback);
    },
    { select: (state) => getIn(state, path), immediate: true },
  );
  return {
    field,
    unbind() {
      offNumber();
      offRange();
    },
  };
}
