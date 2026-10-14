/**
 * "Add a flow": the dialog behind the Entries card's "Add entry" button (F7). F2 (a click on a node
 * of the chart, chart/node-flow.js) opens the same dialog with a prefilled end, the direction choice
 * (add-form.js) and a title that names the node ("Add a flow from X" / "Add a flow into X"; the title
 * follows the choice).
 *
 * `openAddEntry({store, edits, names, prefill})` -> `Promise<boolean>` (true once an entry was added).
 *   - `edits` is the edit engine (`editsFor(ctx)`): `edits.addEntry` decides where the entry goes
 *     (the text or manual links in the draft, a file or a collection after the consent dialog, or the
 *     graph alone) and says so in a toast; this dialog only collects and checks the fields;
 *   - `names` is the category suggestion helper of the entries panel (`known()`, `add(name)`);
 *   - `prefill` is `{source?, target?}` and, for F2, `{node, direction}` (see add-form.js).
 * The dialog stays open on every failure and shows the sentence in `add-entry-error` (a cycle, the
 * 5,000 link limit, a stale draft); a cancelled consent question leaves it open without a message.
 * Enter submits. Only one dialog exists at a time. The consent dialog may open ABOVE this one (the
 * focus traps nest: the newest one reacts); focus returns to the opener when it closes.
 *
 * `createAddButton({store, edits, names})` -> `{el, dispose}`: the header button `entries-add`. It is
 * always rendered, and disabled with a title when the source names nothing to edit yet.
 * Test ids: `entries-add`, `add-entry-dialog`, `add-entry-submit`, `add-entry-cancel` (the field ids
 * are in ./add-form.js).
 */

import { openDialog } from "../../core/dialog.js";
import { h, setBusy } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { closePopovers } from "../../core/popover.js";
import { toast } from "../../core/toast.js";
import { plainText } from "../chart/errors.js";
import { classify } from "../edits/classify.js";
import { createAddForm, checkEntry, titleFor } from "./add-form.js";

let shown = null;

function known(names, store) {
  return names?.known ? names.known() : (store.get().bundle?.category_names ?? []);
}

const FAILED = "The entry could not be added.";

/** One open dialog: the form, the busy state of the Add button and what an answer of the engine does. */
class AddSession {
  constructor({ store, edits, names, prefill }) {
    this.store = store;
    this.edits = edits;
    this.names = names;
    this.busy = false;
    this.open = true;
    const retitle = (direction) => this.retitle({ ...prefill, direction });
    this.form = createAddForm({ bundle: store.get().bundle, categories: known(names, store), prefill, onDirection: retitle });
    this.dialog = openDialog({
      title: titleFor(prefill),
      testid: "add-entry-dialog",
      body: this.form.el,
      initialFocus: () => this.form.firstEmpty(),
      actions: [
        { label: "Cancel", value: false, testid: "add-entry-cancel" },
        { label: "Add", kind: "primary", testid: "add-entry-submit", onClick: () => this.submit() },
      ],
    });
    this.button = this.dialog.el.querySelector('[data-testid="add-entry-submit"]');
    this.form.el.addEventListener("keydown", (event) => this.onKey(event));
    this.stop = store.subscribe(() => this.form.refresh(store.get().bundle), { select: (state) => state.bundle });
    this.promise = this.dialog.result.then((value) => this.closed(value));
  }

  /** F2: the title follows the direction choice. */
  retitle(prefill) {
    const heading = this.dialog.el.querySelector(".dialog-title");
    if (heading) {
      heading.textContent = titleFor(prefill);
    }
  }

  onKey(event) {
    if (event.key === "Enter" && !event.isComposing && event.target instanceof HTMLInputElement) {
      event.preventDefault();
      this.submit();
    }
  }

  async submit() {
    if (this.busy) {
      return;
    }
    const check = checkEntry(this.form.values(), known(this.names, this.store));
    if (!check.ok) {
      this.form.fail(check);
      return;
    }
    this.form.clearError();
    this.busy = true;
    setBusy(this.button, true);
    try {
      this.finish(await this.edits.addEntry(check.entry), check.entry);
    } finally {
      this.busy = false;
      setBusy(this.button, false);
    }
  }

  /** Success closes the dialog; a cancelled consent question changes nothing; anything else is said. */
  finish(result, entry) {
    if (result.ok) {
      if (entry.category) {
        this.names?.add?.(entry.category);
      }
      this.dialog.close(true);
    } else if (!result.cancelled) {
      const message = plainText(result.message ?? FAILED);
      if (this.open) {
        this.form.fail({ message });
      } else {
        toast.error(message); // the dialog was closed while the edit ran
      }
    }
  }

  closed(value) {
    this.open = false;
    shown = null;
    this.stop();
    return value === true;
  }
}

/**
 * Opens the dialog (a second call while it is open only focuses it).
 * @param {{store: object, edits: {addEntry: Function}, names?: {known: () => string[], add: (name: string) => void}, prefill?: {source?: string, target?: string, node?: string, direction?: "from" | "to"}}} options
 * @returns {Promise<boolean>}
 */
export function openAddEntry(options) {
  if (shown) {
    shown.form.firstEmpty().focus();
    return shown.promise;
  }
  closePopovers();
  shown = new AddSession(options);
  return shown.promise;
}

/**
 * The "Add entry" button of the Entries card header.
 * @param {{store: object, edits: object, names?: object}} deps
 * @returns {{el: HTMLButtonElement, dispose: () => void}}
 */
export function createAddButton({ store, edits, names }) {
  const el = h(
    "button",
    { type: "button", class: "btn btn-sm out-entries-add", "aria-haspopup": "dialog", "data-testid": "entries-add", on: { click: () => openAddEntry({ store, edits, names }) } },
    icon("plus", { size: 15 }),
    "Add entry",
  );
  const paint = () => {
    const kind = classify(store.get().draft?.source);
    el.disabled = kind.where === "blocked";
    if (el.disabled) {
      el.title = kind.message ?? "";
    } else {
      el.removeAttribute("title");
    }
  };
  paint();
  return { el, dispose: store.subscribe(paint, { select: (state) => state.draft?.source }) };
}
