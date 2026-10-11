/**
 * Tab "Paste": the data is typed or pasted into a box and stored inside the graph
 * (`{type: "text", origin: "inline", content}`, up to 2,000,000 characters).
 * Test id: source-content (the box).
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

/**
 * Builds the tab.
 * @param {{store: object, toast: object, fields: Record<string, object>}} options
 * @returns {{el: HTMLElement, dispose: () => void}}
 */
export function createPasteTab({ store, toast, fields }) {
  const control = textArea({
    code: true,
    rows: 9,
    wrap: "off",
    placeholder: "source,target,value\nSalary,Budget,3000\nBudget,Rent,1200",
    "data-testid": "source-content",
  });
  const f = field({ label: "Your data", control, hint: "Paste rows from a spreadsheet or a CSV file, or type SankeyMATIC text such as Salary [3000] Budget." });
  // the server rejects an over-long text too; its wording would replace this clearer one
  fields.content = { ...f, setError: (message) => f.setError(tooLong(getIn(store.get(), CONTENT)) ? LIMIT_MESSAGE : message) };
  const count = h("span", { class: "ed-count" });
  const paste = h("button", { type: "button", class: "btn btn-sm", on: { click: () => pasteFromClipboard() } }, icon("copy", { size: 14 }), "Paste from clipboard");
  const example = h("button", { type: "button", class: "btn btn-sm btn-ghost", on: { click: () => fill(EXAMPLE, "Example data added") } }, "Insert an example");
  const clear = h("button", { type: "button", class: "btn btn-sm btn-ghost", on: { click: () => fill("", "Cleared") } }, icon("x", { size: 14 }), "Clear");

  function fill(text, message) {
    store.patch(CONTENT, text);
    announce(message);
    control.focus();
  }

  async function pasteFromClipboard() {
    try {
      fill(await navigator.clipboard.readText(), "Pasted from the clipboard");
    } catch {
      toast.info("Your browser did not allow clipboard access. Click in the box and press Ctrl+V (or Cmd+V).");
      control.focus();
    }
  }

  const paint = (text) => {
    const length = charCount(text ?? ""); // characters as the server counts them: an emoji is one
    count.textContent = length > 0 ? `${formatNumber(length, { maximumFractionDigits: 0 })} characters` : "";
    example.hidden = length > 0;
    clear.hidden = length === 0;
    f.setError(tooLong(text) ? LIMIT_MESSAGE : "");
  };
  const offs = [
    bindText(store, control, CONTENT),
    store.subscribe(paint, { select: (state) => getIn(state, CONTENT), immediate: true }),
  ];
  const el = h("div", { class: "stack stack-sm" }, f.el, h("div", { class: "cluster ed-toolbar" }, paste, example, clear, count));
  return { el, dispose: () => offs.forEach((off) => off()) };
}
