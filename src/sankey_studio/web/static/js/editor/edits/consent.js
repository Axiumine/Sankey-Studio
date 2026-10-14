/**
 * The consent dialog: "Change your data too?".
 *
 * Opened by the engine when an edit could be written into a file or a MongoDB collection and the
 * graph has no saved answer for that exact target. The answer is one of
 *   "accept"   `write-back-accept`   "Update the source": written now, remembered with the graph
 *   "decline"  `write-back-decline`  "Keep in this graph": this edit only; remembered for the page
 *                                    session and the same target (never persisted), initial focus
 *   "never"    `write-back-never`    "Keep in this graph, don't ask again": saved with the graph
 *   null       `write-back-cancel`   Cancel, Esc and the backdrop: nothing happens
 * Display strings (target, names, categories) are text nodes with bidi/control characters
 * stripped; the stored values stay raw. Queued edits of one target wait on ONE open dialog.
 */

import { openDialog } from "../../core/dialog.js";
import { h } from "../../core/dom.js";
import { stripBidi } from "../../core/text.js";
import { createChoices } from "./choices.js";

/** The page-session memory of plain "Keep in this graph" answers (see choices.js). */
export const choices = createChoices();

const ANSWERS = new Set(["accept", "decline", "never"]);

function clean(text) {
  return stripBidi(text ?? "");
}

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * One line that says what the edit is.
 * @param {object} edit
 * @returns {string}
 */
export function describeEdit(edit) {
  const pair = `${clean(edit.source)} to ${clean(edit.target)}`;
  if (edit.op === "add_entry") {
    const category = edit.category ? `, category ${clean(edit.category)}` : "";
    return `New entry: ${pair}, value ${edit.value}${category}.`;
  }
  if (edit.op === "set_category") {
    return edit.category ? `Entry ${pair}: category ${clean(edit.category)}.` : `Entry ${pair}: no category.`;
  }
  return "Node order.";
}

function reformats(source) {
  return source.format === "json" || /\.json$/i.test(source.path ?? "");
}

function fileLines(plan, source) {
  const lines = [
    h("p", null, "This change can be written into ", h("strong", null, clean(plan.target)), ", so the file and the chart agree."),
    h("p", null, "Other graphs that read this file change too. The file is replaced now; it is not part of Save and cannot be undone here."),
    h("p", null, "Row order in the file follows your drags."),
  ];
  if (reformats(source)) {
    lines.push(h("p", null, "The file will be re-formatted."));
  }
  return lines;
}

function mongoLines(plan, edit) {
  const effect = edit.op === "add_entry" ? "1 document will be added." : `${plural(plan.changed, "document", "documents")} will be changed.`;
  return [
    h("p", null, "This change can be written into the MongoDB collection ", h("strong", null, clean(plan.target)), `. ${effect}`),
    h("p", null, "Sankey Studio normally only reads from MongoDB. Your database user needs write permission. The change is not part of Save and cannot be undone here."),
  ];
}

/**
 * The dialog body.
 * @param {{plan: object, edit: object, source: object}} request
 * @returns {HTMLElement}
 */
export function consentBody({ plan, edit, source }) {
  const kind = plan.where === "mongo" ? "collection" : "file";
  return h(
    "div",
    { class: "stack stack-sm" },
    h("p", null, describeEdit(edit)),
    ...(plan.where === "mongo" ? mongoLines(plan, edit) : fileLines(plan, source)),
    h("p", { class: "hint" }, `Your choice is saved with this graph for this ${kind}. A different ${kind} asks again.`),
  );
}

function open(request) {
  return openDialog({
    title: "Change your data too?",
    body: consentBody(request),
    testid: "write-back-dialog",
    actions: [
      { label: "Cancel", value: "cancel", testid: "write-back-cancel" },
      { label: "Keep in this graph, don't ask again", value: "never", testid: "write-back-never" },
      { label: "Keep in this graph", value: "decline", testid: "write-back-decline", initial: true },
      { label: "Update the source", value: "accept", kind: "primary", testid: "write-back-accept" },
    ],
  });
}

/**
 * Asks (or answers from the page-session memory) whether the edit may change the data.
 * @param {object} plan  the `EditOutcome` of /edits/plan (`where` file|mongo, `target`, `target_key`)
 * @param {object} edit
 * @param {object} source  `draft.source`
 * @returns {Promise<"accept" | "decline" | "never" | null>} null = cancelled
 */
export function askConsent(plan, edit, source) {
  const key = plan.target_key;
  if (choices.remembered(key)) {
    return Promise.resolve("decline");
  }
  return choices.share(key, async () => {
    const answer = await open({ plan, edit, source }).result;
    const choice = ANSWERS.has(answer) ? answer : null;
    if (choice === "decline") {
      choices.remember(key);
    }
    return choice;
  });
}
