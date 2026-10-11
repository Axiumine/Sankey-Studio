/**
 * Tab "Text file": read a file that is already in the sources folder of the server
 * (`{type: "text", origin: "file", path}`). New files are added on the Upload tab.
 * Test id: source-file-select.
 */

import { h } from "../../core/dom.js";
import { formatBytes, formatDate } from "../../core/format.js";
import { field, selectInput } from "../../core/form.js";
import { icon } from "../../core/icons.js";
import { labelText } from "../meta/util.js";

const PATH = ["draft", "source", "path"];

function optionList(files, current) {
  const options = [{ value: "", label: files.length > 0 ? "Choose a file" : "No files yet" }];
  for (const file of files) {
    options.push({ value: file.name, label: `${labelText(file.name, 80)} (${formatBytes(file.size)})` });
  }
  if (current && !files.some((file) => file.name === current)) {
    options.push({ value: current, label: `${labelText(current, 80)} (not in the folder)` });
  }
  return options;
}

function infoText({ status, error, picked, empty }) {
  if (status === "error") {
    return `Could not list the files: ${error}`;
  }
  if (status === "loading") {
    return "Loading files";
  }
  if (picked) {
    return `${formatBytes(picked.size)}, changed ${formatDate(picked.modified, { time: true })}`;
  }
  return empty ? "The sources folder is empty. Upload a file to start." : "";
}

/**
 * Builds the tab.
 * @param {{store: object, files: ReturnType<typeof import("./files.js").createFiles>, fields: Record<string, object>, goto: (tab: string) => void}} options
 * @returns {{el: HTMLElement, dispose: () => void}}
 */
export function createTextTab({ store, files, fields, goto }) {
  const select = selectInput({ options: optionList([], null), "data-testid": "source-file-select" });
  const f = field({ label: "File", control: select, hint: "Files in the sources folder of this server (csv, tsv, txt, json, ndjson, sankey)." });
  fields.path = f;
  const info = h("p", { class: "hint ed-file-info" });
  const upload = h("button", { type: "button", class: "btn btn-sm", on: { click: () => goto("upload") } }, icon("upload", { size: 14 }), "Upload a new file");
  const retry = h("button", { type: "button", class: "btn btn-sm", on: { click: () => files.refresh() } }, icon("refresh", { size: 14 }), "Try again");
  select.addEventListener("change", () => {
    if (select.value === "") {
      store.remove(PATH);
    } else {
      store.patch(PATH, select.value);
    }
  });

  const paint = () => {
    const { status, files: list, error } = files.state;
    const current = store.get().draft.source.path ?? "";
    select.replaceChildren(...optionList(list, current).map((o) => h("option", { value: o.value }, o.label)));
    select.value = current;
    select.disabled = status === "loading";
    const picked = files.find(current);
    f.setHint(status === "error" ? "" : "Files in the sources folder of this server (csv, tsv, txt, json, ndjson, sankey).");
    info.textContent = infoText({ status, error, picked, empty: list.length === 0 });
    retry.hidden = status !== "error";
    upload.hidden = status === "error";
  };
  const offs = [files.subscribe(paint), store.subscribe(paint, { select: (state) => state.draft.source.path })];
  paint();
  if (files.state.status === "idle") {
    files.refresh();
  }
  const el = h("div", { class: "stack stack-sm" }, f.el, info, h("div", { class: "cluster ed-toolbar" }, upload, retry));
  return { el, dispose: () => offs.forEach((off) => off()) };
}
