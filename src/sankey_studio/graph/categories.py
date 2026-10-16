# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Step 2: resolve one category per aggregated entry (never per raw row).

Precedence, highest first: (1) ``TransformSpec.entry_categories`` (``None`` forces
"uncategorised"), (2) the category found in the data, (3) glob ``category_rules`` (first match
wins). With ``rules_override`` the rules rank above the data but still below (1).

The rule tables are evaluated once per DISTINCT node name. Patterns are globs matched with
``fnmatch.fnmatchcase`` on casefolded text: fnmatch translates a glob into an anchored regular
expression that cannot backtrack catastrophically, and caches the compiled form, so no user
text ever reaches ``re.compile``.

Matching is still ``distinct names * rules`` ``fnmatch`` calls (about 5 million a second), so
``check_rule_work`` refuses a graph above ``MAX_RULE_WORK`` of them BEFORE any name is matched.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

from sankey_studio.errors import GraphTooLargeError
from sankey_studio.graph.intern import FIELD_MASK, pack_key, unpack_key
from sankey_studio.graph.state import new_index_column, new_value_column
from sankey_studio.models.base import MAX_CATEGORIES
from sankey_studio.util import category_key

if TYPE_CHECKING:
    from sankey_studio.graph.state import BuildState
    from sankey_studio.models import CategoryRule

#: Rule sides: a rule with ``match="either"`` counts for both.
SOURCE_SIDE = frozenset({"source", "either"})
TARGET_SIDE = frozenset({"target", "either"})
#: Most ``distinct node names * category rules`` a build accepts (about 4 s of matching).
MAX_RULE_WORK = 20_000_000


def check_rule_work(names: int, rules: int) -> None:
    """Raise ``GraphTooLargeError`` when ``names * rules`` exceeds ``MAX_RULE_WORK``."""
    if names * rules > MAX_RULE_WORK:
        raise GraphTooLargeError(
            f"The category rules are too expensive for this graph ({rules} rules over {names} "
            "distinct node names); remove rules or narrow the data"
        )


def _first_match(folded: str, patterns: list[tuple[int, str]]) -> int:
    """Index of the first rule whose glob matches ``folded``, or -1."""
    for index, pattern in patterns:
        if fnmatchcase(folded, pattern):
            return index
    return -1


def rule_tables(rules: list[CategoryRule], names: list[str]) -> tuple[list[int], list[int]]:
    """First matching rule index per node id, for the source side and for the target side.

    Raises ``GraphTooLargeError`` (before matching anything) when the work is above the cap.
    """
    check_rule_work(len(names), len(rules))
    side_patterns = (
        [(i, rule.pattern.casefold()) for i, rule in enumerate(rules) if rule.match in side]
        for side in (SOURCE_SIDE, TARGET_SIDE)
    )
    source_patterns, target_patterns = side_patterns
    by_source: list[int] = []
    by_target: list[int] = []
    for name in names:
        folded = name.casefold()
        by_source.append(_first_match(folded, source_patterns))
        by_target.append(_first_match(folded, target_patterns))
    return by_source, by_target


@dataclass(slots=True)
class CategorySlots:
    """Resolved categories in first-seen order (the stable colour slot) with one spelling each."""

    state: BuildState
    by_name: dict[str, int] = field(default_factory=dict)
    by_key: dict[str, int] = field(default_factory=dict)
    display: list[str] = field(default_factory=list)
    dropped: set[str] = field(default_factory=set)

    def slot(self, name: str | None) -> int:
        """Slot of ``name`` (-1 for ``None`` and for categories beyond ``MAX_CATEGORIES``)."""
        if name is None:
            return -1
        slot = self.by_name.get(name)
        if slot is None:
            slot = self._new_slot(name)
            self.by_name[name] = slot
        return slot

    def _new_slot(self, name: str) -> int:
        key = category_key(name)
        slot = self.by_key.get(key)
        if slot is not None:
            return slot
        if len(self.display) >= MAX_CATEGORIES:
            self.dropped.add(key)
            return -1
        slot = len(self.display)
        data_id = self.state.data_cat_keys.get(key)
        # the spelling already seen in the data wins over a rule's or an entry's spelling
        self.display.append(self.state.data_cats[data_id - 1] if data_id else name)
        self.by_key[key] = slot
        return slot


@dataclass(slots=True)
class Resolver:
    """Applies the precedence to one entry at a time."""

    state: BuildState
    slots: CategorySlots
    explicit: dict[tuple[int, int], str | None]
    rule_source: list[int]
    rule_target: list[int]
    matched: set[tuple[int, int]] = field(default_factory=set)

    @classmethod
    def create(cls, state: BuildState) -> Resolver:
        transform = state.transform
        explicit: dict[tuple[int, int], str | None] = {}
        if transform.entry_categories:
            ids = {name: i for i, name in enumerate(state.names)}
            for entry in transform.entry_categories:
                with suppress(KeyError):  # a pair naming an unknown node matches no entry
                    explicit[(ids[entry.source], ids[entry.target])] = entry.category
        by_source, by_target = rule_tables(transform.category_rules, state.names)
        return cls(state, CategorySlots(state), explicit, by_source, by_target)

    def category(self, source: int, target: int, data_id: int) -> str | None:
        """The category name of the entry, or ``None`` (uncategorised)."""
        pair = (source, target)
        if pair in self.explicit:
            self.matched.add(pair)
            return self.explicit[pair]
        data = self.state.data_cats[data_id - 1] if data_id else None
        rule = self._rule(source, target)
        if self.state.transform.rules_override:
            return rule or data
        return data or rule

    def _rule(self, source: int, target: int) -> str | None:
        matching = [i for i in (self.rule_source[source], self.rule_target[target]) if i >= 0]
        return self.state.transform.category_rules[min(matching)].category if matching else None

    @property
    def may_collapse(self) -> bool:
        """True when two entries could now share ``(source, target, category)``."""
        return bool(self.explicit or self.state.transform.category_rules or self.slots.dropped)

    def warnings(self) -> list[str]:
        """One aggregated message per kind of problem."""
        state = self.state
        unmatched = len(state.transform.entry_categories) - len(self.matched)
        messages = (
            (
                state.unusable_categories,
                "{} category value(s) in the data were empty, reserved or unusable; ignored",
            ),
            (unmatched, "{} entry_categories matched no entry"),
            (
                len(self.slots.dropped),
                (
                    f"{{}} category name(s) beyond the limit of {MAX_CATEGORIES} were left "
                    "uncategorised"
                ),
            ),
        )
        return [text.format(count) for count, text in messages if count]


def resolve_categories(state: BuildState) -> None:
    """Turn ``state.agg`` into the entry columns, with one resolved category slot per entry."""
    resolver = Resolver.create(state)
    category, slot = resolver.category, resolver.slots.slot
    for key, value in state.agg.items():
        source, target, data_id = unpack_key(key)
        state.e_src.append(source)
        state.e_tgt.append(target)
        state.e_cat.append(slot(category(source, target, data_id)))
        state.e_val.append(value)
    state.agg.clear()
    state.categories = resolver.slots.display
    state.warnings.extend(resolver.warnings())
    if resolver.may_collapse:
        merge_entries(state)


def merge_entries(state: BuildState) -> None:
    """Sum entries that now share ``(source, target, category)``; first appearance order stays."""
    index: dict[int, int] = {}
    src, tgt, cat, val = (
        new_index_column(),
        new_index_column(),
        new_index_column(),
        new_value_column(),
    )
    for s, t, c, v in zip(state.e_src, state.e_tgt, state.e_cat, state.e_val, strict=True):
        key = pack_key(s, t, c & FIELD_MASK)  # -1 (uncategorised) packs as all ones
        position = index.get(key)
        if position is None:
            index[key] = len(val)
            src.append(s)
            tgt.append(t)
            cat.append(c)
            val.append(v)
        else:
            val[position] += v
    state.e_src, state.e_tgt, state.e_cat, state.e_val = src, tgt, cat, val
