// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The two steps of the new-graph wizard (editor/wizard/index.js owns the card around them).
 *
 * - `buildDetailsStep({store, api})` -> `{el, focus, validate, onEnter, dispose}`: the heading
 *   "Name your graph" and the same fields as the details dialog (editor-name, editor-description,
 *   editor-tags). `validate()` shows the "give the graph a name" message and returns false when
 *   the name is empty. `onEnter(fn)` calls `fn` when Enter is pressed in the name field.
 * - `buildSourceStep({store, api, toast, settings, switcher})` -> `{el, focus, tabs, parts,
 *   skippable, paintHint, dispose}`: the heading "Where does the data come from?", the five source
 *   tabs (the same tab set as the editor), and for text sources the checkbox "The first row is a
 *   header" (source-has-header, bound to the wizard store). `skippable()` is true while the Paste
 *   or Manual tab is selected (their empty source is a valid graph), `paintHint()` writes the
 *   sentence under the tabs for the tab that is selected. `onChange(id)` reports a tab change.
 * Both headings take focus when their step opens (tabindex -1).
 */

import { h } from "../../core/dom.js";
import { checkbox } from "../../core/form.js";
import { createTabSet } from "../source/tab-set.js";
import { createDetailsFields } from "../meta/fields.js";

const SKIPPABLE = ["paste", "manual"];
const HINTS = {
  paste: "Add some data, or choose Do it later.",
  manual: "Add a link, or choose Do it later.",
  text: "Choose a file from the sources folder to continue.",
  upload: "Upload a file to continue.",
  mongo: "Choose a connection and a collection to continue.",
};

/**
 * Step 1: name, description and tags.
 * @param {{store: object, api: object}} options
 */
export function buildDetailsStep({ store, api }) {
  const fields = createDetailsFields({ store, api });
  const heading = h("h2", { class: "ed-wizard-heading", tabindex: "-1" }, "Name your graph");
  const el = h("div", { "data-testid": "wizard-step-details", class: "stack" }, heading, fields.el);
  return {
    el,
    focus: () => fields.focusName(),
    focusHeading: () => heading.focus({ preventScroll: true }),
    validate() {
      const ok = fields.validate();
      if (!ok) {
        fields.focusName();
      }
      return ok;
    },
    onEnter(handler) {
      fields.name.control.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.isComposing) {
          event.preventDefault();
          handler();
        }
      });
    },
    dispose: () => fields.dispose(),
  };
}

function buildHeaderToggle(store) {
  const label = checkbox({ label: "The first row is a header", "data-testid": "source-has-header" });
  const input = label.querySelector("input");
  input.addEventListener("change", () => store.patch(["draft", "source", "has_header"], input.checked));
  const off = store.subscribe(
    (spec) => {
      label.hidden = spec.type !== "text";
      input.checked = spec.has_header !== false;
    },
    { select: (state) => state.draft.source, immediate: true },
  );
  return { label, off };
}

/**
 * Step 2: the data source.
 * @param {{store: object, api: object, toast: object, settings: object | null, switcher: object, onChange?: (id: string) => void}} options
 */
export function buildSourceStep({ store, api, toast, settings, switcher, onChange }) {
  const tabSet = createTabSet({ store, api, toast, settings, switcher, onChange });
  const header = buildHeaderToggle(store);
  const heading = h("h2", { class: "ed-wizard-heading", tabindex: "-1" }, "Where does the data come from?");
  const hint = h("p", { class: "hint", id: "wizard-source-hint" });
  const el = h(
    "div",
    { "data-testid": "wizard-step-source", class: "stack", hidden: true },
    heading,
    h("div", { class: "ed-source-tabs" }, tabSet.tabs.el),
    header.label,
    hint,
  );
  return {
    el,
    tabs: tabSet.tabs,
    parts: tabSet.parts,
    focusHeading: () => heading.focus({ preventScroll: true }),
    skippable: () => SKIPPABLE.includes(tabSet.tabs.selected()),
    paintHint() {
      hint.textContent = HINTS[tabSet.tabs.selected()] ?? "";
    },
    dispose() {
      header.off();
      tabSet.dispose();
    },
  };
}
