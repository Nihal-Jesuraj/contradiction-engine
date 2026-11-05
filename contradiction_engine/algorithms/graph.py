"""A weighted undirected graph with Dijkstra's shortest-path algorithm.

The graph is an explicit adjacency list. Edge weights are travel minutes and
must be finite and non-negative, which is what Dijkstra requires.
"""

from __future__ import annotations

import math

from .min_heap import MinHeap


class WeightedGraph:
    """An undirected graph stored as ``node -> [(neighbour, weight), ...]``.

    Inputs: none.
    Outputs: a mutable graph.
    Complexity: O(V + E) space for V nodes and E edges.
    """

    def __init__(self) -> None:
        """Create an empty graph.

        Inputs: none.
        Outputs: none.
        Complexity: O(1) time and space.
        """
        self._adjacency: dict[str, list[tuple[str, float]]] = {}

    def add_node(self, name: str) -> None:
        """Add a node if it is not already present.

        Inputs: ``name``.
        Outputs: none.
        Complexity: average O(1) time, O(1) space.
        """
        if name not in self._adjacency:
            self._adjacency[name] = []

    def add_edge(self, first: str, second: str, weight: float) -> None:
        """Add an undirected road between two nodes.

        Inputs: two node names and a non-negative, finite weight.
        Outputs: none.
        Complexity: average O(1) time, O(1) space.
        Raises ValueError for a self-loop or an invalid weight.
        """
        if first == second:
            raise ValueError("self-loops are not supported")
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("edge weight must be finite and non-negative")
        self.add_node(first)
        self.add_node(second)
        self._adjacency[first].append((second, float(weight)))
        self._adjacency[second].append((first, float(weight)))

    def neighbors(self, node: str) -> list[tuple[str, float]]:
        """Return the adjacency list of a node.

        Inputs: ``node``.
        Outputs: a list of ``(neighbour, weight)`` pairs.
        Complexity: O(1) time to fetch, O(deg(node)) to copy.
        """
        return list(self._adjacency.get(node, []))

    def edge_weight(self, first: str, second: str) -> float | None:
        """Return the weight of the direct road, or None if there is none.

        Inputs: two node names.
        Outputs: a float weight or None.
        Complexity: O(deg(first)) time, O(1) space.
        """
        for neighbour, weight in self._adjacency.get(first, []):
            if neighbour == second:
                return weight
        return None

    def nodes(self) -> list[str]:
        """Return all node names in insertion order.

        Inputs: none.
        Outputs: a new list of names.
        Complexity: O(V) time and space.
        """
        return list(self._adjacency.keys())

    def has_node(self, name: str) -> bool:
        """Return True when the node exists."""
        return name in self._adjacency

    def dijkstra(self, source: str) -> tuple[dict[str, float], dict[str, str]]:
        """Compute shortest distances from ``source`` to every reachable node.

        Inputs: ``source``, a node in the graph.
        Outputs: ``(distances, previous)`` where ``previous`` maps a node to
        the node before it on the shortest path. Unreachable nodes are absent
        from both dictionaries.
        Complexity: O((V + E) log V) time, O(V + E) space.
        """
        if source not in self._adjacency:
            raise ValueError(f"unknown source node: {source}")
        distances: dict[str, float] = {source: 0.0}
        previous: dict[str, str] = {}
        settled: set[str] = set()
        heap: MinHeap[str] = MinHeap()
        heap.push(0.0, source)

        while not heap.is_empty():
            node = heap.pop()
            if node in settled:
                # A stale duplicate entry from lazy deletion; the smaller
                # distance was already finalised.
                continue
            settled.add(node)
            for neighbour, weight in self._adjacency[node]:
                candidate = distances[node] + weight
                if candidate < distances.get(neighbour, math.inf):
                    distances[neighbour] = candidate
                    previous[neighbour] = node
                    heap.push(candidate, neighbour)
        return distances, previous

    def shortest_path(
        self,
        previous: dict[str, str],
        source: str,
        target: str,
    ) -> list[str]:
        """Reconstruct a path from a ``previous`` map.

        Inputs: the map returned by ``dijkstra``, a source, and a target.
        Outputs: the node list, or an empty list when no path was found.
        Complexity: O(V) time and space.
        """
        if source == target:
            return [source]
        if target not in previous:
            return []
        path = [target]
        node = target
        while node != source:
            node = previous[node]
            path.append(node)
            if len(path) > len(previous) + 1:
                return []
        path.reverse()
        return path
