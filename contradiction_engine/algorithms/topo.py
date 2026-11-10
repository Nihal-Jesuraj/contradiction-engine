"""DFS cycle detection and topological ordering for dependency graphs.

An edge ``parent -> child`` means "the parent must come before the child".
Messages use this graph: a reply points to the message it depends on.

We use one colouring DFS for both jobs: colours detect a back edge (a cycle),
and the reverse of the DFS finishing order is a valid topological order. Kahn's
algorithm would need a second pass and an indegree table for no extra insight.
"""

from __future__ import annotations

WHITE = 0
GRAY = 1
BLACK = 2


class DependencyGraph:
    """A directed graph with cycle detection and topological ordering.

    Inputs: none.
    Outputs: a mutable graph.
    Complexity: O(V + E) space.
    """

    def __init__(self) -> None:
        """Create an empty dependency graph.

        Inputs: none.
        Outputs: none.
        Complexity: O(1) time and space.
        """
        self._adjacency: dict[str, list[str]] = {}

    def add_node(self, name: str) -> None:
        """Add a node if it is not already present.

        Inputs: ``name``.
        Outputs: none.
        Complexity: average O(1) time, O(1) space.
        """
        if name not in self._adjacency:
            self._adjacency[name] = []

    def add_edge(self, parent: str, child: str) -> None:
        """Add a directed dependency ``parent -> child``.

        Inputs: two node names.
        Outputs: none.
        Complexity: average O(1) time, O(1) space.
        """
        self.add_node(parent)
        self.add_node(child)
        self._adjacency[parent].append(child)

    def nodes(self) -> list[str]:
        """Return all node names in insertion order.

        Inputs: none.
        Outputs: a new list of names.
        Complexity: O(V) time and space.
        """
        return list(self._adjacency.keys())

    def _traverse(self) -> tuple[list[str] | None, list[str]]:
        """Run the colouring DFS once.

        Inputs: none.
        Outputs: ``(cycle, postorder)``. ``cycle`` lists the nodes on a cycle
        without repeating the start; ``postorder`` is the DFS finishing order.
        Complexity: O(V + E) time and space.
        """
        colour: dict[str, int] = {}
        postorder: list[str] = []
        stack: list[str] = []
        cycle: list[str] | None = None

        def visit(node: str) -> None:
            nonlocal cycle
            colour[node] = GRAY
            stack.append(node)
            for neighbour in self._adjacency.get(node, []):
                state = colour.get(neighbour, WHITE)
                if state == WHITE:
                    visit(neighbour)
                    if cycle is not None:
                        return
                elif state == GRAY:
                    # A back edge closes a cycle. ``index`` is O(V), but it
                    # runs at most once, when the cycle is first found.
                    cycle = stack[stack.index(neighbour):]
                    return
            stack.pop()
            colour[node] = BLACK
            postorder.append(node)

        for node in self._adjacency:
            if colour.get(node, WHITE) == WHITE:
                visit(node)
                if cycle is not None:
                    return cycle, []
        return None, postorder

    def find_cycle(self) -> list[str] | None:
        """Return the nodes of one cycle, or None when the graph is acyclic.

        Inputs: none.
        Outputs: a list of node names forming a cycle, or None.
        Complexity: O(V + E) time and space.
        """
        cycle, _ = self._traverse()
        return cycle

    def topological_order(self) -> list[str] | None:
        """Return a parent-before-child order, or None if a cycle exists.

        Inputs: none.
        Outputs: a list of node names, or None.
        Complexity: O(V + E) time and space.
        """
        cycle, postorder = self._traverse()
        if cycle is not None:
            return None
        postorder.reverse()
        return postorder
