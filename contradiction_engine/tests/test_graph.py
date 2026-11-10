"""Tests for the weighted graph and Dijkstra."""

from __future__ import annotations

import math

import pytest

from contradiction_engine.algorithms.graph import WeightedGraph


def build_triangle() -> WeightedGraph:
    """Build A-B-C where the direct A-C road is deliberately slow."""
    graph = WeightedGraph()
    graph.add_edge("A", "B", 2)
    graph.add_edge("B", "C", 2)
    graph.add_edge("A", "C", 10)
    return graph


def test_direct_edge_can_be_slower_than_two_hops() -> None:
    """Dijkstra must prefer A-B-C over the slower direct A-C road."""
    graph = build_triangle()
    distances, previous = graph.dijkstra("A")
    assert graph.edge_weight("A", "C") == 10
    assert distances["C"] == 4
    assert graph.shortest_path(previous, "A", "C") == ["A", "B", "C"]


def test_edges_are_undirected() -> None:
    """Distances work in both directions."""
    graph = build_triangle()
    distances, _ = graph.dijkstra("C")
    assert distances["A"] == 4


def test_unreachable_node_is_absent() -> None:
    """A node with no road is not reported as reachable."""
    graph = build_triangle()
    graph.add_node("Island")
    distances, previous = graph.dijkstra("A")
    assert "Island" not in distances
    assert graph.shortest_path(previous, "A", "Island") == []


def test_source_to_itself() -> None:
    """The shortest path from a node to itself is just that node."""
    graph = build_triangle()
    distances, previous = graph.dijkstra("A")
    assert distances["A"] == 0
    assert graph.shortest_path(previous, "A", "A") == ["A"]


def test_unknown_source_is_rejected() -> None:
    """Dijkstra cannot start from a node that does not exist."""
    graph = build_triangle()
    with pytest.raises(ValueError):
        graph.dijkstra("Nowhere")


def test_invalid_edges_are_rejected() -> None:
    """Self-loops and negative or non-finite weights are refused."""
    graph = WeightedGraph()
    with pytest.raises(ValueError):
        graph.add_edge("A", "A", 1)
    with pytest.raises(ValueError):
        graph.add_edge("A", "B", -1)
    with pytest.raises(ValueError):
        graph.add_edge("A", "B", math.inf)


def test_to_dot_marks_the_shortest_path() -> None:
    """DOT output includes every road and highlights the requested route."""
    graph = build_triangle()
    dot = graph.to_dot(["A", "B", "C"])
    assert dot.startswith("graph Map {")
    assert '"A" -- "B" [label="2m", color="#d62728", penwidth=2];' in dot
    assert '"A" -- "C" [label="10m"];' in dot


def test_to_dot_escapes_quotes_and_backslashes() -> None:
    """Uploaded names cannot break out of a DOT string literal."""
    graph = WeightedGraph()
    graph.add_edge('A"1', "B\\2", 1)
    dot = graph.to_dot(['A"1', "B\\2"])
    assert r'"A\"1" [label="A\"1"];' in dot
    assert r'"B\\2" [label="B\\2"];' in dot
    assert (
        r'"A\"1" -- "B\\2" [label="1m", color="#d62728", penwidth=2];'
        in dot
    )
