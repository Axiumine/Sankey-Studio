// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The "Graph details" dialog: name, description and tags in a modal opened from the gear next to
 * the title (and by the save bar when the name is missing).
 *
 * `openDetailsDialog({store, api, problem, extras})` shows the fields bound to the real store, so
 * every keystroke is already in the draft (and marks it dirty, like the panel it replaces did).
 * "Done" only validates the name and closes; Esc, the X or a click on the backdrop close without
 * validating, so an emptied name stays empty (the heading says so, and Save asks again).
 * `problem: "name"` opens the dialog with the "give the graph a name" message under the field.
 * Test ids: details-dialog, details-done, dialog-close (and editor-name, editor-description,
 * editor-tags inside).
 */

import { closePopovers } from "../../core/popover.js";
import { openDialog } from "../../core/dialog.js";
import { createDetailsFields } from "../meta/fields.js";

let shown = null;

/**
 * Opens the dialog (a second call while it is open only reports the problem in the open one).
 * @param {{store: object, api: object, problem?: "name" | null, extras?: Function[]}} options
 * @returns {{close: (value?: unknown) => void, result: Promise<unknown>}}
 */
export function openDetailsDialog({ store, api, problem = null, extras = [] }) {
  if (shown) {
    if (problem === "name") {
      shown.fields.setNameProblem();
    }
    shown.fields.focusName();
    return shown.handle;
  }
  closePopovers();
  const fields = createDetailsFields({ store, api, checkOnBlur: true, extras });
  const dialog = openDialog({
    title: "Graph details",
    testid: "details-dialog",
    closeButton: true,
    body: fields.el,
    initialFocus: () => fields.name.control,
    actions: [
      {
        label: "Done",
        kind: "primary",
        testid: "details-done",
        onClick: (close) => {
          if (fields.validate()) {
            close("done");
          } else {
            fields.focusName();
          }
        },
      },
    ],
  });
  if (problem === "name") {
    fields.setNameProblem();
  }
  const handle = { close: dialog.close, result: dialog.result };
  shown = { fields, handle };
  dialog.result.then(() => {
    shown = null;
    fields.dispose();
  });
  return handle;
}
