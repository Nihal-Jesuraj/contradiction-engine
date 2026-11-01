"""Difference-constraint graph and negative-cycle engines.

Encoding
--------
Each event is a variable x_e = its true timestamp in seconds.  Rules become
difference constraints:

    precedes / min_gap:  x_b - x_a >= delta   =>   x_a <= x_b - delta
                         edge b -> a, weight -delta
    max_gap:             x_b - x_a <= delta   =>   x_b <= x_a + delta
                         edge a -> b, weight  delta

The observed timestamps are pinned with a virtual origin node:

    origin -> e, weight  t_e        (x_e <= t_e)
    e -> origin, weight -t_e        (x_e >= t_e)

A negative cycle means no assignment of timestamps can satisfy every rule and
observation simultaneously.  Because every event is pinned to its observed
time, such a cycle is exactly a contradiction in the evidence.  We return the
event ids on the cycle for explainability.

All algorithms (Bellman-Ford, Floyd-Warshall, incremental re-check) are written
from scratch.  Complexity is documented on each method.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from .schema import NormalizedEvent, Rule

ORIGIN = "__ORIGIN__"
NEG_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    dest: str
    weight: float
    rule_id: str = ""
    kind: str = "observation"  # observation | rule


@dataclass(slots=True)
class CycleResult:
    has_cycle: bool
    cycle_nodes: list[str] = field(default_factory=list)
    cycle_event_ids: list[str] = field(default_factory=list)
    cycle_edges: list[Edge] = field(default_factory=list)
    total_weight: float = 0.0
    iterations: int = 0
    relaxations: int = 0
    nodes_examined: int = 0
    algorithm: str = "bellman_ford"

    def as_dict(self) -> dict[str, object]:
        return {
            "has_cycle": self.has_cycle,
            "cycle_event_ids": list(self.cycle_event_ids),
            "total_weight": round(self.total_weight, 6),
            "iterations": self.iterations,
            "relaxations": self.relaxations,
            "nodes_examined": self.nodes_examined,
            "algorithm": self.algorithm,
        }


def build_rule_edges(
    rules: Iterable[Rule],
    times: dict[str, float],
) -> tuple[set[str], list[Edge]]:
    """Translate rules into weighted directed edges.

    Only events referenced by at least one rule become graph nodes.  Events with
    no rule can never participate in a rule contradiction, so excluding them
    keeps the graph tiny even for million-record cases.

    O(r) time and space for r rules.
    """
    nodes: set[str] = set()
    edges: list[Edge] = []
    for rule in rules:
        if rule.event_a not in times or rule.event_b not in times:
            continue
        nodes.add(rule.event_a)
        nodes.add(rule.event_b)
        delta = float(rule.delta_s)
        if rule.type in ("precedes", "min_gap"):
            edges.append(
                Edge(rule.event_b, rule.event_a, -delta, rule.id, "rule")
            )
        elif rule.type == "max_gap":
            edges.append(
                Edge(rule.event_a, rule.event_b, delta, rule.id, "rule")
            )
    return nodes, edges


def observation_edges(nodes: Iterable[str], times: dict[str, float]) -> list[Edge]:
    """Pin every rule-event to its observed timestamp via the origin node.

    O(v) time and space for v graph nodes.
    """
    edges: list[Edge] = []
    for node in sorted(nodes):
        t = times[node]
        edges.append(Edge(ORIGIN, node, t))
        edges.append(Edge(node, ORIGIN, -t))
    return edges


def build_graph(
    rules: Iterable[Rule],
    times: dict[str, float],
) -> tuple[list[str], list[Edge], dict[str, list[Edge]]]:
    """Assemble nodes, edges, and adjacency for the constraint graph."""
    nodes, rule_edges = build_rule_edges(rules, times)
    edges = observation_edges(nodes, times) + rule_edges
    all_nodes = sorted(nodes)
    if all_nodes:
        all_nodes = [ORIGIN] + all_nodes
    adjacency: dict[str, list[Edge]] = {node: [] for node in all_nodes}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge)
        adjacency.setdefault(edge.dest, [])
    return all_nodes, edges, adjacency


def _trace_to_cycle(pred: dict[str, Edge], start: str, limit: int) -> list[str]:
    """Walk predecessor pointers until a node repeats.

    The first ``limit`` steps guarantee we are inside the cycle, not on the
    path leading into it.  O(V) time.
    """
    current = start
    for _ in range(limit):
        edge = pred.get(current)
        if edge is None:
            return []
        current = edge.source
    cycle: list[str] = []
    seen: dict[str, int] = {}
    while current not in seen:
        seen[current] = len(cycle)
        cycle.append(current)
        edge = pred.get(current)
        if edge is None:
            return []
        current = edge.source
    return cycle[seen[current]:]


def _cycle_edges(nodes: list[str], adjacency: dict[str, list[Edge]], pred: dict[str, Edge]) -> list[Edge]:
    """Pick one predecessor edge for each hop of a node cycle."""
    edges: list[Edge] = []
    for node in nodes:
        edge = pred.get(node)
        if edge is not None:
            edges.append(edge)
    return edges


def bellman_ford(
    rules: Iterable[Rule],
    times: dict[str, float],
) -> CycleResult:
    """Full Bellman-Ford from the virtual origin.

    O(V*E) time, O(V+E) space.  All graph nodes are reachable from the origin,
    so a single source is sufficient.  On the V-th relaxation we locate a
    relaxed node, walk predecessor pointers V steps to enter the cycle, then
    trace the repeated segment.  The returned ``cycle_event_ids`` excludes the
    synthetic origin.
    """
    nodes, edges, adjacency = build_graph(rules, times)
    if not nodes:
        return CycleResult(False, algorithm="bellman_ford")

    dist: dict[str, float] = {node: math.inf for node in nodes}
    dist[ORIGIN] = 0.0
    pred: dict[str, Edge] = {}
    relaxations = 0
    updated_node: str | None = None

    for iteration in range(len(nodes)):
        updated_node = None
        for source in nodes:
            base = dist[source]
            if base == math.inf:
                continue
            for edge in adjacency.get(source, ()):
                candidate = base + edge.weight
                if candidate < dist[edge.dest] - NEG_EPS:
                    dist[edge.dest] = candidate
                    pred[edge.dest] = edge
                    updated_node = edge.dest
                    relaxations += 1
        if updated_node is None:
            return CycleResult(
                False,
                iterations=iteration + 1,
                relaxations=relaxations,
                nodes_examined=len(nodes),
                algorithm="bellman_ford",
            )

    if updated_node is None:  # pragma: no cover - defensive
        return CycleResult(False, algorithm="bellman_ford")

    cycle = _trace_to_cycle(pred, updated_node, len(nodes))
    if not cycle:
        return CycleResult(False, algorithm="bellman_ford")
    cycle_edges = _cycle_edges(cycle, adjacency, pred)
    total = sum(edge.weight for edge in cycle_edges)
    event_ids = [node for node in cycle if node != ORIGIN]
    return CycleResult(
        True,
        cycle_nodes=cycle,
        cycle_event_ids=event_ids,
        cycle_edges=cycle_edges,
        total_weight=total,
        iterations=len(nodes),
        relaxations=relaxations,
        nodes_examined=len(nodes),
        algorithm="bellman_ford",
    )


def floyd_warshall(
    rules: Iterable[Rule],
    times: dict[str, float],
) -> CycleResult:
    """All-pairs shortest paths baseline and negative-cycle extraction.

    O(V^3) time, O(V^2) space.  Used as the correctness baseline for the
    incremental engine and capped in benchmarks where cubic growth is
    physically infeasible.  A negative diagonal ``dist[i][i] < 0`` is a cycle;
    the ``next`` matrix reconstructs its hops.
    """
    nodes, _edges, _adjacency = build_graph(rules, times)
    n = len(nodes)
    if n == 0:
        return CycleResult(False, algorithm="floyd_warshall")

    index = {node: i for i, node in enumerate(nodes)}
    inf = math.inf
    dist = [[inf] * n for _ in range(n)]
    nxt = [[-1] * n for _ in range(n)]
    for i in range(n):
        dist[i][i] = 0.0
    for edge in _edges:
        i, j = index[edge.source], index[edge.dest]
        if edge.weight < dist[i][j]:
            dist[i][j] = edge.weight
            nxt[i][j] = j

    for k in range(n):
        dk = dist[k]
        for i in range(n):
            dik = dist[i][k]
            if dik == inf:
                continue
            row = dist[i]
            for j in range(n):
                candidate = dik + dk[j]
                if candidate < row[j] - NEG_EPS:
                    row[j] = candidate
                    nxt[i][j] = nxt[i][k] if i != k else nxt[k][j]

    # A negative diagonal means a negative cycle.  With the virtual origin the
    # origin's diagonal is always negative when any contradiction exists, and
    # starting there avoids picking a vertex merely *downstream* of the cycle.
    cycle_start = None
    best = -NEG_EPS
    for i in range(n):
        if dist[i][i] < best:
            best = dist[i][i]
            cycle_start = i
    if cycle_start is None:
        return CycleResult(
            False,
            iterations=n,
            nodes_examined=n,
            algorithm="floyd_warshall",
        )
    if dist[0][0] < -NEG_EPS:
        cycle_start = 0

    # Follow successor pointers from the chosen vertex toward itself.  For a
    # vertex downstream of a negative cycle the walk eventually repeats a node
    # inside the cycle; extract the repeated segment.
    path: list[int] = []
    seen_at: dict[int, int] = {}
    current = cycle_start
    for _ in range(n + 1):
        if current in seen_at:
            break
        seen_at[current] = len(path)
        path.append(current)
        hop = nxt[current][cycle_start]
        if hop == -1:
            break
        current = hop
    if current in seen_at:
        cycle_idx = path[seen_at[current]:]
    else:
        cycle_idx = path
    cycle_nodes = [nodes[i] for i in cycle_idx]
    event_ids = [node for node in cycle_nodes if node != ORIGIN]
    cycle_edges: list[Edge] = []
    total = 0.0
    for i, node in enumerate(cycle_nodes):
        target = cycle_nodes[(i + 1) % len(cycle_nodes)]
        # For 2-node and longer cycles, choose the minimum-weight direct edge.
        direct = [
            e
            for e in _edges
            if e.source == node and e.dest == target
        ]
        if direct:
            edge = min(direct, key=lambda e: e.weight)
            cycle_edges.append(edge)
            total += edge.weight
    return CycleResult(
        True,
        cycle_nodes=cycle_nodes,
        cycle_event_ids=event_ids,
        cycle_edges=cycle_edges,
        total_weight=total if cycle_edges else best,
        iterations=n,
        nodes_examined=n,
        algorithm="floyd_warshall",
    )


class IncrementalConstraintGraph:
    """Incremental difference-constraint graph.

    The novelty is the re-check: after adding edges we do **not** rerun a full
    Bellman-Ford over every node.  For each new edge u -> v we BFS the forward
    reachable set from v, then run relaxation only on that induced subgraph.
    A new negative cycle that uses the edge exists iff ``w(u,v) +
    shortest(v -> u) < 0`` (or a negative cycle is reachable from v).

    Cost per new edge: O(V' + V'E'), where V'/E' are the reachable subgraph
    sizes.  This is a strict subgraph of the full graph.  Worst case (every
    node reachable) matches full Bellman-Ford, which is documented honestly in
    README/viva notes.  Space: O(V+E) for the maintained graph.
    """

    def __init__(self, events: Iterable[NormalizedEvent] = ()) -> None:
        self.times: dict[str, float] = {event.id: event.ts for event in events}
        self.nodes: set[str] = set()
        self.edges: list[Edge] = []
        self.adjacency: dict[str, list[Edge]] = {ORIGIN: []}
        self._pinned: set[str] = set()
        self._rule_ids: set[str] = set()
        self._added_edges_since_check: list[Edge] = []
        self.rechecks = 0
        self.nodes_scanned_total = 0

    def add_events(self, events: Iterable[NormalizedEvent]) -> None:
        """Record observed timestamps; O(1) per event.

        Observation edges are materialized lazily when an event becomes a rule
        endpoint, preventing an unbounded graph from a million unused records.
        """
        for event in events:
            self.times[event.id] = event.ts

    def _pin(self, node: str) -> list[Edge]:
        if node in self._pinned:
            return []
        self._pinned.add(node)
        self.nodes.add(node)
        t = self.times[node]
        edges = [Edge(ORIGIN, node, t), Edge(node, ORIGIN, -t)]
        self._append_edges(edges)
        return edges

    def _append_edges(self, edges: Iterable[Edge]) -> None:
        for edge in edges:
            self.edges.append(edge)
            self.adjacency.setdefault(edge.source, []).append(edge)
            self.adjacency.setdefault(edge.dest, [])
            self._added_edges_since_check.append(edge)

    def add_rule(self, rule: Rule) -> list[Edge]:
        """Add one rule's constraint edge plus any newly-referenced endpoints.

        O(log V) expected for endpoint checks; actual checking is deferred.
        """
        if rule.id in self._rule_ids:
            return []
        if rule.event_a not in self.times or rule.event_b not in self.times:
            return []
        self._rule_ids.add(rule.id)
        added: list[Edge] = []
        added.extend(self._pin(rule.event_a))
        added.extend(self._pin(rule.event_b))
        delta = float(rule.delta_s)
        if rule.type in ("precedes", "min_gap"):
            edge = Edge(rule.event_b, rule.event_a, -delta, rule.id, "rule")
        else:
            edge = Edge(rule.event_a, rule.event_b, delta, rule.id, "rule")
        self._append_edges([edge])
        added.append(edge)
        return added

    def add_rules(self, rules: Iterable[Rule]) -> list[Edge]:
        added: list[Edge] = []
        for rule in rules:
            added.extend(self.add_rule(rule))
        return added

    def mark_clean(self) -> None:
        """Forget pending additions after a full graph build.

        The caller has already established a baseline with full Bellman-Ford;
        this avoids re-reporting every historical edge on the next incremental
        check.
        """
        self._added_edges_since_check = []

    def _reachable(self, start: str) -> set[str]:
        """Forward reachability in the CURRENT graph; O(V'+E')."""
        seen = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for edge in self.adjacency.get(node, ()):
                if edge.dest not in seen:
                    seen.add(edge.dest)
                    queue.append(edge.dest)
        return seen

    def _subgraph_bellman_ford(
        self,
        source: str,
        reachable: set[str],
    ) -> tuple[dict[str, float], dict[str, Edge], str | None, int]:
        """Relax only nodes reachable from ``source``.

        O(V'*E') worst case; O(V'+E') when no updates occur.
        Returns distances, predecessor edges, an updated node if a negative
        cycle is reachable, and the number of relaxations.
        """
        dist: dict[str, float] = {node: math.inf for node in reachable}
        dist[source] = 0.0
        pred: dict[str, Edge] = {}
        relaxations = 0
        for _ in range(len(reachable)):
            updated: str | None = None
            for node in reachable:
                base = dist[node]
                if base == math.inf:
                    continue
                for edge in self.adjacency.get(node, ()):
                    if edge.dest not in reachable:
                        continue
                    candidate = base + edge.weight
                    if candidate < dist[edge.dest] - NEG_EPS:
                        dist[edge.dest] = candidate
                        pred[edge.dest] = edge
                        updated = edge.dest
                        relaxations += 1
            if updated is None:
                return dist, pred, None, relaxations
        return dist, pred, updated if "updated" in locals() else None, relaxations

    def check_new_edges(self) -> list[CycleResult]:
        """Re-check only subgraphs reachable from newly added edges.

        For each new edge u -> v we examine reachable(v).  A negative cycle
        using the edge is reported if shortest(v -> u) + w < 0.  Duplicate
        cycles (same event set) are collapsed.

        O(sum over new edges of V'*E') time, O(V+E) extra space.
        """
        new_edges = self._added_edges_since_check
        self._added_edges_since_check = []
        if not new_edges:
            return []

        results: list[CycleResult] = []
        seen: set[tuple[str, ...]] = set()
        for new_edge in new_edges:
            # Only rule edges can complete a contradiction when observations
            # were already consistent.  Observation edges are still cheap to
            # skip deliberately.
            if new_edge.kind != "rule":
                continue
            self.rechecks += 1
            reachable = self._reachable(new_edge.dest)
            self.nodes_scanned_total += len(reachable)
            dist, pred, cycle_node, relaxations = self._subgraph_bellman_ford(
                new_edge.dest, reachable
            )

            if cycle_node is not None:
                cycle = _trace_to_cycle(pred, cycle_node, len(reachable))
                if cycle:
                    cycle_edges = _cycle_edges(cycle, self.adjacency, pred)
                    total = sum(edge.weight for edge in cycle_edges)
                    key = tuple(sorted(node for node in cycle if node != ORIGIN))
                    if key and key not in seen:
                        seen.add(key)
                        results.append(
                            CycleResult(
                                True,
                                cycle_nodes=cycle,
                                cycle_event_ids=list(key),
                                cycle_edges=cycle_edges,
                                total_weight=total,
                                iterations=len(reachable),
                                relaxations=relaxations,
                                nodes_examined=len(reachable),
                                algorithm="incremental",
                            )
                        )
                continue

            if new_edge.source in reachable:
                shortest = dist.get(new_edge.source, math.inf)
                if shortest + new_edge.weight < -NEG_EPS:
                    # Reconstruct v -> ... -> u and close with u -> v.
                    path: list[str] = [new_edge.source]
                    cur = new_edge.source
                    guard = 0
                    while cur != new_edge.dest and cur in pred and guard <= len(reachable):
                        edge = pred[cur]
                        cur = edge.source
                        path.append(cur)
                        guard += 1
                    path.reverse()  # v ... u
                    cycle = path
                    total = shortest + new_edge.weight
                    key = tuple(sorted(node for node in cycle if node != ORIGIN))
                    if key and key not in seen:
                        seen.add(key)
                        results.append(
                            CycleResult(
                                True,
                                cycle_nodes=cycle,
                                cycle_event_ids=list(key),
                                cycle_edges=[new_edge],
                                total_weight=total,
                                iterations=len(reachable),
                                relaxations=relaxations,
                                nodes_examined=len(reachable),
                                algorithm="incremental",
                            )
                        )
        return results

    def full_check(self) -> CycleResult:
        """Convenience baseline over the maintained graph; O(V*E)."""
        rules = [
            edge
            for edge in self.edges
            if edge.kind == "rule"
        ]
        # Reconstruct lightweight Rule objects for the standalone baseline.
        rebuilt: list[Rule] = []
        for edge in rules:
            if edge.weight <= 0:
                rebuilt.append(
                    Rule("min_gap", edge.dest, edge.source, -edge.weight, id=edge.rule_id)
                )
            else:
                rebuilt.append(
                    Rule("max_gap", edge.source, edge.dest, edge.weight, id=edge.rule_id)
                )
        return bellman_ford(rebuilt, self.times)

    @property
    def size(self) -> tuple[int, int]:
        return len(self.nodes), len(self.edges)
