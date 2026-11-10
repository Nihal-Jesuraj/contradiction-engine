"""Tests for the presentation-only Graphviz theme."""

from __future__ import annotations

from contradiction_engine.algorithms.evidence_graph import EvidenceGraph
from contradiction_engine.algorithms.graph import WeightedGraph
from ui.dot_theme import style_entity_dot, style_road_dot


def build_road() -> WeightedGraph:
    """Build a three-place road where the direct edge is slower."""
    graph = WeightedGraph()
    graph.add_edge("A", "B", 2)
    graph.add_edge("B", "C", 2)
    graph.add_edge("A", "C", 10)
    return graph


def test_road_dot_uses_dark_palette_and_minutes() -> None:
    """The road diagram is transparent, readable, and labels minutes."""
    dot = style_road_dot(build_road().to_dot(["A", "B", "C"]), ["A", "B", "C"])
    assert 'bgcolor="transparent"' in dot
    assert 'label="2 min"' in dot
    assert 'fontcolor="#E7EEF6"' in dot
    assert "#d62728" not in dot


def test_road_dot_highlights_the_route_in_accent() -> None:
    """The fastest route uses the UI accent, not the HIGH severity colour."""
    dot = style_road_dot(build_road().to_dot(["A", "B"]), ["A", "B"])
    assert 'color="#38BDF8", penwidth=2.4' in dot
    assert '"A" [label="A", color="#38BDF8", penwidth=2.2];' in dot
    assert '"B" [label="B", color="#38BDF8", penwidth=2.2];' in dot


def test_entity_dot_uses_rings_instead_of_bright_fills() -> None:
    """Entity nodes keep a dark fill and gain a hop-coloured ring."""
    graph = EvidenceGraph()
    graph.link("person:P1", "device:D1")
    graph.link("device:D1", "account:A1")
    dot = style_entity_dot(graph.to_dot({"person:P1": 0, "device:D1": 1}),
                           "person:P1")
    assert 'fillcolor="#17202B"' in dot
    assert 'color="#38BDF8"' in dot
    assert 'color="#A78BFA"' in dot
    assert "shape=box" in dot
    assert "#d62728" not in dot
    assert "#eeeeee" not in dot


def test_entity_dot_emphasises_the_start_ring() -> None:
    """The start entity gets a thicker accent ring than its neighbours."""
    graph = EvidenceGraph()
    graph.link("person:P1", "device:D1")
    dot = style_entity_dot(graph.to_dot({"person:P1": 0, "device:D1": 1}),
                           "person:P1")
    start_line = next(
        line for line in dot.splitlines() if '"person:P1"' in line
    )
    assert 'color="#38BDF8"' in start_line
    assert "penwidth=3" in start_line


def test_graph_colours_come_from_the_shared_palette() -> None:
    """Graph colours are read from the UI palette, not duplicated."""
    from ui import dot_theme
    from ui.theme import PALETTE

    assert dot_theme.ROUTE == PALETTE["route"]
    assert dot_theme.NODE_FILL == PALETTE["node"]
    assert dot_theme.EDGE_COLOR == PALETTE["edge"]
    assert dot_theme.NODE_BORDER == PALETTE["grid"]
    assert set(PALETTE["ring_1"] for _ in [0]) <= set(dot_theme._HOP_RINGS.values())
