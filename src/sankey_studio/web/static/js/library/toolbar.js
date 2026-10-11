/**
 * The filter row above the library: search box, sort menu, tag chips, "clear filters".
 *
 * `createToolbar({state, onChange})` returns `{el, setTags(tags), sync(state)}`. `onChange(patch)`
 * receives a partial state (`{q, page: 1}`, `{tag, page: 1}`, `{sort, page: 1}`); the owner
 * merges it and reloads. Typing is debounced; Enter searches at once.
 *
 * Test ids: library-search, library-sort, library-tag-filter (one per chip, data-tag),
 * library-clear-filters.
 */

import { debounce } from "../core/debounce.js";
import { h, uid } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { stripBidi } from "../core/text.js";
import { isShown } from "./names.js";
import { Q_MAX, SORTS } from "./state.js";

const SEARCH_DELAY_MS = 250;
const TAGS_COLLAPSED = 10;

function searchBox(state, onChange) {
  const input = h("input", {
    type: "search",
    class: "input",
    id: uid("library-search"),
    value: state.q,
    maxlength: Q_MAX,
    placeholder: "Search name, description or tag",
    autocomplete: "off",
    spellcheck: "false",
    "data-testid": "library-search",
  });
  const apply = debounce(() => onChange({ q: stripBidi(input.value).trim(), page: 1 }), SEARCH_DELAY_MS);
  input.addEventListener("input", apply);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      apply();
      apply.flush();
    }
  });
  const label = h("label", { class: "visually-hidden", for: input.id }, "Search graphs");
  const wrap = h("div", { class: "search-field" }, label, icon("search", { size: 16, class: "search-icon" }), input);
  return { wrap, input };
}

function sortMenu(state, onChange) {
  const select = h(
    "select",
    { class: "select", id: uid("library-sort"), "data-testid": "library-sort", on: { change: () => onChange({ sort: select.value, page: 1 }) } },
    SORTS.map((item) => h("option", { value: item.value }, item.label)),
  );
  select.value = state.sort;
  const wrap = h("div", { class: "sort-field" }, h("label", { class: "text-sm text-muted", for: select.id }, "Sort by"), select);
  return { wrap, select };
}

function chip(tag, active, onChange) {
  return h(
    "button",
    {
      type: "button",
      class: "chip",
      "aria-pressed": String(active),
      "data-testid": "library-tag-filter",
      "data-tag": tag,
      on: { click: () => onChange({ tag: active ? "" : tag, page: 1 }) },
    },
    tag,
  );
}

function tagRow(onChange) {
  const row = h("div", { class: "tag-filter", role: "group", "aria-label": "Filter by tag", hidden: true });
  let expanded = false;
  const render = (tags, active) => {
    const shown = expanded ? tags : tags.filter((tag, index) => index < TAGS_COLLAPSED || tag === active);
    const hidden = tags.length - shown.length;
    const toggle = tags.length > TAGS_COLLAPSED
      ? h(
        "button",
        {
          type: "button",
          class: "link-button text-sm",
          "aria-expanded": String(expanded),
          on: { click: () => { expanded = !expanded; render(tags, active); } },
        },
        expanded ? "Show fewer tags" : `Show ${hidden} more`,
      )
      : null;
    row.replaceChildren(...shown.map((tag) => chip(tag, tag === active, onChange)), ...(toggle ? [toggle] : []));
    row.hidden = tags.length === 0;
  };
  return { row, render };
}

/**
 * Builds the toolbar.
 * @param {{state: {q: string, tag: string, sort: string}, onChange: (patch: object) => void}} options
 * @returns {{el: HTMLElement, setTags: (tags: string[]) => void, sync: (state: object) => void}}
 */
export function createToolbar({ state, onChange }) {
  const search = searchBox(state, onChange);
  const sort = sortMenu(state, onChange);
  const tags = tagRow(onChange);
  const clear = h(
    "button",
    { type: "button", class: "btn btn-sm btn-ghost", hidden: !(state.q || state.tag), "data-testid": "library-clear-filters", on: { click: () => onChange({ q: "", tag: "", page: 1 }) } },
    icon("x", { size: 14 }),
    "Clear filters",
  );
  let known = [];
  let current = state;
  const el = h("div", { class: "toolbar library-toolbar" }, search.wrap, sort.wrap, clear, h("div", { class: "toolbar-tags" }, tags.row));
  return {
    el,
    setTags(list) {
      known = list.filter(isShown); // a tag made only of control characters has nothing to show
      tags.render(known, current.tag);
    },
    sync(next) {
      current = next;
      if (stripBidi(search.input.value).trim() !== next.q) {
        search.input.value = next.q;
      }
      sort.select.value = next.sort;
      clear.hidden = !(next.q || next.tag);
      tags.render(known, next.tag);
    },
  };
}
