/**
 * The form of the "Add a flow" dialog and the rules it checks before the server is asked.
 *
 * Pure rules (no DOM, node-testable):
 * - `checkEntry(values, knownCategories)` -> `{ok: true, entry}` or `{ok: false, field, message}`.
 *   Names are trimmed, 1-200 characters, without control characters; source and target differ; the
 *   value is a finite number above 0; the category is optional, not reserved, and takes the spelling
 *   already in use. `entry` is `{source, target, value, category}` (category `null` when empty).
 * - `nodeNameSet(bundle)` / `newNodeHint(name, nodes)`: the non-blocking "New node" hint. It stays
 *   silent while the preview lists no node at all (an empty graph or a preview still loading), because
 *   then every name would be "new".
 *
 * `titleFor(prefill)`: "Add a flow", or for a clicked node "Add a flow from X" / "Add a flow into X".
 *
 * `createAddForm({bundle, categories, prefill, onDirection})` builds the fields: `{el, inputs, values(),
 * fail(problem), clearError(), firstEmpty(), refresh(bundle)}`. `prefill` is `{source?,
 * target?, node?, direction?}`; the first empty field takes the focus.
 * F2 (a click on a node of the chart) passes `node` (its name) and `direction` ("from": the new flow
 * starts at the node, "to": it ends there). Then the form shows the fieldset `add-entry-direction` with
 * two radios; choosing the other one moves the node to the other end (source and target swap, so
 * what was typed for the other end follows; the focus stays on the radio) and calls `onDirection(direction)`.
 * Test ids: `add-entry-source`, `add-entry-target`, `add-entry-value`, `add-entry-category`,
 * `add-entry-error` (the one `role="alert"` line for local and server problems),
 * `add-entry-direction`, `add-entry-from-node`, `add-entry-to-node`.
 */

import { h, uid } from "../../core/dom.js";
import { field, textInput } from "../../core/form.js";
import { stripBidi } from "../../core/text.js";
import { parseNumber } from "../meta/util.js";
import { canonicalCategory, checkCategory } from "./edits.js";

/** The server's limit of a node name (`NAME_MAX`). */
export const NODE_NAME_MAX = 200;
/** At most this many names are offered as suggestions. */
export const SUGGESTION_MAX = 1000;

const CONTROL = /[\u0000-\u001f\u007f-\u009f]/;
const FIELDS = ["source", "target", "value", "category"];
const ROLE = { source: "source", target: "target" };

/**
 * Checks one node name.
 * @param {unknown} text
 * @param {"source" | "target"} role
 * @returns {{ok: true, value: string} | {ok: false, message: string}}
 */
export function checkNodeName(text, role) {
  const value = String(text ?? "").trim();
  if (value === "") {
    return { ok: false, message: role === "source" ? "Enter the source: where the flow starts." : "Enter the target: where the flow ends." };
  }
  if (value.length > NODE_NAME_MAX) {
    return { ok: false, message: `Names can have at most ${NODE_NAME_MAX} characters.` };
  }
  if (CONTROL.test(value) || (value.isWellFormed && !value.isWellFormed())) {
    return { ok: false, message: `The ${role} name contains characters that cannot be used.` };
  }
  return { ok: true, value };
}

/**
 * The checked entry for the typed values, or the first problem (in reading order).
 * @param {{source: string, target: string, value: string, category: string}} values
 * @param {string[]} [known]  the category spellings in use (`bundle.category_names`)
 * @returns {{ok: true, entry: {source: string, target: string, value: number, category: string | null}} | {ok: false, field: string, message: string}}
 */
export function checkEntry(values, known = []) {
  const ends = {};
  for (const key of Object.keys(ROLE)) {
    const checked = checkNodeName(values[key], ROLE[key]);
    if (!checked.ok) {
      return { ok: false, field: key, message: checked.message };
    }
    ends[key] = checked.value;
  }
  if (ends.source === ends.target) {
    return { ok: false, field: "target", message: "The source and the target must be different nodes." };
  }
  const value = parseNumber(values.value ?? "");
  if (!(Number.isFinite(value) && value > 0)) {
    return { ok: false, field: "value", message: "Enter a value above 0, for example 1200 or 12.5." };
  }
  const category = checkCategory(values.category);
  if (!category.ok) {
    return { ok: false, field: "category", message: category.message };
  }
  return { ok: true, entry: { ...ends, value, category: category.value === null ? null : canonicalCategory(category.value, known) } };
}

/**
 * The node names of a preview bundle.
 * @param {{nodes?: {name: string}[]} | null | undefined} bundle
 * @returns {Set<string>}
 */
export function nodeNameSet(bundle) {
  return new Set((bundle?.nodes ?? []).map((node) => node.name));
}

/**
 * "New node: X will be created." for a typed name the graph does not have, else "".
 * @param {string} name  as typed
 * @param {Set<string>} nodes  from `nodeNameSet`
 * @returns {string}
 */
export function newNodeHint(name, nodes) {
  const value = String(name ?? "").trim();
  if (nodes.size === 0 || value === "" || nodes.has(value)) {
    return "";
  }
  return `New node: ${stripBidi(value)} will be created.`;
}

function options(names) {
  return names.slice(0, SUGGESTION_MAX).map((name) => h("option", { value: name }));
}

/** One labelled input with its status line (the "New node" hint) for source and target. */
function hinted(label, control) {
  const statusId = uid("add-hint");
  const status = h("p", { class: "hint out-add-hint", id: statusId, role: "status" });
  const wrapper = field({ label, control });
  control.setAttribute("aria-describedby", `${control.getAttribute("aria-describedby")} ${statusId}`);
  wrapper.el.append(status);
  return { el: wrapper.el, status };
}

function createInputs(prefill, lists) {
  const ends = { maxlength: NODE_NAME_MAX, list: lists.nodes, placeholder: "e.g. Budget" };
  return {
    source: textInput({ ...ends, value: prefill.source ?? "", "data-testid": "add-entry-source" }),
    target: textInput({ ...ends, value: prefill.target ?? "", "data-testid": "add-entry-target" }),
    value: textInput({ inputmode: "decimal", maxlength: 40, placeholder: "e.g. 1200", "data-testid": "add-entry-value" }),
    category: textInput({ list: lists.categories, placeholder: "None", "data-testid": "add-entry-category" }),
  };
}

const TITLE = "Add a flow";
const TITLE_NAME_MAX = 60;

/** The dialog title: "Add a flow", or for a clicked node "Add a flow from X" / "Add a flow into X". */
export function titleFor(prefill) {
  if (typeof prefill?.node !== "string") {
    return TITLE;
  }
  const name = stripBidi(prefill.node);
  const shown = name.length > TITLE_NAME_MAX ? `${name.slice(0, TITLE_NAME_MAX)}...` : name;
  return `${TITLE} ${prefill.direction === "to" ? "into" : "from"} ${shown}`;
}

/** One radio of the direction choice: `{input, el}`. */
function directionRadio({ name, value, label, checked, testid }) {
  const input = h("input", { type: "radio", name, value, class: "ed-kind-input", checked, "data-testid": testid });
  return { input, el: h("label", { class: "ed-kind" }, input, h("span", { class: "ed-kind-body" }, h("span", { class: "ed-kind-label" }, label))) };
}

/** F2: "The new flow starts at X" / "ends at X". `onPick(direction)` runs when the person chooses. */
function createDirection({ node, direction, onPick }) {
  const name = uid("add-direction");
  const shown = stripBidi(node);
  const radios = {
    from: directionRadio({ name, value: "from", label: `The new flow starts at ${shown}`, checked: direction === "from", testid: "add-entry-from-node" }),
    to: directionRadio({ name, value: "to", label: `The new flow ends at ${shown}`, checked: direction === "to", testid: "add-entry-to-node" }),
  };
  for (const [value, radio] of Object.entries(radios)) {
    radio.input.addEventListener("change", () => radio.input.checked && onPick(value));
  }
  const el = h(
    "fieldset",
    { class: "ed-kinds", "data-testid": "add-entry-direction" },
    h("legend", { class: "ed-kinds-legend" }, "Direction"),
    radios.from.el,
    radios.to.el,
  );
  return { el };
}

function createLayout({ inputs, lists, suggestions, direction }) {
  const source = hinted("Source", inputs.source);
  const target = hinted("Target", inputs.target);
  const error = h("p", { class: "field-error", role: "alert", hidden: true, "data-testid": "add-entry-error" });
  const nodeOptions = h("datalist", { id: lists.nodes }, options(suggestions.nodes));
  const el = h(
    "form",
    { class: "stack stack-sm out-add-form", novalidate: true, on: { submit: (event) => event.preventDefault() } },
    h("p", { class: "hint" }, "Source and target can be existing nodes or new ones."),
    direction?.el,
    source.el,
    target.el,
    field({ label: "Value", control: inputs.value }).el,
    field({ label: "Category (optional)", control: inputs.category }).el,
    error,
    nodeOptions,
    h("datalist", { id: lists.categories }, options(suggestions.categories)),
  );
  return { el, source, target, error, nodeOptions };
}

function showProblem({ inputs, error, clearError }, { field: key, message }) {
  clearError();
  error.textContent = stripBidi(message);
  error.hidden = false;
  const input = inputs[key];
  if (input) {
    input.setAttribute("aria-invalid", "true");
    input.focus();
  }
}

/**
 * @param {{bundle: object | null, categories: string[], prefill?: {source?: string, target?: string, node?: string, direction?: "from" | "to"}, onDirection?: (direction: "from" | "to") => void}} options
 * @returns {object}
 */
export function createAddForm({ bundle, categories, prefill = {}, onDirection }) {
  const lists = { nodes: uid("add-nodes"), categories: uid("add-categories") };
  const inputs = createInputs(prefill, lists);
  let nodes = nodeNameSet(bundle);
  const pick = (value) => {
    [inputs.source.value, inputs.target.value] = [inputs.target.value, inputs.source.value]; // the node changes ends
    refreshHints();
    clearError();
    onDirection?.(value);
  };
  const direction = typeof prefill.node === "string" ? createDirection({ node: prefill.node, direction: prefill.direction === "to" ? "to" : "from", onPick: pick }) : null;
  const { el, source, target, error, nodeOptions } = createLayout({ inputs, lists, suggestions: { nodes: [...nodes], categories }, direction });
  const firstEmptyKey = () => ["source", "target", "value"].find((key) => inputs[key].value.trim() === "") ?? "source";
  const refreshHints = () => {
    source.status.textContent = newNodeHint(inputs.source.value, nodes);
    target.status.textContent = newNodeHint(inputs.target.value, nodes);
  };
  const clearError = () => {
    error.hidden = true;
    error.textContent = "";
    Object.values(inputs).forEach((input) => input.removeAttribute("aria-invalid"));
  };
  Object.values(inputs).forEach((input) =>
    input.addEventListener("input", () => {
      refreshHints();
      clearError();
    }),
  );
  refreshHints();
  return {
    el,
    inputs,
    values: () => Object.fromEntries(FIELDS.map((key) => [key, inputs[key].value])),
    clearError,
    /** Shows one problem: the message in the alert line and, for a field, `aria-invalid` and the focus. */
    fail: (problem) => showProblem({ inputs, error, clearError }, problem),
    /** The first empty required field (the source when all are filled). */
    firstEmpty() {
      return inputs[firstEmptyKey()];
    },
    /** New preview: refresh the suggestions and the hints. */
    refresh(next) {
      nodes = nodeNameSet(next);
      nodeOptions.replaceChildren(...options([...nodes]));
      refreshHints();
    },
  };
}
