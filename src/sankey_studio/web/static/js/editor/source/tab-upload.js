// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Tab "Upload": add files to the sources folder of the server and manage them.
 *
 * A picked or dropped file is checked in the browser (extension and size against the server's
 * `max_upload_mb`), sent as multipart FormData through the one fetch wrapper, and then selected
 * as the graph's source. A name that already exists asks before it replaces the file (the server
 * answers 409). Files can be previewed, chosen and deleted from the list. Uploading and deleting
 * are write actions: they are disabled when the server is read-only.
 *
 * The browser's own file control is not drawn (its words follow the language of the operating
 * system): the real `<input type=file>` stays in the page, visually hidden but reachable with Tab,
 * and a styled label next to it opens the picker. Enter and Space on the focused input open it
 * too, and the label of the input is the English "Choose a file". Next to the button a short
 * line names the file picked last.
 * Test id: source-upload-input.
 */

import { announce } from "../../core/a11y.js";
import { canWrite, lockWriteControls } from "../../core/boot.js";
import { confirmDialog } from "../../core/dialog.js";
import { h } from "../../core/dom.js";
import { formatBytes, formatDate } from "../../core/format.js";
import { icon } from "../../core/icons.js";
import { stripBidi } from "../../core/text.js";
import { labelText } from "../meta/util.js";

const PATH = ["draft", "source", "path"];
const ALLOWED = [".csv", ".tsv", ".txt", ".json", ".ndjson", ".sankey"];
const DEFAULT_MAX_MB = 10;
const NO_FILE = "No file chosen";

function problemWith(file, maxMb) {
  const name = file.name.toLowerCase();
  if (!ALLOWED.some((ext) => name.endsWith(ext))) {
    return `${labelText(file.name)} is not a supported file. Use ${ALLOWED.join(", ")}.`;
  }
  if (file.size > maxMb * 1024 * 1024) {
    return `${labelText(file.name)} is ${formatBytes(file.size)}, more than the ${maxMb} MB limit. The limit can be raised in Settings.`;
  }
  return "";
}

class UploadTab {
  constructor({ store, files, settings, toast }) {
    this.store = store;
    this.files = files;
    this.toast = toast;
    this.maxMb = settings?.max_upload_mb ?? DEFAULT_MAX_MB;
    this.writable = canWrite();
    this.input = h("input", {
      type: "file",
      id: "source-upload",
      class: "visually-hidden ed-file-input",
      accept: ALLOWED.join(","),
      "aria-describedby": "source-upload-name source-upload-hint",
      disabled: !this.writable,
      "data-writes": "",
      "data-testid": "source-upload-input",
      on: { change: () => this.pick(this.input.files?.[0]) },
    });
    this.status = h("p", { class: "ed-upload-status", role: "status" });
    this.list = h("div", { class: "ed-files" });
    this.previewBox = h("div", { class: "ed-file-preview", hidden: true });
    this.zone = this.buildZone();
    this.el = h("div", { class: "stack" }, this.zone, this.status, this.list, this.previewBox);
    this.offs = [files.subscribe(() => this.paint()), store.subscribe(() => this.paint(), { select: (state) => state.draft.source.path }), this.guardStrayDrops()];
    this.paint();
    if (files.state.status === "idle") {
      files.refresh();
    }
  }

  buildZone() {
    const hint = this.writable ? `csv, tsv, txt, json, ndjson or sankey, up to ${this.maxMb} MB.` : "Uploading is turned off on this server (read-only).";
    this.name = h("span", { class: "ed-file-name", id: "source-upload-name" }, NO_FILE);
    const choose = h("div", { class: "ed-dropzone-pick" }, this.input, h("label", { for: "source-upload", class: "btn btn-sm" }, "Choose a file"), this.name);
    const zone = h(
      "div",
      { class: "ed-dropzone", "data-state": "idle" },
      h("span", { class: "ed-dropzone-icon" }, icon("upload", { size: 20 })),
      h("div", { class: "ed-dropzone-text" }, h("span", { class: "ed-dropzone-title" }, this.writable ? "Drop a file here, or" : "Uploads are turned off"), choose, h("span", { class: "hint", id: "source-upload-hint" }, hint)),
    );
    for (const type of ["dragenter", "dragover"]) {
      zone.addEventListener(type, (event) => {
        event.preventDefault();
        zone.dataset.state = this.writable ? "over" : "idle";
      });
    }
    zone.addEventListener("dragleave", () => {
      zone.dataset.state = "idle";
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.dataset.state = "idle";
      if (this.writable) {
        this.pick(event.dataTransfer?.files?.[0]);
      }
    });
    return zone;
  }

  /** A file dropped outside the drop zone would make the browser open it and leave the editor. */
  guardStrayDrops() {
    const stop = (event) => {
      if (event.dataTransfer?.types?.includes("Files") && !this.zone.contains(event.target)) {
        event.preventDefault();
      }
    };
    document.addEventListener("dragover", stop);
    document.addEventListener("drop", stop);
    return () => {
      document.removeEventListener("dragover", stop);
      document.removeEventListener("drop", stop);
    };
  }

  say(text, kind = "info") {
    this.status.replaceChildren(...(kind === "busy" ? [h("span", { class: "spinner", "aria-hidden": "true" }), " "] : []), stripBidi(text));
    this.status.dataset.kind = kind;
    if (text) {
      announce(text, { assertive: kind === "error" });
    }
  }

  async pick(file) {
    if (!file) {
      return;
    }
    const problem = problemWith(file, this.maxMb);
    if (problem) {
      this.say(problem, "error");
    } else {
      this.showName(file.name);
      await this.upload(file);
    }
    this.input.value = "";
  }

  /** The line next to the button: the file picked last (bidi controls removed, long names cut). */
  showName(name) {
    this.name.textContent = labelText(name, 80);
    this.name.title = labelText(name, 255);
  }

  /** Asks before replacing a file of the same name (names compare ignoring case), then sends. */
  async upload(file) {
    if (this.files.state.status !== "ready") {
      await this.files.refresh();
    }
    const taken = this.files.state.files.some((item) => item.name.toLowerCase() === file.name.toLowerCase());
    if (!taken) {
      await this.send(file, false);
    } else if (await this.askReplace(file)) {
      await this.send(file, true);
    }
  }

  askReplace(file) {
    return confirmDialog({
      title: "Replace the existing file?",
      message: `A file named ${labelText(file.name)} is already in the sources folder. Uploading replaces it for every graph that reads it.`,
      confirmLabel: "Replace file",
      danger: true,
    });
  }

  async send(file, overwrite) {
    this.zone.dataset.state = "busy";
    this.say(`Uploading ${labelText(file.name)} (${formatBytes(file.size)})`, "busy");
    try {
      const stored = await this.files.upload(file, { overwrite });
      await this.files.refresh();
      const source = this.store.get().draft.source;
      const active = source.type === "text" && source.origin === "file"; // the person may have left the file tabs meanwhile
      if (active) {
        this.store.patch(PATH, stored.name);
      }
      this.say(active ? `${labelText(stored.name)} was uploaded and is now the source.` : `${labelText(stored.name)} was uploaded. Pick it on the Text file tab to use it.`, "success");
    } catch (error) {
      this.say(error.friendly ?? error.message ?? "The upload failed.", "error");
    } finally {
      this.zone.dataset.state = "idle";
    }
  }

  paint() {
    const { status, files, error } = this.files.state;
    const current = this.store.get().draft.source.path ?? "";
    if (status === "error") {
      this.list.replaceChildren(h("p", { class: "hint" }, `Could not list the files: ${error}`), h("button", { type: "button", class: "btn btn-sm", on: { click: () => this.files.refresh() } }, icon("refresh", { size: 14 }), "Try again"));
      return;
    }
    if (files.length === 0) {
      this.list.replaceChildren(h("p", { class: "hint" }, status === "loading" ? "Loading files" : "No files in the sources folder yet."));
      return;
    }
    this.list.replaceChildren(this.table(files, current));
    lockWriteControls(this.list);
  }

  table(files, current) {
    const rows = files.map((file) => this.row(file, file.name === current));
    return h(
      "div",
      { class: "table-wrap ed-files-wrap", tabindex: "0", role: "region", "aria-label": "Files in the sources folder, scrollable" },
      h("table", { class: "table ed-files-table" }, h("caption", { class: "visually-hidden" }, "Files in the sources folder"), h("thead", null, h("tr", null, ["File", "Size", "Changed", ""].map((label, i) => h("th", { scope: "col", class: i === 3 ? "ed-rows-actions" : null }, i === 3 ? h("span", { class: "visually-hidden" }, "Actions") : label)))), h("tbody", null, rows)),
    );
  }

  row(file, inUse) {
    const name = labelText(file.name, 200);
    const use = h("button", { type: "button", class: "btn btn-sm", "aria-label": `Use ${name}`, disabled: inUse, on: { click: () => this.store.patch(PATH, file.name) } }, inUse ? "In use" : "Use");
    const look = h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-label": `Preview ${name}`, on: { click: () => this.showPreview(file.name) } }, "Preview");
    const del = h("button", { type: "button", class: "btn btn-sm btn-ghost btn-icon", "aria-label": `Delete ${name}`, title: `Delete ${name}`, "data-writes": "", on: { click: () => this.remove(file.name) } }, icon("trash", { size: 14 }));
    return h("tr", { "data-in-use": inUse ? "true" : "false" }, h("th", { scope: "row" }, name), h("td", { class: "ed-nowrap" }, formatBytes(file.size)), h("td", { class: "ed-nowrap", title: formatDate(file.modified, { time: true }) }, formatDate(file.modified)), h("td", { class: "ed-rows-actions" }, h("div", { class: "ed-row-actions" }, use, look, del)));
  }

  async showPreview(name) {
    try {
      const lines = await this.files.preview(name);
      this.previewBox.replaceChildren(
        h("div", { class: "cluster cluster-between" }, h("strong", null, `Preview of ${labelText(name, 120)}`), h("button", { type: "button", class: "btn btn-sm btn-ghost", on: { click: () => { this.previewBox.hidden = true; } } }, "Close preview")),
        h("pre", { class: "ed-raw", tabindex: "0", "aria-label": "File preview, scrollable" }, lines.length > 0 ? lines.join("\n") : "(the file is empty)"),
      );
      this.previewBox.hidden = false;
    } catch (error) {
      this.toast.error(error.friendly ?? "The preview could not be loaded.");
    }
  }

  async remove(name) {
    const sure = await confirmDialog({
      title: "Delete this file?",
      message: `${labelText(name, 120)} is removed from the sources folder. Graphs that read it will stop drawing.`,
      confirmLabel: "Delete file",
      danger: true,
    });
    if (!sure) {
      return;
    }
    try {
      await this.files.remove(name);
      if (this.store.get().draft.source.path === name) {
        this.store.remove(PATH);
      }
      await this.files.refresh();
      this.toast.success(`${labelText(name, 80)} was deleted.`);
    } catch (error) {
      this.toast.error(error.friendly ?? "The file could not be deleted.");
    }
  }

  dispose() {
    this.offs.forEach((off) => off());
  }
}

/**
 * Builds the tab.
 * @param {{store: object, files: object, settings: object | null, toast: object}} options
 * @returns {{el: HTMLElement, dispose: () => void}}
 */
export function createUploadTab(options) {
  const tab = new UploadTab(options);
  return { el: tab.el, dispose: () => tab.dispose() };
}
