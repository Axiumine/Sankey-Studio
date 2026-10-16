// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * "Edits to the data": the status of the write-back choice of a file or MongoDB source.
 *
 * Shown only while the source names a target (a chosen file, a chosen collection). It is a STATUS
 * line plus an "Ask me again" button, never a way to grant consent: the key that binds a choice to
 * a target is built by the server and only the consent dialog stores it (see ../edits/). The line
 * reads "ask me each time", "written to the source" or "kept in this graph"; "Ask me again" sets
 * `source.write_back` to null and forgets the answers remembered for this page. When the person
 * picks another file or collection the line goes back to "ask me each time" (the server asks
 * again for a target it has no answer for), until a new answer is stored.
 * Test id: `source-write-back` (the wrapper; the button is found by its name).
 */

import { announce } from "../../core/a11y.js";
import { h, uid } from "../../core/dom.js";
import { forgetChoices } from "../edits/index.js";

const MODES = {
  source: "written to the source",
  graph: "kept in this graph",
};
const FACTS =
  "When you agree, a category or an entry you change is written into the file or collection at once. That is not part of Save, other graphs that read the same data change too, and JSON text is re-formatted. In files the row order follows your drags.";

function hasTarget(source) {
  if (source?.type === "mongo") {
    return Boolean(source.connection && source.collection);
  }
  return source?.type === "text" && source.origin === "file" && Boolean(source.path);
}

function signature(source) {
  return [source?.type, source?.path, source?.connection, source?.database, source?.collection].join("\u0000");
}

/**
 * @param {{store: object}} options
 * @returns {{el: HTMLElement, dispose: () => void}}
 */
export function createWriteBackField({ store }) {
  const id = uid("write-back");
  const status = h("span", { class: "nums", id: `${id}-status` });
  const reset = h("button", { type: "button", class: "btn btn-sm", "aria-describedby": `${id}-facts`, on: { click: () => askAgain() } }, "Ask me again");
  const facts = h("p", { class: "hint", id: `${id}-facts` }, FACTS);
  const el = h("div", { class: "stack stack-sm", hidden: true, "data-testid": "source-write-back" }, h("div", { class: "cluster" }, h("span", null, "Edits to the data: "), status, reset), facts);
  const start = store.get().draft.source;
  let bound = { signature: signature(start), pref: start.write_back ?? null }; // where the stored answer was given

  function askAgain() {
    store.patch(["draft", "source", "write_back"], null);
    forgetChoices();
    announce("Edits to the data will ask first");
  }

  function paint(source) {
    el.hidden = !hasTarget(source);
    const pref = source.write_back ?? null;
    if (pref !== bound.pref) {
      bound = { signature: signature(source), pref }; // a new answer (the dialog, or "Ask me again")
    }
    const mode = signature(source) === bound.signature ? pref?.mode : undefined;
    status.textContent = MODES[mode] ?? "ask me each time";
    reset.disabled = !MODES[mode];
  }

  paint(start);
  const off = store.subscribe(paint, { select: (state) => state.draft.source });
  return { el, dispose: off };
}
