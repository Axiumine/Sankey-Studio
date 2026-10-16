// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The graph details fields: name, description and tags (what the library shows).
 *
 * `createDetailsFields({store, api, checkOnBlur, extras})` binds three controls to the store
 * (`meta.name`, `meta.description`, `meta.tags`; edits mark the draft dirty) and returns
 * `{el, name, description, tags, focusName(), setNameProblem(message), validate(), dispose()}`.
 * Tag suggestions come from GET /api/v1/tags (the tags already used by saved graphs). Server
 * validation errors for the three fields (`status.error`, from a failed preview or save) appear
 * under their field. `checkOnBlur` marks an empty name when the person leaves the field;
 * `extras` is a list of `(ctx) => ({el, dispose})` builders appended below the tags.
 * Test ids: editor-name, editor-description, editor-tags (the input inside the chip list).
 */

import { createScope, h } from "../../core/dom.js";
import { field, textArea, textInput } from "../../core/form.js";
import { bindText, cutNotice } from "./bind.js";
import { createChipInput } from "./chips.js";
import { createErrorSink } from "./errors.js";
import { DESCRIPTION_MAX, NAME_MAX, NAME_REQUIRED, TAGS_MAX, TAG_MAX } from "./limits.js";
import { uniqueSorted } from "./util.js";

async function loadTagSuggestions(api) {
  try {
    return uniqueSorted(await api.get("/tags", { quiet: true }), 200);
  } catch {
    return []; // suggestions are a convenience: typing a tag works without them
  }
}

function buildFields() {
  const name = field({
    label: "Name",
    control: textInput({ placeholder: "e.g. Household budget 2026", required: true, "data-testid": "editor-name", autocomplete: "off" }),
    hint: `Shown in your library. Up to ${NAME_MAX} characters.`,
  });
  const description = field({
    label: "Description (optional)",
    control: textArea({ rows: 2, placeholder: "What does this graph show?", "data-testid": "editor-description" }),
    hint: `Up to ${DESCRIPTION_MAX.toLocaleString("en-US")} characters.`,
  });
  return { name, description };
}

function buildTags({ store, suggestions }) {
  return createChipInput({
    label: "Tags (optional)",
    itemName: "tag",
    items: store.get().meta.tags,
    maxItems: TAGS_MAX,
    maxLength: TAG_MAX,
    separators: ",",
    placeholder: "Type a tag, press Enter",
    hint: `Up to ${TAGS_MAX} tags, ${TAG_MAX} characters each, separated by commas. Use them to filter the library.`,
    suggestions,
    testid: "editor-tags",
    onChange: (items) => store.patch(["meta", "tags"], items),
  });
}

function bindAll({ store, scope, fields }) {
  const { name, description, tags } = fields;
  scope.add(bindText(store, name.control, ["meta", "name"], { max: NAME_MAX, onWrite: cutNotice(name, NAME_MAX) }));
  scope.add(bindText(store, description.control, ["meta", "description"], { max: DESCRIPTION_MAX, onWrite: cutNotice(description, DESCRIPTION_MAX) }));
  scope.add(store.subscribe((items) => {
    if (items.join("\u0000") !== tags.getItems().join("\u0000")) {
      tags.setItems(items);
    }
  }, { select: (state) => state.meta.tags }));
  const sink = createErrorSink({
    owns: (path) => path[0] in fields,
    resolve: (path) => fields[path[0]],
    notice: () => undefined,
  });
  scope.add(store.subscribe((error) => sink.apply(error), { select: (state) => state.status.error, immediate: true }));
}

/**
 * Builds the fields.
 * @param {{store: object, api: object, checkOnBlur?: boolean, extras?: ((ctx: object) => {el: Node, dispose?: () => void})[]}} options
 * @returns {{el: HTMLElement, name: object, description: object, tags: object, focusName: () => void, setNameProblem: (message?: string) => void, validate: () => boolean, dispose: () => void}}
 */
export function createDetailsFields({ store, api, checkOnBlur = false, extras = [] }) {
  const scope = createScope();
  let suggestions = [];
  let disposed = false;
  const { name, description } = buildFields();
  const tags = buildTags({ store, suggestions: () => suggestions });
  const fields = { name, description, tags };
  bindAll({ store, scope, fields });
  const setNameProblem = (message = NAME_REQUIRED) => name.setError(message);
  const validate = () => {
    const empty = store.get().meta.name.trim() === "";
    if (empty) {
      setNameProblem();
    }
    return !empty;
  };
  if (checkOnBlur) {
    name.control.addEventListener("blur", () => {
      if (name.control.value.trim() === "") {
        setNameProblem();
      }
    });
  }
  const built = extras.map((build) => build({ store, api }));
  loadTagSuggestions(api).then((items) => {
    if (!disposed) {
      suggestions = items;
    }
  });
  const el = h("div", { class: "stack ed-details" }, name.el, description.el, tags.el, built.map((item) => item.el));
  return {
    el,
    name,
    description,
    tags,
    focusName: () => name.control.focus(),
    setNameProblem,
    validate,
    dispose() {
      disposed = true;
      scope.dispose();
      for (const item of built) {
        item.dispose?.();
      }
    },
  };
}
