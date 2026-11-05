"""Detector 3: message dependency cycles and replies before their parents.

Algorithm: build a directed parent -> child graph, run one colouring DFS. A
back edge is a cycle (an impossible sequence). Otherwise the reversed DFS
finishing order is a topological order; each dependency edge is then checked
against the timestamps.
"""

from __future__ import annotations

from ..algorithms.topo import DependencyGraph
from ..models import Conflict, Evidence

ORDER_RULE = "A reply cannot be timestamped before the message it depends on."
CYCLE_RULE = "Messages cannot depend on each other in a cycle."


def detect(records: list[Evidence]) -> list[Conflict]:
    """Find impossible message orders and dependency cycles.

    Inputs: all evidence records.
    Outputs: one cycle conflict, or one conflict per reversed edge.
    Complexity: O(V + E) time and space.
    """
    messages = [record for record in records if record.record_type == "message"]
    by_id = {message.id: message for message in messages}
    graph = DependencyGraph()
    for message in messages:
        graph.add_node(message.id)
    for message in messages:
        if message.depends_on and message.depends_on in by_id:
            graph.add_edge(message.depends_on, message.id)

    cycle = graph.find_cycle()
    if cycle is not None:
        # A cycle makes every ordering impossible; report it once instead of
        # emitting a confusing burst of timestamp conflicts.
        return [_cycle_conflict(cycle, by_id)]

    order = graph.topological_order() or []
    positions = {node: index for index, node in enumerate(order)}
    conflicts: list[Conflict] = []
    for message in messages:
        parent = by_id.get(message.depends_on)
        if parent is None or message.timestamp >= parent.timestamp:
            continue
        conflicts.append(_order_conflict(parent, message, positions))
    return conflicts


def _cycle_conflict(
    cycle: list[str],
    by_id: dict[str, Evidence],
) -> Conflict:
    """Build one conflict describing a dependency cycle."""
    route = " -> ".join(cycle + [cycle[0]])
    return Conflict(
        kind="message_cycle",
        record_ids=tuple(cycle),
        rule_text=CYCLE_RULE,
        numbers={
            "cycle_length": len(cycle),
            "cycle": route,
        },
        explanation=(
            f"Messages form a dependency cycle: {route}. "
            "No timestamp order can satisfy every reply relation."
        ),
        severity=0.90,
    )


def _order_conflict(
    parent: Evidence,
    child: Evidence,
    positions: dict[str, int],
) -> Conflict:
    """Build one conflict for a reply timestamped before its parent."""
    seconds_early = (parent.timestamp - child.timestamp).total_seconds()
    return Conflict(
        kind="message_order",
        record_ids=(parent.id, child.id),
        rule_text=ORDER_RULE,
        numbers={
            "parent_time": parent.timestamp.isoformat(),
            "child_time": child.timestamp.isoformat(),
            "seconds_early": seconds_early,
            "parent_topological_index": positions.get(parent.id, -1),
            "child_topological_index": positions.get(child.id, -1),
        },
        explanation=(
            f"Message {child.id} replies to {parent.id}, but it is "
            f"timestamped {seconds_early:.0f} seconds earlier "
            f"({child.timestamp} before {parent.timestamp})."
        ),
        severity=0.80,
    )
