/**
 * F2: a click on a bar of the Sankey opens the "Add a flow" dialog for that node.
 *
 * - `prefillFor(node)` -> `{source?, target?, node, direction}`: what the dialog starts with. `node` is
 *   the row of the DRAWN `bundle.nodes` (never a name recovered from the figure: labels there are
 *   shortened and escaped). A node nothing leaves (`node_out === 0`, a sink) gets a flow that ENDS at
 *   it (`direction: "to"`, the target is the node); every other node gets a flow that STARTS at it
 *   (`direction: "from"`, the source is the node). The dialog lets the person flip it.
 * - `openNodeFlow({edits, node})` -> `Promise<boolean> | null`: opens the dialog (null when there is
 *   nothing to open it with). When the source names nothing to edit yet (no file or no collection
 *   chosen) a toast says so instead, like the disabled "Add entry" button does.
 */

import { toast } from "../../core/toast.js";
import { classify } from "../edits/classify.js";
import { openAddEntry } from "../entries/add-dialog.js";

/**
 * @param {{name: string, node_out?: number}} node  a row of `bundle.nodes`
 * @returns {{source?: string, target?: string, node: string, direction: "from" | "to"}}
 */
export function prefillFor(node) {
  if (node.node_out === 0) {
    return { target: node.name, node: node.name, direction: "to" };
  }
  return { source: node.name, node: node.name, direction: "from" };
}

/**
 * @param {{edits?: {store?: object} | null, node?: {name: string, node_out?: number} | null}} deps
 * @returns {Promise<boolean> | null}
 */
export function openNodeFlow({ edits, node }) {
  const store = edits?.store;
  if (!store || typeof node?.name !== "string") {
    return null;
  }
  const kind = classify(store.get().draft?.source);
  if (kind.where === "blocked") {
    toast.info(kind.message ?? "Choose the data source first.");
    return null;
  }
  return openAddEntry({ store, edits, prefill: prefillFor(node) });
}
