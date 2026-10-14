/**
 * Tab "Paste": the data is typed or pasted into a box and stored inside the graph
 * (`{type: "text", origin: "inline", content}`, up to 2,000,000 characters).
 * Test ids: source-content (the box), source-clear (the icon inside the box, top right).
 * Clear wipes the only copy of the data and a programmatic `value` has no native undo, so it also
 * shows a toast with an Undo button that puts the previous text back through the same `fill` path.
 */

import { announce } from "../../core/a11y.js";
import { h } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { field, textArea } from "../../core/form.js";
import { icon } from "../../core/icons.js";
import { bindText } from "../meta/bind.js";
import { charCount, getIn } from "../meta/util.js";

const CONTENT = ["draft", "source", "content"];
const LIMIT = 2_000_000;
const LIMIT_MESSAGE = `That is more than the ${LIMIT.toLocaleString("en-US")} characters a pasted graph can hold. Upload it as a file instead.`;
const tooLong = (text) => (text ?? "").length > LIMIT && charCount(text) > LIMIT;
const EXAMPLE = [
  "source,target,value,category",
  "Salary,Budget,3000,Income",
  "Freelance,Budget,800,Income",
  "Budget,Rent,1200,Housing",
  "Budget,Utilities,260,Housing",
  "Budget,Food,640,Living",
  "Budget,Transport,230,Living",
  "Budget,Savings,1470,Savings",
].join("\n");

function buildClearButton(onClick) {
  return h(
    "button",
    {
      type: "button",
      class: "btn btn-ghost btn-icon btn-sm ed-textarea-clear",
      "aria-label": "Clear the pasted data",
      title: "Clear",
      "data-testid": "source-clear",
      on: { click: onClick },
    },
    icon("x", { size: 14 }),
  );
}

/**
 * The "Cleared" toast with its Undo. `clear()` wipes the text, `textChanged()` drops the toast
 * (new text came in, so Undo would overwrite it), `dispose()` drops it when the tab goes away.
 */
function createClearUndo({ toast, fill, current }) {
  let undoToast = null;
  return {
    clear() {
      const previous = current();
      fill("", "Cleared");
      undoToast?.dismiss(); // a second toast would keep the Undo of the first text
      undoToast = toast.show("Cleared", { kind: "info", action: { label: "Undo", onClick: () => fill(previous, "Restored") } });
    },
    textChanged() {
      undoToast?.dismiss();
      undoToast = null;
    },
    dispose: () => undoToast?.dismiss(),
  };
}

function buildControl() {
  return textArea({
    code: true,
    rows: 9,
    wrap: "off",
    placeholder: "source,target,value\nSalary,Budget,3000\nBudget,Rent,1200",
    "data-testid": "source-content",
  });
}

async function pasteFromClipboard({ toast, fill, control }) {
  try {
    fill(await navigator.clipboard.readText(), "Pasted from the clipboard");
  } catch {
    toast.info("Your browser did not allow clipboard access. Click in the box and press Ctrl+V (or Cmd+V).");
    control.focus();
  }
}

/**
 * Builds the tab.
 * @param {{store: object, toast: object, fields: Record<string, object>}} options
 * @returns {{el: HTMLElement, dispose: () => void}}
 */
export function createPasteTab({ store, toast, fields }) {
  const control = buildControl();
  const f = field({ label: "Your data", control, hint: "Paste rows from a spreadsheet or a CSV file, or type SankeyMATIC text such as Salary [3000] Budget." });
  // the server rejects an over-long text too; its wording would replace this clearer one
  fields.content = { ...f, setError: (message) => f.setError(tooLong(getIn(store.get(), CONTENT)) ? LIMIT_MESSAGE : message) };
  const count = h("span", { class: "ed-count" });
  const paste = h("button", { type: "button", class: "btn btn-sm", on: { click: () => pasteFromClipboard({ toast, fill, control }) } }, icon("copy", { size: 14 }), "Paste from clipboard");
  const example = h("button", { type: "button", class: "btn btn-sm btn-ghost", on: { click: () => fill(EXAMPLE, "Example data added") } }, "Insert an example");
  const clear = buildClearButton(() => undo.clear());
  const box = h("div", { class: "ed-textarea" });
  f.el.insertBefore(box, control); // the label (for=id), hint and error keep their place and wiring
  box.append(control, clear); // moves the textarea into the frame that carries the Clear icon

  function fill(text, message) {
    store.patch(CONTENT, text);
    announce(message);
    control.focus();
  }
  const undo = createClearUndo({ toast, fill, current: () => getIn(store.get(), CONTENT) ?? "" });

  const paint = (text) => {
    const length = charCount(text ?? ""); // characters as the server counts them: an emoji is one
    count.textContent = length > 0 ? `${formatNumber(length, { maximumFractionDigits: 0 })} characters` : "";
    example.hidden = length > 0;
    clear.hidden = length === 0;
    if (text !== "") {
      undo.textChanged(); // new text came in (typed, pasted, restored) or the tab changed
    }
    f.setError(tooLong(text) ? LIMIT_MESSAGE : "");
  };
  const offs = [
    bindText(store, control, CONTENT),
    store.subscribe(paint, { select: (state) => getIn(state, CONTENT), immediate: true }),
  ];
  const el = h("div", { class: "stack stack-sm" }, f.el, h("div", { class: "cluster ed-toolbar" }, paste, example, count));
  return {
    el,
    dispose: () => {
      offs.forEach((off) => off());
      undo.dispose();
    },
  };
}
