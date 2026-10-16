// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * A chip input: a list of short text items (tags, node names) edited in place.
 *
 * Keyboard: type and press Enter (or the separator, a comma for tags) to add; Backspace in the
 * empty box removes the last chip; every chip has a remove button; pasting several lines adds them
 * all; leaving the box adds what is typed. Suggestions use a native `<datalist>`: picking one adds
 * it at once. Items are text nodes only. Limits are enforced with a message, never silently.
 *
 * `createChipInput({label, itemName, items, maxItems, maxLength, separators, suggestions, hint,
 * testid, onChange})` -> `{el, input, getItems(), setItems(items), setError(message)}`.
 */

import { announce } from "../../core/a11y.js";
import { h, uid } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { stripBidi } from "../../core/text.js";
import { charCount, clipText, labelText } from "./util.js";

function parts(text, separators) {
  let chunks = text.split(/\r\n|\r|\n/);
  for (const separator of separators) {
    chunks = chunks.flatMap((chunk) => chunk.split(separator));
  }
  return chunks.map((item) => item.trim()).filter(Boolean);
}

class ChipInput {
  constructor(config) {
    this.config = config;
    this.items = [...(config.items ?? [])];
    this.separators = config.separators ?? "";
    this.name = config.itemName ?? "item";
    const id = uid("chips");
    this.list = h("ul", { class: "ed-chip-list", role: "list", "aria-label": `${config.label} (added)` });
    this.datalist = h("datalist", { id: `${id}-options` });
    this.input = h("input", {
      type: "text",
      id,
      class: "ed-chip-input",
      autocomplete: "off",
      spellcheck: "false",
      list: this.datalist.id,
      placeholder: config.placeholder ?? null,
      "aria-describedby": `${id}-hint ${id}-error`,
      "data-testid": config.testid ?? null,
      on: {
        keydown: (event) => this.onKey(event),
        input: (event) => this.onInput(event),
        paste: (event) => this.onPaste(event),
        blur: () => this.commit(this.input.value),
        focus: () => this.refreshOptions(),
      },
    });
    this.hint = h("p", { class: "hint", id: `${id}-hint`, hidden: !config.hint }, config.hint);
    this.error = h("p", { class: "field-error", id: `${id}-error`, hidden: true });
    const box = h("div", { class: "ed-chips", on: { click: (event) => event.target === box && this.input.focus() } }, this.list, this.input);
    this.el = h("div", { class: "field ed-chips-field" }, h("label", { for: id }, config.label), box, this.datalist, this.hint, this.error);
    this.render();
  }

  getItems() {
    return [...this.items];
  }

  setItems(items) {
    this.items = [...items];
    this.render();
  }

  setError(message) {
    this.error.textContent = stripBidi(message ?? "");
    this.error.hidden = !message;
    this.input.setAttribute("aria-invalid", message ? "true" : "false");
  }

  render() {
    this.list.replaceChildren(...this.items.map((text, index) => this.chip(text, index)));
    this.refreshOptions();
  }

  chip(text, index) {
    const remove = h(
      "button",
      { type: "button", class: "ed-chip-remove", "aria-label": `Remove ${this.name} ${labelText(text)}`, on: { click: () => this.removeAt(index) } },
      icon("x", { size: 12 }),
    );
    return h("li", { class: "chip ed-chip", title: text.length > 40 ? labelText(text, 200) : null }, h("span", { class: "ed-chip-text" }, text), remove);
  }

  refreshOptions() {
    const taken = new Set(this.items);
    const options = (this.config.suggestions?.() ?? []).filter((text) => !taken.has(text)).slice(0, 200);
    this.datalist.replaceChildren(...options.map((text) => h("option", { value: text })));
  }

  removeAt(index) {
    const [gone] = this.items.splice(index, 1);
    this.setError("");
    this.render();
    this.input.focus();
    announce(`Removed ${this.name} ${labelText(gone)}`);
    this.config.onChange?.(this.getItems());
  }

  /** Adds every part of `text`; returns true when something was added. A part that is refused stays in the box. */
  commit(text) {
    const added = [];
    const kept = [];
    this.setError("");
    for (const item of parts(text, this.separators)) {
      const problem = kept.length === 0 ? this.problemWith(item) : "";
      if (problem) {
        this.setError(problem);
      }
      if (problem || kept.length > 0) {
        kept.push(item);
      } else if (!this.items.includes(item)) {
        this.items.push(item);
        added.push(item);
      }
    }
    this.input.value = kept.join(this.separators[0] ?? " ");
    if (added.length > 0) {
      this.render();
      announce(`Added ${this.name} ${labelText(added[0])}${added.length > 1 ? ` and ${added.length - 1} more` : ""}`);
      this.config.onChange?.(this.getItems());
    }
    return added.length > 0;
  }

  problemWith(item) {
    const { maxItems, maxLength } = this.config;
    if (maxLength && charCount(item) > maxLength) {
      return `A ${this.name} can have at most ${maxLength} characters.`;
    }
    if (maxItems && this.items.length >= maxItems && !this.items.includes(item)) {
      return `At most ${maxItems} ${this.name}s.`;
    }
    return "";
  }

  onKey(event) {
    const separator = this.separators.includes(event.key) && event.key.length === 1;
    if (event.key === "Enter" || separator) {
      event.preventDefault();
      this.commit(this.input.value);
    } else if (event.key === "Backspace" && this.input.value === "" && this.items.length > 0) {
      event.preventDefault();
      this.removeAt(this.items.length - 1);
    }
  }

  onInput(event) {
    this.refreshOptions();
    const { maxLength } = this.config;
    if (maxLength && this.input.value.length > maxLength && charCount(this.input.value) > maxLength) {
      this.input.value = clipText(this.input.value, maxLength);
      const message = `A ${this.name} can have at most ${maxLength} characters, so the rest was cut off.`;
      this.setError(message);
      announce(message);
    } else if (event.inputType === "insertReplacementText") {
      this.commit(this.input.value); // a suggestion was picked from the list
    }
  }

  onPaste(event) {
    const text = event.clipboardData?.getData("text") ?? "";
    if (/[\r\n]/.test(text) || [...this.separators].some((char) => text.includes(char))) {
      event.preventDefault();
      this.commit(text);
    }
  }
}

/**
 * Creates a chip input; see the file header.
 * @param {object} config
 * @returns {{el: HTMLElement, input: HTMLInputElement, getItems: () => string[], setItems: (items: string[]) => void, setError: (message?: string) => void}}
 */
export function createChipInput(config) {
  const chips = new ChipInput(config);
  return {
    el: chips.el,
    input: chips.input,
    getItems: () => chips.getItems(),
    setItems: (items) => chips.setItems(items),
    setError: (message) => chips.setError(message),
  };
}
