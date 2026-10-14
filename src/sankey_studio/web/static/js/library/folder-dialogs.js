/**
 * The three questions the collections ask: a name, a place, and "really delete?".
 *
 * `askName({title, initial, parentLabel, confirmLabel, submit})` and `askTarget({...})` keep their
 * dialog open while the request they start fails, so a taken name is fixed in place. `submit` does
 * the request (and whatever must follow it) and resolves to the value the dialog closes with; when
 * it throws an `ApiError` the sentence goes under the field. The promise resolves to that value, or
 * to `undefined` when the person cancelled (Cancel, Esc, the backdrop).
 *
 * `askTarget` shows the collections as a radio list in tree order ("Library" first, children
 * indented by `data-depth`). An option that cannot be chosen stays visible and disabled with the
 * reason next to it: where the thing already is, inside the collection that is being moved, or too
 * deep for the tree. Names are text nodes with control and direction characters removed.
 *
 * `confirmDeleteFolder(folder, where)` resolves true after the person confirms; it says how many
 * graphs and collections move up (a delete never removes a graph).
 *
 * Test ids: folder-dialog (name and delete share the prefix: folder-dialog, folder-delete-dialog),
 * folder-name-input, folder-name-error, folder-name-confirm, move-dialog, move-option
 * (data-folder-id, "root" for the top level), move-confirm, folder-delete-confirm.
 */

import { reportError } from "../core/api.js";
import { confirmDialog, openDialog } from "../core/dialog.js";
import { h, setBusy, uid } from "../core/dom.js";
import { formatCount } from "../core/format.js";
import { DEPTH_MAX, LABEL_MAX } from "./folders-data.js";
import { folderLabel } from "./names.js";

const SENTENCES = {
  folder_name_taken: "A collection with this name already exists in that place. Choose another name.",
  folder_rule: null, // the server's own sentence says which rule (depth, count, cycle)
};

/** The sentence under the field for a failed request. */
function describe(error) {
  const known = SENTENCES[error?.code];
  return known ?? reportError(error)?.friendly ?? "That did not work. Try again.";
}

async function attempt({ run, error, button, close }) {
  if (button.hasAttribute("aria-busy")) {
    return; // the request is still running: Enter pressed twice must not send it twice
  }
  error.hidden = true;
  setBusy(button, true);
  try {
    close(await run());
  } catch (failure) {
    error.textContent = describe(failure);
    error.hidden = false;
  } finally {
    setBusy(button, false);
  }
}

function errorLine(id) {
  return h("p", { class: "field-error", id, role: "alert", hidden: true, "data-testid": "folder-name-error" });
}

/**
 * Asks for a collection name.
 * @param {{title: string, initial?: string, parentLabel?: string | null, confirmLabel?: string, submit: (name: string) => Promise<unknown>}} options
 * @returns {Promise<unknown>}  what `submit` resolved to, or `undefined` when cancelled
 */
export function askName({ title, initial = "", parentLabel = null, confirmLabel = "Save", submit }) {
  const id = uid("folder-name");
  const error = errorLine(`${id}-error`);
  const input = h("input", { type: "text", class: "input", id, value: initial, maxlength: LABEL_MAX, autocomplete: "off", spellcheck: "false", "aria-describedby": error.id, "data-testid": "folder-name-input" });
  const body = h(
    "div",
    { class: "stack stack-sm" },
    parentLabel ? h("p", { class: "text-muted" }, `Inside ${parentLabel}`) : null,
    h("div", { class: "field" }, h("label", { for: id }, "Name"), input, error),
  );
  const run = () => {
    const name = input.value.trim();
    if (!name) {
      error.textContent = "Give the collection a name.";
      error.hidden = false;
      input.focus();
      return Promise.resolve();
    }
    return attempt({ run: () => submit(name), error, button: dialog.el.querySelector('[data-testid="folder-name-confirm"]'), close: dialog.close });
  };
  const dialog = openDialog({
    title,
    body,
    testid: "folder-dialog",
    initialFocus: () => input,
    actions: [{ label: "Cancel" }, { label: confirmLabel, kind: "primary", testid: "folder-name-confirm", onClick: run }],
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      run();
    }
  });
  input.select();
  return dialog.result;
}

/** The options of the radio list, in tree order: `{id, label, depth, reason}`; `reason` disables one. */
function targetOptions({ index, current, moving }) {
  const blocked = new Set(moving ? [moving.id, ...index.descendantsOf(moving.id).map((item) => item.id)] : []);
  const reasonFor = (id, depth) => {
    if (blocked.has(id)) {
      return "inside the collection being moved";
    }
    if (id === current) {
      return "already here";
    }
    return moving && depth + index.heightOf(moving.id) > DEPTH_MAX ? `too deep (at most ${DEPTH_MAX} levels)` : null;
  };
  const walk = (parent, depth) => index.childrenOf(parent).flatMap((folder) => [
    { id: folder.id, label: folderLabel(folder.name), depth, reason: reasonFor(folder.id, depth) },
    ...walk(folder.id, depth + 1),
  ]);
  const top = { id: null, label: "Library (top level)", depth: 0, reason: current === null ? "already here" : null };
  return [top, ...walk(null, 1)];
}

function optionRow(option, name, onPick) {
  const input = h("input", { type: "radio", name, disabled: option.reason !== null, on: { change: () => onPick(option.id) } });
  return h(
    "label",
    { class: "move-option", "data-depth": option.depth, title: option.reason ? `Not possible: ${option.reason}` : null, "data-testid": "move-option", "data-folder-id": option.id ?? "root" },
    input,
    h("span", { class: "move-name" }, option.label),
    option.reason ? h("span", { class: "move-reason text-muted" }, `(${option.reason})`) : null,
  );
}

/**
 * Asks where something should go.
 * @param {{title: string, index: object, current?: string | null, moving?: {id: string} | null, submit: (target: string | null) => Promise<unknown>}} options
 *   `current`: the collection it sits in now (`null` = the top level; omit when several graphs from different places move);
 *   `moving`: the collection being moved, which cannot go into itself, below itself or too deep
 * @returns {Promise<unknown>}  what `submit` resolved to, or `undefined` when cancelled
 */
export function askTarget({ title, index, current, moving = null, submit }) {
  const name = uid("move-target");
  const error = errorLine(`${name}-error`);
  let chosen;
  const rows = targetOptions({ index, current, moving }).map((option) => optionRow(option, name, (id) => {
    chosen = { id };
    dialog.el.querySelector('[data-testid="move-confirm"]').disabled = false;
  }));
  const list = h("div", { class: "move-tree", role: "radiogroup", "aria-label": "Move to", "aria-describedby": error.id }, rows);
  const run = () => attempt({ run: () => submit(chosen.id), error, button: dialog.el.querySelector('[data-testid="move-confirm"]'), close: dialog.close });
  const dialog = openDialog({
    title,
    body: h("div", { class: "stack stack-sm" }, list, error),
    testid: "move-dialog",
    actions: [{ label: "Cancel" }, { label: "Move here", kind: "primary", testid: "move-confirm", onClick: run }],
  });
  dialog.el.querySelector('[data-testid="move-confirm"]').disabled = true;
  return dialog.result;
}

/**
 * Asks before a collection is deleted.
 * @param {{name: string, graph_count: number, child_count: number}} folder
 * @param {string} where  what the contents move up to ("Library" or a collection name)
 * @returns {Promise<boolean>}
 */
export function confirmDeleteFolder(folder, where) {
  const moved = [];
  if (folder.graph_count > 0) {
    moved.push(formatCount(folder.graph_count, "graph"));
  }
  if (folder.child_count > 0) {
    moved.push(formatCount(folder.child_count, "collection"));
  }
  const message = moved.length > 0
    ? `${moved.join(" and ")} will move up to ${where}. No graph is deleted.`
    : "The collection is empty. No graph is deleted.";
  return confirmDialog({
    title: `Delete the collection “${folderLabel(folder.name)}”?`,
    message,
    confirmLabel: "Delete collection",
    danger: true,
    testid: "folder-delete-dialog",
    confirmTestid: "folder-delete-confirm",
  });
}
