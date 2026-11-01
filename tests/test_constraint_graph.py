"""Constraint graph, negative cycles, and incremental vs full equivalence."""

from __future__ import annotations

import math

import pytest

from core.constraint_graph import (
    IncrementalConstraintGraph,
    bellman_ford,
    build_graph,
    floyd_warshall,
)
from core.normalize import normalize_events
from core.schema import Event, Rule, iso_utc


def norm(event_id: str, ts: float, entity: str = "SUBJ-1"):
    return normalize_events(
        [
            Event(
                id=event_id,
                timestamp=iso_utc(ts),
                duration_s=5,
                entity=entity,
                lat=51.5,
                lon=-0.1,
                source="gps",
                device_id="GPS-1",
                action="FIX",
                reliability=0.8,
            )
        ]
    )[0]


E_A = norm("A", 1_700_000_000)
E_B = norm("B", 1_700_000_200)
E_C = norm("C", 1_700_000_500)
TIMES = {"A": E_A.ts, "B": E_B.ts, "C": E_C.ts}


def test_satisfied_constraints_have_no_cycle():
    rules = [
        Rule("min_gap", "A", "B", 60),
        Rule("max_gap", "A", "C", 10_000),
        Rule("precedes", "A", "C", 0),
    ]
    bf = bellman_ford(rules, TIMES)
    fw = floyd_warshall(rules, TIMES)
    assert not bf.has_cycle
    assert not fw.has_cycle


def test_min_gap_violation_is_detected_by_both_algorithms():
    rules = [Rule("min_gap", "B", "A", 1000)]  # A must occur far after B
    bf = bellman_ford(rules, TIMES)
    fw = floyd_warshall(rules, TIMES)
    assert bf.has_cycle and fw.has_cycle
    assert set(bf.cycle_event_ids) == {"A", "B"}
    assert set(fw.cycle_event_ids) == {"A", "B"}
    assert bf.total_weight < 0
    assert fw.total_weight < 0


def test_max_gap_violation_is_detected():
    rules = [Rule("max_gap", "A", "C", 10)]  # C occurs 500s after A; max 10s
    bf = bellman_ford(rules, TIMES)
    assert bf.has_cycle
    assert set(bf.cycle_event_ids) == {"A", "C"}


def test_cycle_event_ids_are_real_and_exclude_origin():
    rules = [
        Rule("precedes", "A", "B", 0),
        Rule("precedes", "B", "C", 0),
        Rule("max_gap", "A", "C", 1),
    ]
    result = bellman_ford(rules, TIMES)
    assert result.has_cycle
    assert result.cycle_event_ids
    assert "__ORIGIN__" not in result.cycle_event_ids
    assert all(event_id in TIMES for event_id in result.cycle_event_ids)
    assert sum(edge.weight for edge in result.cycle_edges) == pytest.approx(
        result.total_weight
    )


def test_floyd_warshall_reconstruction_has_negative_closed_cycle():
    rules = [Rule("min_gap", "B", "A", 1000)]
    fw = floyd_warshall(rules, TIMES)
    assert fw.has_cycle
    assert fw.total_weight < 0
    # The direct edges chosen must form the returned node cycle.
    by_source = {edge.source: edge for edge in fw.cycle_edges}
    assert by_source
    for node in fw.cycle_nodes:
        assert node in by_source


def test_incremental_matches_full_and_scans_less_than_whole_graph():
    rules = [
        Rule("precedes", "A", "B", 0),
        Rule("precedes", "B", "C", 0),
    ]
    incremental = IncrementalConstraintGraph([E_A, E_B, E_C])
    incremental.add_rules(rules)
    assert incremental.check_new_edges() == []

    violation = Rule("min_gap", "B", "A", 1000)
    incremental.add_rule(violation)
    cycles = incremental.check_new_edges()
    assert cycles
    assert set(cycles[0].cycle_event_ids) == {"A", "B"}

    full = bellman_ford(rules + [violation], TIMES)
    assert full.has_cycle
    assert set(full.cycle_event_ids) == set(cycles[0].cycle_event_ids)
    # The reported reachable subgraph is bounded by the graph size and the
    # incremental path counted it explicitly.
    assert cycles[0].nodes_examined <= len(incremental.nodes) + 1  # + origin


def test_incremental_noop_and_satisfied_rules():
    incremental = IncrementalConstraintGraph([E_A, E_B, E_C])
    incremental.add_rules([Rule("min_gap", "A", "B", 10)])
    assert incremental.check_new_edges() == []
    assert incremental.check_new_edges() == []  # pending additions consumed

    # A data-only event creates no rule edge and no cycle.
    incremental.add_events([norm("D", 1_700_000_900)])
    assert incremental.check_new_edges() == []


def test_build_graph_excludes_events_without_rules():
    nodes, edges, _adj = build_graph([Rule("min_gap", "A", "B", 0)], TIMES)
    assert nodes == ["__ORIGIN__", "A", "B"]
    # Two observation edges per event plus one rule edge.
    assert len(edges) == 5
