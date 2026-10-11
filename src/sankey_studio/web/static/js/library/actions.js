/**
 * The buttons next to the library heading: Import (a file chooser) and Export.
 *
 * Import is a `<label>` that wraps a real file input (visually hidden but focusable, so the
 * keyboard and screen readers get a native control and the label shows the focus ring). It carries
 * `data-testid="library-import"`: click it to open the chooser, or `setInputFiles` on it (the
 * browser targets the control inside). Read-only servers disable it with a title.
 * Export (`library-export`) changes its label (and tooltip) with what it will export; the owner sets it.
 * `focusImport()` puts the focus back on the Import control once a flow around it is over.
 */

import { canWrite } from "../core/boot.js";
import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";

const READ_ONLY_TITLE = "Not available: this server is read-only";

/**
 * @param {{onFile: (file: File) => void, onExport: (button: HTMLButtonElement) => void}} options
 * @returns {{el: HTMLElement, openPicker: () => void, focusImport: () => void, setExport: (info: {label: string, disabled: boolean, title?: string}) => void}}
 */
export function createActions({ onFile, onExport }) {
  const writable = canWrite();
  const input = h("input", {
    type: "file",
    class: "visually-hidden",
    accept: ".json,application/json",
    disabled: !writable,
    on: {
      change: () => {
        const file = input.files?.[0];
        input.value = ""; // the same file can be chosen again
        if (file) {
          onFile(file);
        }
      },
    },
  });
  const label = h(
    "label",
    {
      class: "btn import-button",
      "data-testid": "library-import",
      "aria-disabled": writable ? null : "true",
      title: writable ? "Import graphs from a bundle file" : READ_ONLY_TITLE,
    },
    icon("upload", { size: 14 }),
    "Import",
    input,
  );
  const exportButton = h(
    "button",
    { type: "button", class: "btn", "data-testid": "library-export", on: { click: (event) => onExport(event.currentTarget) } },
    icon("download", { size: 14 }),
    h("span", { class: "export-label" }, "Export"),
  );
  return {
    el: h("div", { class: "cluster", role: "group", "aria-label": "Bundle" }, label, exportButton),
    openPicker: () => input.click(),
    focusImport: () => input.focus(),
    setExport({ label: text, disabled, title = "" }) {
      exportButton.querySelector(".export-label").textContent = text;
      exportButton.disabled = disabled;
      exportButton.title = title;
    },
  };
}
