"""Step 4: cycles on pairs, found with an ITERATIVE depth-first search (100k nodes are fine)."""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sankey_studio.errors import GraphBuildError
from sankey_studio.graph.pairs import adjacency, apply_pair_selection
from sankey_studio.models.base import INDEX_TYPECODE

if TYPE_CHECKING:
    from sankey_studio.graph.state import BuildState

WHITE, GRAY, BLACK = 0, 1, 2
#: Nodes named in the error message; longer cycles are cut with an ellipsis.
CYCLE_NAMES_SHOWN = 8


@dataclass(slots=True)
class CycleScan:
    """Result of one search: every back-edge (a pair that closes a cycle) and one example."""

    back_edges: list[int] = field(default_factory=list)
    first_cycle: list[int] = field(default_factory=list)


class Walker:
    """Depth-first search from every unvisited node, in node order, over pairs in pair order."""

    def __init__(self, state: BuildState) -> None:
        self._p_tgt = state.p_tgt
        self._start, self._edges = adjacency(state.n_nodes, state.p_src)
        self._cursor = array(INDEX_TYPECODE, self._start[:-1])
        self._color = bytearray(state.n_nodes)
        self.scan = CycleScan()

    def run(self) -> CycleScan:
        for root in range(len(self._color)):
            if self._color[root] == WHITE:
                self._explore(root)
        return self.scan

    def _explore(self, root: int) -> None:
        stack: list[int] = []
        self._push(stack, root)
        while stack:
            edge = self._next_edge(stack[-1])
            if edge is not None:
                self._follow(stack, edge)
            else:
                self._color[stack.pop()] = BLACK

    def _push(self, stack: list[int], node: int) -> None:
        self._color[node] = GRAY
        stack.append(node)

    def _next_edge(self, node: int) -> int | None:
        """The next unused pair leaving ``node``, or ``None`` once all of them were followed."""
        cursor = self._cursor[node]
        if cursor >= self._start[node + 1]:
            return None
        self._cursor[node] = cursor + 1
        return self._edges[cursor]

    def _follow(self, stack: list[int], edge: int) -> None:
        target = self._p_tgt[edge]
        color = self._color[target]
        if color == WHITE:
            self._push(stack, target)
        elif color == GRAY:
            self.scan.back_edges.append(edge)
            if not self.scan.first_cycle:
                self.scan.first_cycle = stack[stack.index(target) :]


def cycle_message(names: list[str], cycle: list[int]) -> str:
    """``A -> B -> A``; a cycle of more than 8 nodes shows the first 8 and its size."""
    shown = [names[node] for node in cycle[:CYCLE_NAMES_SHOWN]]
    if len(cycle) > CYCLE_NAMES_SHOWN:
        path = " -> ".join(shown) + f" -> ... ({len(cycle)} nodes)"
    else:
        path = " -> ".join([*shown, shown[0]])
    return (
        f"The links form a cycle: {path}. Set on_cycle to 'break' to drop the links that close it"
    )


def break_cycles(state: BuildState) -> None:
    """``on_cycle="error"``: raise; ``"break"``: drop the back-edges and warn with the count."""
    scan = Walker(state).run()
    if not scan.back_edges:
        return
    if state.transform.on_cycle == "error":
        raise GraphBuildError(cycle_message(state.names, scan.first_cycle))
    closing = set(scan.back_edges)
    apply_pair_selection(state, [p for p in range(state.n_pairs) if p not in closing])
    state.warnings.append(f"Removed {len(closing)} link(s) that closed a cycle")
