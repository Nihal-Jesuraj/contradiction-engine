"""Tests for the BFS entity graph and its DOT export."""

from __future__ import annotations

from contradiction_engine.algorithms.evidence_graph import EvidenceGraph


def build_chain() -> EvidenceGraph:
    """Build person -> device -> account plus a detached place."""
    graph = EvidenceGraph()
    graph.link("person:P1", "device:D1")
    graph.link("device:D1", "account:A1")
    graph.link("person:P1", "place:Harbour")
    return graph


def test_empty_graph() -> None:
    graph = EvidenceGraph()
    assert graph.nodes() == []
    assert graph.related("person:P1") == {}
    assert graph.neighbors("missing") == []


def test_links_are_undirected_and_self_links_are_ignored() -> None:
    graph = EvidenceGraph()
    graph.link("person:P1", "device:D1")
    graph.link("person:P1", "person:P1")
    assert graph.neighbors("person:P1") == ["device:D1"]
    assert graph.neighbors("device:D1") == ["person:P1"]
    assert len(graph.nodes()) == 2


def test_related_respects_depth() -> None:
    graph = build_chain()
    assert graph.related("person:P1", 1) == {
        "device:D1": 1,
        "place:Harbour": 1,
    }
    two_hops = graph.related("person:P1", 2)
    assert two_hops["account:A1"] == 2
    assert "person:P1" not in two_hops


def test_depth_zero_and_unknown_start_are_empty() -> None:
    graph = build_chain()
    assert graph.related("person:P1", 0) == {}
    assert graph.related("person:Nobody", 2) == {}


def test_cycle_does_not_loop_forever() -> None:
    graph = EvidenceGraph()
    graph.link("person:P1", "device:D1")
    graph.link("device:D1", "account:A1")
    graph.link("account:A1", "person:P1")
    assert set(graph.related("person:P1", 2)) == {"device:D1", "account:A1"}


def test_to_dot_contains_nodes_and_edges() -> None:
    dot = build_chain().to_dot()
    assert dot.startswith("graph Evidence {")
    assert '"person:P1"' in dot
    assert '"account:A1" -- "device:D1"' in dot
    assert "shape=box" in dot


def test_to_dot_highlights_hops() -> None:
    graph = build_chain()
    dot = graph.to_dot({"person:P1": 0, "device:D1": 1, "account:A1": 2})
    assert 'fillcolor="#d62728"' in dot
    assert 'fillcolor="#ff7f0e"' in dot
    assert 'fillcolor="#2ca02c"' in dot
    assert 'fillcolor="#eeeeee"' in dot


def test_to_dot_escapes_quotes_and_backslashes() -> None:
    """Uploaded entity names cannot break out of a DOT string literal."""
    graph = EvidenceGraph()
    graph.link('person:P"1', "place:C\\D")
    dot = graph.to_dot()
    assert r'"person:P\"1"' in dot
    assert r'"place:C\\D"' in dot
