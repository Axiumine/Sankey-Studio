// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The two actions of a graph card that change the library and need a reload afterwards: Duplicate
 * and Delete (Move is asked by folders.js). Both take the card button that was pressed, mark it busy
 * and give the focus back to the same button (or to the summary line when its card is gone).
 *
 * `createRowActions({view, selection, reload})` returns `{copy(graph, button), remove(graph, button)}`;
 * `reload()` redraws the list after the server accepted the change (or said the graph was gone).
 */

import { reportError } from "../core/api.js";
import { confirmDialog } from "../core/dialog.js";
import { setBusy } from "../core/dom.js";
import { toast } from "../core/toast.js";
import { deleteGraph, duplicateGraph, graphHref } from "./data.js";
import { displayName } from "./names.js";

function makeCopy({ view, reload }) {
  return async (graph, button) => {
    const memo = view.rememberFocus(button);
    setBusy(button, true);
    try {
      const made = await duplicateGraph(graph.id);
      toast.success(`Created “${displayName(made.name)}”.`, {
        timeout: 12000,
        action: { label: "Open copy", onClick: () => location.assign(graphHref(made.id)) },
      });
      await reload();
    } catch (error) {
      if (error?.status === 404) {
        // deleted elsewhere: drop the ghost card instead of leaving a button that can only fail again
        toast.info("That graph was already gone, so it was not copied.");
        await reload();
      } else {
        reportError(error, toast);
      }
    } finally {
      setBusy(button, false);
      view.restoreFocus(memo);
    }
  };
}

function makeRemove({ view, selection, reload }) {
  return async (graph, button) => {
    const sure = await confirmDialog({
      title: `Delete “${graph.name}”?`,
      message: "The graph and its settings are removed for good. Files you exported earlier are not affected.",
      confirmLabel: "Delete graph",
      danger: true,
      confirmTestid: "delete-confirm",
      testid: "delete-dialog",
    });
    if (!sure) {
      return;
    }
    const memo = view.rememberFocus(button);
    setBusy(button, true);
    try {
      await deleteGraph(graph.id);
      toast.success(`Deleted “${graph.name}”.`);
    } catch (error) {
      if (error?.status === 404) {
        toast.info("That graph was already gone.");
      } else {
        reportError(error, toast);
      }
    }
    selection.remove(graph.id);
    await reload();
    setBusy(button, false);
    view.restoreFocus(memo);
  };
}

/**
 * @param {{view: {rememberFocus: Function, restoreFocus: Function}, selection: {remove: (id: string) => void}, reload: () => Promise<void>}} options
 * @returns {{copy: (graph: {id: string}, button: HTMLElement) => Promise<void>, remove: (graph: {id: string, name: string}, button: HTMLElement) => Promise<void>}}
 */
export function createRowActions({ view, selection, reload }) {
  return { copy: makeCopy({ view, reload }), remove: makeRemove({ view, selection, reload }) };
}
