/**
 * Panel "meta": the graph's name, description and tags (what the library shows).
 *
 * Writes `meta.name`, `meta.description`, `meta.tags` of the store (these mark the draft dirty).
 * Tag suggestions come from GET /api/v1/tags (the tags already used by saved graphs). Server
 * validation errors for `name`, `description` and `tags` appear under their field.
 * Test ids: editor-name, editor-description, editor-tags (the input inside the chip list).
 */

import { createScope, h } from "../../core/dom.js";
import { field, textArea, textInput } from "../../core/form.js";
import { registerPanel } from "../panels.js";
import { bindText, cutNotice } from "./bind.js";
import { createChipInput } from "./chips.js";
import { createErrorSink } from "./errors.js";
import { uniqueSorted } from "./util.js";

const NAME_MAX = 200;
const DESCRIPTION_MAX = 2000;
const TAG_MAX = 40;
const TAGS_MAX = 20;
const SAVE_BAR_PROBLEM = '[data-panel="savebar"] [data-testid="save-status"][data-state="error"]';

async function loadTagSuggestions(api) {
  try {
    return uniqueSorted(await api.get("/tags", { quiet: true }), 200);
  } catch {
    return []; // suggestions are a convenience: typing a tag works without them
  }
}

/**
 * Calls `onChange` whenever a `data-state` attribute (the save bar's status line) changes under
 * `root`. Only attributes are watched: `onChange` writes text, and watching that would loop.
 */
function watchStatus(root, onChange) {
  if (!root) {
    return () => undefined;
  }
  const observer = new MutationObserver(onChange);
  observer.observe(root, { subtree: true, attributes: true, attributeFilter: ["data-state"] });
  return () => observer.disconnect();
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

function mountMeta(container, ctx) {
  const { store } = ctx;
  const scope = createScope();
  const { name, description } = buildFields();
  let suggestions = [];
  const tags = createChipInput({
    label: "Tags (optional)",
    itemName: "tag",
    items: store.get().meta.tags,
    maxItems: TAGS_MAX,
    maxLength: TAG_MAX,
    separators: ",",
    placeholder: "Type a tag, press Enter",
    hint: `Up to ${TAGS_MAX} tags, ${TAG_MAX} characters each. Use them to filter the library.`,
    suggestions: () => suggestions,
    testid: "editor-tags",
    onChange: (items) => store.patch(["meta", "tags"], items),
  });
  scope.add(bindText(store, name.control, ["meta", "name"], { max: NAME_MAX, onWrite: cutNotice(name, NAME_MAX) }));
  scope.add(bindText(store, description.control, ["meta", "description"], { max: DESCRIPTION_MAX, onWrite: cutNotice(description, DESCRIPTION_MAX) }));
  scope.add(store.subscribe((items) => {
    if (items.join("\u0000") !== tags.getItems().join("\u0000")) {
      tags.setItems(items);
    }
  }, { select: (state) => state.meta.tags }));
  const checkName = (afterSave) => {
    const problem = name.control.value.trim() === "" && (!afterSave || container.closest(".ed-root")?.querySelector(SAVE_BAR_PROBLEM));
    if (problem) {
      name.setError("Give the graph a name so you can find it later.");
    }
  };
  name.control.addEventListener("blur", () => checkName(false));
  // Save moves focus here when the name is empty: mark the field itself, not only the save bar
  name.control.addEventListener("focus", () => checkName(true));
  // ... and when focus is already here (Ctrl+S while typing in the field) no focus event comes, so
  // watch the save bar's status instead
  scope.add(watchStatus(container.closest(".ed-root"), () => checkName(true)));
  const fields = { name, description, tags };
  const sink = createErrorSink({
    owns: (path) => path[0] in fields,
    resolve: (path) => fields[path[0]],
    notice: () => undefined,
  });
  scope.add(store.subscribe((error) => sink.apply(error), { select: (state) => state.status.error, immediate: true }));
  loadTagSuggestions(ctx.api).then((items) => {
    suggestions = items;
  });
  container.replaceChildren(h("div", { class: "card ed-card ed-meta" }, h("div", { class: "card-body stack" }, name.el, description.el, tags.el)));
  return () => scope.dispose();
}

registerPanel("meta", mountMeta, { order: 10 });
