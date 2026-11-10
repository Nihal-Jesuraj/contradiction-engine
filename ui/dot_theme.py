"""Presentation-only Graphviz styling for the dark HUD.

The algorithm modules export structure-only DOT. This module rewrites that text
with fixed colours, fonts, and labels so the diagrams match the rest of the UI
without adding presentation concerns to the graph algorithms.
"""

from __future__ import annotations

import re

from .theme import PALETTE

FONT = "Inter, Helvetica, Arial, sans-serif"
TEXT = PALETTE["text"]
MUTED = PALETTE["muted"]
NODE_FILL = PALETTE["node"]
NODE_BORDER = PALETTE["grid"]
EDGE_COLOR = PALETTE["edge"]
ROUTE = PALETTE["route"]
ROUTE_LABEL = PALETTE["accent_hover"]
UNLINKED_RING = PALETTE["ring_far"]

GRAPH_ATTRS = (
    'graph [bgcolor="transparent", pad=0.25, margin=0, ranksep=0.55, '
    f'fontname="{FONT}", fontcolor="{TEXT}"];'
)
ROAD_NODE_ATTRS = (
    'node [shape=box, style="rounded,filled", '
    f'fillcolor="{NODE_FILL}", color="{NODE_BORDER}", fontcolor="{TEXT}", '
    f'fontname="{FONT}", fontsize=11, penwidth=1.2, margin="0.16,0.10"];'
)
ROAD_EDGE_ATTRS = (
    f'edge [color="{EDGE_COLOR}", fontcolor="{MUTED}", fontname="{FONT}", '
    "fontsize=10, penwidth=1.1];"
)
ENTITY_NODE_ATTRS = (
    'node [style="filled", '
    f'fillcolor="{NODE_FILL}", color="{NODE_BORDER}", fontcolor="{TEXT}", '
    f'fontname="{FONT}", fontsize=11, penwidth=1.2];'
)
ENTITY_EDGE_ATTRS = (
    f'edge [color="{EDGE_COLOR}", fontcolor="{MUTED}", fontname="{FONT}", '
    "fontsize=10, penwidth=1.1];"
)

# Structure-only fills from EvidenceGraph.to_dot -> hop ring colours.
_HOP_RINGS = {
    "#d62728": ROUTE,
    "#ff7f0e": PALETTE["ring_1"],
    "#2ca02c": PALETTE["ring_2"],
    "#1f77b4": PALETTE["ring_3"],
    "#eeeeee": UNLINKED_RING,
}
_MINUTES = re.compile(r'label="(-?\d+(?:\.\d+)?)m"')
_FILL = re.compile(r'fillcolor="(#[0-9a-fA-F]{6})"')
_ROUTE_EDGE = 'color="#d62728", penwidth=2'


def style_road_dot(dot: str, route: list[str] | None = None) -> str:
    """Return road-map DOT with the HUD palette and readable minutes.

    Inputs: DOT text from ``WeightedGraph.to_dot`` and the highlighted route.
    Outputs: styled DOT text for ``st.graphviz_chart``.
    Complexity: O(number of DOT characters and route nodes).
    """
    styled = _add_defaults(dot, (GRAPH_ATTRS, ROAD_NODE_ATTRS, ROAD_EDGE_ATTRS))
    styled = _MINUTES.sub(r'label="\1 min"', styled)
    styled = styled.replace(
        _ROUTE_EDGE,
        f'color="{ROUTE}", penwidth=2.4, fontcolor="{ROUTE_LABEL}"',
    )
    return _mark_route_nodes(styled, route or [])


def style_entity_dot(dot: str, start: str | None = None) -> str:
    """Return entity DOT with a dark fill and a coloured hop ring per node.

    Inputs: DOT text from ``EvidenceGraph.to_dot`` and the start entity.
    Outputs: styled DOT text for ``st.graphviz_chart``.
    Complexity: O(number of DOT characters).
    """
    styled = _add_defaults(dot, (GRAPH_ATTRS, ENTITY_NODE_ATTRS,
                                 ENTITY_EDGE_ATTRS))
    styled = _FILL.sub(_ring, styled)
    if start:
        prefix = f'  "{_dot_safe(start)}" ['
        styled = "\n".join(
            _emphasise(line, prefix) for line in styled.splitlines()
        )
    return styled


def _add_defaults(dot: str, attributes: tuple[str, ...]) -> str:
    """Insert graph, node, and edge defaults after the opening line."""
    head, separator, tail = dot.partition("\n")
    if not separator:
        return dot
    defaults = "\n".join(f"  {attribute}" for attribute in attributes)
    return "\n".join((head, defaults, tail))


def _mark_route_nodes(dot: str, route: list[str]) -> str:
    """Give the route's endpoint nodes an accent border."""
    prefixes = {f'  "{_dot_safe(name)}" [' for name in route}
    return "\n".join(
        _emphasise(line, next((p for p in prefixes if line.startswith(p)), ""))
        for line in dot.splitlines()
    )


def _emphasise(line: str, prefix: str) -> str:
    """Add or thicken an accent border on one matching node line."""
    if not prefix or not line.startswith(prefix) or not line.endswith("];"):
        return line
    if f'color="{ROUTE}"' in line:
        return line.replace("penwidth=2.2", "penwidth=3")
    return f'{line[:-2]}, color="{ROUTE}", penwidth=2.2];'


def _ring(match: re.Match[str]) -> str:
    """Replace a bright fill with a dark fill plus a coloured ring."""
    ring = _HOP_RINGS.get(match.group(1).lower(), UNLINKED_RING)
    return (
        f'fillcolor="{NODE_FILL}", color="{ring}", '
        "penwidth=2.2"
    )


def _dot_safe(text: str) -> str:
    """Escape characters that would break a DOT string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
