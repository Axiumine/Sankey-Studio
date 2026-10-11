/**
 * The filter row above the entries table: search, "uncategorised only" and sort.
 *
 * `createToolbar({onSearch, onFilter})` -> `{el, search, only, sort, values(), clear(), hasFilter()}`.
 * `onSearch(text)` fires on every keystroke (the owner debounces); `onFilter()` fires at once when
 * the checkbox or the sort changes. Escape in the search box clears it. Test ids: `entries-search`,
 * `entries-uncategorized-only`, `entries-sort`.
 */

import { h, uid } from "../../core/dom.js";
import { icon } from "../../core/icons.js";

const SORTS = [
  { value: "value", label: "Value, largest first" },
  { value: "source", label: "Source, A to Z" },
  { value: "target", label: "Target, A to Z" },
  { value: "category", label: "Category, A to Z" },
];

/**
 * @param {{onSearch: (text: string) => void, onFilter: () => void}} handlers
 * @returns {object}
 */
export function createToolbar({ onSearch, onFilter }) {
  const searchId = uid("entries-search");
  const sortId = uid("entries-sort");
  const search = h("input", {
    id: searchId,
    class: "input out-search-input",
    type: "search",
    maxlength: "200",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "Search entries",
    "data-testid": "entries-search",
    on: {
      input: () => onSearch(search.value),
      keydown: (event) => {
        if (event.key === "Escape" && search.value !== "") {
          event.preventDefault();
          event.stopPropagation();
          search.value = "";
          onSearch("");
        }
      },
    },
  });
  const only = h("input", { type: "checkbox", "data-testid": "entries-uncategorized-only", on: { change: () => onFilter() } });
  const sort = h("select", { id: sortId, class: "select out-sort-select", "data-testid": "entries-sort", on: { change: () => onFilter() } }, SORTS.map((item) => h("option", { value: item.value }, item.label)));
  const el = h(
    "div",
    { class: "out-toolbar", role: "search", "aria-label": "Filter entries" },
    h("div", { class: "out-search" }, h("label", { class: "visually-hidden", for: searchId }, "Search entries"), icon("search", { size: 16, class: "out-search-icon" }), search),
    h("label", { class: "check out-only" }, only, h("span", null, "Only uncategorised")),
    h("div", { class: "out-sort" }, h("label", { for: sortId }, "Sort by"), sort),
  );
  return {
    el,
    search,
    only,
    sort,
    values: () => ({ q: search.value, onlyUncategorized: only.checked, sort: sort.value }),
    hasFilter: () => search.value.trim() !== "" || only.checked,
    clear() {
      search.value = "";
      only.checked = false;
    },
  };
}
