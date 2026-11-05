"""Breadth-first search over an undirected entity-relationship graph.

The Evidence Explorer builds one node per person, device, account, and place,
then links nodes that co-occur in a record. ``related`` answers "what is within
k hops of this entity?" with a hand-written FIFO queue.

Nodes are labelled ``"person:P01"``, ``"device:D01"``, ``"account:A01"``, or
``"place:Harbour"`` so the UI can pick a shape for each kind.
"""

from __future__ import annotations

from collections import deque

_SHAPES = {
    "person": "ellipse",
    "device": "box",
    "account": "diamond",
    "place": "house",
}
_HOP_COLORS = ("#d62728", "#ff7f0e", "#2ca02c", "#1f77b4")


class EvidenceGraph:
    """An undirected graph of people, devices, accounts, and places.

    Inputs: none.
    Outputs: a mutable graph.
    Complexity: O(V + E) space for V entities and E relationships.
    """

    def __init__(self) -> None:
        """Create an empty entity graph.

        Inputs: none.
        Outputs: none.
        Complexity: O(1) time and space.
        """
        self._adjacency: dict[str, list[str]] = {}

    def add_node(self, node: str) -> None:
        """Add a node if it is not already present.

        Inputs: ``node``, a labelled entity such as ``"person:P01"``.
        Outputs: none.
        Complexity: average O(1) time, O(1) space.
        """
        if node not in self._adjacency:
            self._adjacency[node] = []

    def link(self, first: str, second: str) -> None:
        """Add an undirected relationship between two entities.

        Inputs: two labelled entity names.
        Outputs: none.
        Complexity: O(deg(first)) time for the duplicate check, O(1) space.
        """
        if first == second:
            return
        self.add_node(first)
        self.add_node(second)
        if second not in self._adjacency[first]:
            self._adjacency[first].append(second)
        if first not in self._adjacency[second]:
            self._adjacency[second].append(first)

    def nodes(self) -> list[str]:
        """Return every entity in insertion order.

        Inputs: none.
        Outputs: a new list of labelled entity names.
        Complexity: O(V) time and space.
        """
        return list(self._adjacency.keys())

    def neighbors(self, node: str) -> list[str]:
        """Return the entities directly linked to ``node``.

        Inputs: ``node``.
        Outputs: a new list of neighbours, or an empty list when unknown.
        Complexity: O(deg(node)) time and space.
        """
        return list(self._adjacency.get(node, []))

    def related(self, start: str, depth: int = 2) -> dict[str, int]:
        """Return every entity within ``depth`` hops of ``start``.

        Inputs: a starting entity and a non-negative hop limit.
        Outputs: ``{entity: hops}`` excluding ``start`` itself. An unknown
        start or ``depth <= 0`` returns an empty dictionary.
        Complexity: O(V + E) time, O(V) space.
        """
        if start not in self._adjacency or depth <= 0:
            return {}
        seen: dict[str, int] = {start: 0}
        queue: deque[str] = deque([start])
        while queue:
            node = queue.popleft()
            hops = seen[node]
            if hops == depth:
                continue
            for neighbour in self._adjacency[node]:
                if neighbour not in seen:
                    seen[neighbour] = hops + 1
                    queue.append(neighbour)
        del seen[start]
        return seen

    def to_dot(self, highlight: dict[str, int] | None = None) -> str:
        """Render the graph as Graphviz DOT text.

        Inputs: an optional ``{entity: hops}`` map used to colour highlighted
        nodes by distance from the start entity.
        Outputs: DOT source accepted by ``st.graphviz_chart``.
        Complexity: O(V + E) time and space.
        """
        lines = ["graph Evidence {", "  overlap=false;"]
        for node in self._adjacency:
            kind, name = _split_node(node)
            attributes = [
                f'label="{_dot_safe(name)}"',
                f"shape={_SHAPES.get(kind, 'ellipse')}",
            ]
            colour = _hop_colour(highlight, node)
            if colour is not None:
                attributes.append(f'style="filled"')
                attributes.append(f'fillcolor="{colour}"')
            lines.append(f'  "{_dot_safe(node)}" [{", ".join(attributes)}];')
        for first in self._adjacency:
            for second in self._adjacency[first]:
                if first < second:
                    lines.append(
                        f'  "{_dot_safe(first)}" -- "{_dot_safe(second)}";'
                    )
        lines.append("}")
        return "\n".join(lines)


def _split_node(node: str) -> tuple[str, str]:
    """Split ``"person:P01"`` into its kind and label."""
    kind, separator, name = node.partition(":")
    if not separator:
        return "", node
    return kind, name


def _hop_colour(highlight: dict[str, int] | None, node: str) -> str | None:
    """Return the fill colour for a node, or None when it is not highlighted."""
    if highlight is None:
        return None
    hops = highlight.get(node)
    if hops is None:
        return "#eeeeee"
    return _HOP_COLORS[min(hops, len(_HOP_COLORS) - 1)]


def _dot_safe(text: str) -> str:
    """Escape characters that would break a DOT string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
