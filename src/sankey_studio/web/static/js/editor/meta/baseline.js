/**
 * The form of a graph that "is this still the saved graph?" compares (see dirty.js).
 *
 * The server answers with every field written out (`delimiter: null`, `top_links: null`,
 * `height: 560`, `hide_nodes: []`), while the editor removes a key when the person clears the
 * field, so the server's default applies. Both mean the same graph, so a comparison of the raw
 * objects calls a graph "changed" after an edit that was put back. `tidyDraft` writes both sides
 * the same way: a key is dropped when it holds nothing (null, empty text, empty list or object)
 * or the server's default for it.
 *
 * Two nulls mean something and stay: a Mongo source with `value_field: null` counts documents
 * instead of adding up a field, and an entry category of `category: null` clears the category.
 *
 * `DEFAULTS` mirrors the models (models/sources.py, transform.py, style.py); a test compares them.
 */

/** Server default of every key the editor can clear or put back, by section. */
export const DEFAULTS = Object.freeze({
  source: { origin: "inline", format: "auto", has_header: true, detect_category: true, encoding: "utf-8", mode: "find", source_field: "source", target_field: "target", value_field: "value", limit: 10000 },
  transform: { min_link_value: 0, on_cycle: "error", strict: false, rules_override: false },
  style: { orientation: "h", color_mode: "node", node_pad: 16, node_thickness: 18, link_opacity: 0.4, arrangement: "snap", value_format: ",.2~f", show_values_in_labels: false, font_size: 13, height: 560 },
  "style.donut": { basis: "all", max_slices: 6, hole: 0.58, show_percent: true, show_total: true, sort: "value" },
});

const KEEP_NULL = new Set(["source.value_field", "transform.entry_categories.[].category"]);

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

function isBlank(value) {
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  return value == null || value === "" || (isObject(value) && Object.keys(value).length === 0);
}

function keeps(path, key, value) {
  if (value === null) {
    return KEEP_NULL.has(`${path}.${key}`);
  }
  return !isBlank(value) && DEFAULTS[path]?.[key] !== value;
}

function tidy(value, path) {
  if (Array.isArray(value)) {
    return value.map((item) => tidy(item, `${path}.[]`));
  }
  if (!isObject(value)) {
    return value;
  }
  const entries = Object.entries(value).map(([key, raw]) => [key, tidy(raw, path === "" ? key : `${path}.${key}`)]);
  return Object.fromEntries(entries.filter(([key, next]) => keeps(path, key, next)));
}

let last = { draft: null, form: null };

/**
 * A draft (`{source, transform, style}`) in comparison form. The newest answer is remembered, so
 * asking again for the same draft object costs nothing.
 * @param {object} draft
 * @returns {object}
 */
export function tidyDraft(draft) {
  if (last.draft !== draft) {
    last = { draft, form: tidy(draft, "") };
  }
  return last.form;
}

/**
 * The part of the store that is saved with a graph, in comparison form.
 * @param {{draft: object, meta: {name: string, description: string, tags: string[]}}} state
 * @returns {{draft: object, meta: object}}
 */
export function savedForm(state) {
  const { name, description, tags } = state.meta;
  return { draft: tidyDraft(state.draft), meta: tidy({ name, description, tags }, "meta") };
}
