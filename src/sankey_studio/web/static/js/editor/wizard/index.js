/**
 * The new-graph wizard: two steps drawn into the page before the editor starts.
 *
 * `runWizard({api, settings, toast})` -> `Promise<Seed>` (editor/wizard/seed.js). It resolves when
 * the person finishes ("Start editing" with data, or "Do it later" for an empty Paste or Manual
 * source) and never rejects on a user action. Leaving (Cancel, the header links) is a normal page
 * navigation.
 *
 * It is an inline card, not a modal, and it calls the API only for tag suggestions and what the
 * source tabs read themselves (the files list, the Mongo pickers); nothing is created, so it also
 * works on a read-only server (the Upload tab is disabled there). The wizard keeps its own store;
 * the editor starts from the seed, and "nothing is saved until you press Save".
 *
 * Step 1 "details": name (required), description, tags. Step 2 "source": the source tabs.
 * Test ids: new-wizard (`data-step` = details|source; `#page-root[data-wizard]` mirrors it),
 * wizard-step-details, wizard-step-source, wizard-next, wizard-back, wizard-create, wizard-later,
 * wizard-cancel. The existing source-has-header checkbox and the tab ids live inside step 2.
 * With typed input the unsaved-changes guard asks before a link inside the app is followed.
 */

import { announce } from "../../core/a11y.js";
import { boot, canWrite, lockWriteControls, pageRoot } from "../../core/boot.js";
import { h, mount } from "../../core/dom.js";
import { installLeaveGuard } from "../meta/guard.js";
import { hasSourceInput } from "../preview.js";
import { createSwitcher, defaultSource, kindOf } from "../source/model.js";
import { createStore, initialState } from "../store.js";
import { seedFrom } from "./seed.js";
import { buildDetailsStep, buildSourceStep } from "./steps.js";

const STEP_NAMES = { details: "Details", source: "Data source" };
const SAVE_NOTE = "Nothing is saved until you press Save.";
const READ_ONLY_NOTE = "This server is read-only: you can draw, not save.";

function cancelHref() {
  const folder = boot().folder_id;
  return typeof folder === "string" && folder ? `/?folder=${encodeURIComponent(folder)}` : "/";
}

function stepList() {
  const items = Object.keys(STEP_NAMES).map((id, index) => h("li", { "data-step-id": id }, h("span", { class: "ed-wizard-num" }, String(index + 1)), STEP_NAMES[id]));
  return { el: h("ol", { class: "ed-wizard-steps", "aria-label": "Steps" }, items), items };
}

function buildActions() {
  const button = (testid, label, extra = {}) => h("button", { type: "button", class: ["btn", extra.primary ? "btn-primary" : null], "data-testid": testid, hidden: extra.hidden === true }, label);
  const cancel = h("a", { class: "btn ed-wizard-cancel", href: cancelHref(), "data-testid": "wizard-cancel" }, "Cancel");
  const parts = {
    cancel,
    back: button("wizard-back", "Back", { hidden: true }),
    later: button("wizard-later", "Do it later", { hidden: true }),
    next: button("wizard-next", "Next", { primary: true }),
    create: button("wizard-create", "Start editing", { primary: true, hidden: true }),
  };
  const note = h("p", { class: "hint ed-wizard-note" }, canWrite() ? SAVE_NOTE : READ_ONLY_NOTE);
  const el = h("div", { class: "ed-wizard-actions" }, parts.cancel, parts.back, parts.later, parts.next, parts.create);
  return { el, note, ...parts };
}

class Wizard {
  constructor({ api, settings, toast }, resolve) {
    this.settings = settings;
    this.resolve = resolve;
    this.store = createStore(initialState());
    this.root = pageRoot();
    this.step = "details";
    this.actions = buildActions();
    this.steps = stepList();
    this.details = buildDetailsStep({ store: this.store, api });
    this.source = buildSourceStep({ store: this.store, api, toast, settings, switcher: createSwitcher(this.store, settings), onChange: () => this.paint() });
    this.card = h(
      "section",
      { class: "card ed-wizard", "data-testid": "new-wizard", "data-step": this.step, "aria-label": "New graph" },
      h("div", { class: "card-body stack" }, this.steps.el, this.details.el, this.source.el, this.actions.el, this.actions.note),
    );
    this.guard = installLeaveGuard({ get: () => ({ status: { dirty: this.typed() } }) });
    this.off = this.store.subscribe(() => this.paint());
    this.wire();
    mount(this.root, this.card);
    lockWriteControls(this.card);
    this.paint();
    this.details.focus();
  }

  hasInput() {
    return hasSourceInput(this.store.get().draft);
  }

  typed() {
    const { meta } = this.store.get();
    return [meta.name, meta.description].some((text) => text.trim() !== "") || meta.tags.length > 0 || this.hasInput();
  }

  wire() {
    const { actions } = this;
    this.details.onEnter(() => this.next());
    actions.next.addEventListener("click", () => this.next());
    actions.back.addEventListener("click", () => this.go("details"));
    actions.create.addEventListener("click", () => this.hasInput() && this.finish(seedFrom(this.store)));
    actions.later.addEventListener("click", () => this.finish(seedFrom(this.store, defaultSource(kindOf(this.source.tabs.selected()), this.settings))));
  }

  paint() {
    const { actions, step } = this;
    const second = step === "source";
    this.card.dataset.step = step;
    this.root.dataset.wizard = step;
    this.details.el.hidden = second;
    this.source.el.hidden = !second;
    actions.back.hidden = !second;
    actions.next.hidden = second;
    actions.create.hidden = !second;
    actions.create.disabled = !this.hasInput();
    if (actions.create.disabled) {
      actions.create.setAttribute("aria-describedby", "wizard-source-hint");
    } else {
      actions.create.removeAttribute("aria-describedby");
    }
    actions.later.hidden = !(second && this.source.skippable() && !this.hasInput());
    this.source.paintHint();
    for (const item of this.steps.items) {
      if (item.dataset.stepId === step) {
        item.setAttribute("aria-current", "step");
      } else {
        item.removeAttribute("aria-current");
      }
    }
  }

  go(step) {
    this.step = step;
    this.paint();
    (step === "source" ? this.source : this.details).focusHeading();
    announce(step === "source" ? "Step 2 of 2: Data source" : "Step 1 of 2: Details");
  }

  next() {
    if (this.details.validate()) {
      this.go("source");
    }
  }

  finish(seed) {
    this.guard.dispose();
    this.off();
    this.details.dispose();
    this.source.dispose();
    delete this.root.dataset.wizard;
    this.resolve(seed);
  }
}

/**
 * Runs the wizard in the page root.
 * @param {{api: object, settings: object | null, toast: object}} deps
 * @returns {Promise<{meta: {name: string, description: string, tags: string[]}, source: object}>}
 */
export function runWizard(deps) {
  return new Promise((resolve) => new Wizard(deps, resolve));
}
