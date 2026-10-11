"""The mutable intermediate columns of ``build_graph``, passed between the build steps.

One small object instead of a long argument list (code cap: 4 parameters). Entries and pairs
are columnar ``array`` objects, never lists of tuples, so a 200k-link graph stays lean.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sankey_studio.models.base import INDEX_TYPECODE, VALUE_TYPECODE

if TYPE_CHECKING:
    from sankey_studio.models import TransformSpec
    from sankey_studio.sources.base import Diagnostics


def new_index_column() -> array[int]:
    return array(INDEX_TYPECODE)


def new_value_column() -> array[float]:
    return array(VALUE_TYPECODE)


@dataclass(slots=True)
class BuildState:
    """Everything the build steps share, filled in pipeline order.

    * interning: ``names`` (post-merge node names, first-appearance order = node colour slot),
      ``ids`` (raw or canonical name -> node id), ``agg`` (packed ``(s, t, c_data)`` key -> value),
      ``data_cats`` / ``data_cat_ids`` / ``data_cat_keys`` (category values found in the data);
    * entries: one row per final ``(source, target, category)`` combination
      (``e_src``/``e_tgt``/``e_cat``/``e_val``; ``e_cat`` is a slot into ``categories`` or -1);
    * pairs: one row per ``(source, target)`` pair, category agnostic (``p_src``/``p_tgt``/
      ``p_val``) and ``e_pair`` linking each entry to its pair (-1 once the pair was dropped);
    * results: ``layers`` per node, ``node_in``/``node_out`` from pair totals.
    """

    transform: TransformSpec
    diag: Diagnostics
    warnings: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    ids: dict[str, int] = field(default_factory=dict)
    agg: dict[int, float] = field(default_factory=dict)
    data_cats: list[str] = field(default_factory=list)
    data_cat_ids: dict[str, int] = field(default_factory=dict)
    data_cat_keys: dict[str, int] = field(default_factory=dict)
    unusable_categories: int = 0
    categories: list[str] = field(default_factory=list)
    e_src: array[int] = field(default_factory=new_index_column)
    e_tgt: array[int] = field(default_factory=new_index_column)
    e_cat: array[int] = field(default_factory=new_index_column)
    e_val: array[float] = field(default_factory=new_value_column)
    p_src: array[int] = field(default_factory=new_index_column)
    p_tgt: array[int] = field(default_factory=new_index_column)
    p_val: array[float] = field(default_factory=new_value_column)
    e_pair: array[int] = field(default_factory=new_index_column)
    layers: array[int] = field(default_factory=new_index_column)
    node_in: array[float] = field(default_factory=new_value_column)
    node_out: array[float] = field(default_factory=new_value_column)

    @property
    def n_nodes(self) -> int:
        return len(self.names)

    @property
    def n_pairs(self) -> int:
        return len(self.p_val)

    @property
    def n_entries(self) -> int:
        return len(self.e_val)
