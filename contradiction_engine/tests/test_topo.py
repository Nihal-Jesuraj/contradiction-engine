"""Tests for DFS cycle detection and topological ordering."""

from __future__ import annotations

from contradiction_engine.algorithms.topo import DependencyGraph


def test_empty_graph() -> None:
    """An empty graph has no cycle and an empty order."""
    graph = DependencyGraph()
    assert graph.find_cycle() is None
    assert graph.topological_order() == []


def test_chain_order() -> None:
    """A simple chain is returned parent first."""
    graph = DependencyGraph()
    graph.add_edge("A", "B")
    graph.add_edge("B", "C")
    assert graph.find_cycle() is None
    assert graph.topological_order() == ["A", "B", "C"]


def test_dag_order_is_valid() -> None:
    """Every parent appears before each of its children."""
    graph = DependencyGraph()
    edges = [("A", "C"), ("B", "C"), ("C", "D"), ("B", "D")]
    for parent, child in edges:
        graph.add_edge(parent, child)
    order = graph.topological_order()
    assert order is not None
    position = {node: index for index, node in enumerate(order)}
    for parent, child in edges:
        assert position[parent] < position[child]


def test_cycle_is_detected() -> None:
    """A three-node cycle is reported and has no topological order."""
    graph = DependencyGraph()
    graph.add_edge("A", "B")
    graph.add_edge("B", "C")
    graph.add_edge("C", "A")
    cycle = graph.find_cycle()
    assert cycle is not None
    assert set(cycle) == {"A", "B", "C"}
    assert graph.topological_order() is None


def test_self_loop_is_a_cycle() -> None:
    """A node that depends on itself is a one-node cycle."""
    graph = DependencyGraph()
    graph.add_edge("A", "A")
    assert graph.find_cycle() == ["A"]
    assert graph.topological_order() is None


def test_disconnected_nodes_are_included() -> None:
    """Nodes without edges still appear in the order."""
    graph = DependencyGraph()
    graph.add_edge("A", "B")
    graph.add_node("Z")
    order = graph.topological_order()
    assert order is not None
    assert set(order) == {"A", "B", "Z"}
