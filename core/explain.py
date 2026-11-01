"""Breadth-first evidence explanation.

The constraint graph provides rule edges; we add temporal-adjacency edges for
the entities involved so a travel conflict can be walked even when no explicit
rule links the two records.  BFS is O(V_e + E_e + r) for the involved entities
and rules, with a hard visit cap to keep interactive requests bounded.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from .index import EventIndex
from .schema import Conflict, NormalizedEvent, Rule


def _temporal_adjacency(
    index: EventIndex,
    entities: set[str],
    window_s: float,
) -> tuple[dict[str, list[tuple[str, str]]], int]:
    """Connect consecutive records of the involved entities.

    O(sum e log e) to sort each entity + O(e) edges.  Only involved entities are
    expanded, so a million-record case does not flood an explain request.
    """
    adjacency: dict[str, list[tuple[str, str]]] = {}
    edges = 0
    for entity in entities:
        records = index.entity_events(entity)
        for left, right in zip(records, records[1:]):
            gap = right.ts - left.end_ts
            if gap <= window_s:
                adjacency.setdefault(left.id, []).append((right.id, "temporal next"))
                adjacency.setdefault(right.id, []).append((left.id, "temporal prev"))
                edges += 2
    return adjacency, edges


def _rule_adjacency(rules: list[Rule]) -> dict[str, list[tuple[str, str]]]:
    """Undirected view of rule edges for evidence interrogation. O(r)."""
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for rule in rules:
        label = f"{rule.type.upper()} {rule.delta_s:g}s"
        adjacency.setdefault(rule.event_a, []).append((rule.event_b, label))
        adjacency.setdefault(rule.event_b, []).append((rule.event_a, label))
    return adjacency


def _record(event: NormalizedEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "timestamp": event.timestamp,
        "entity": event.entity,
        "source": event.source,
        "device_id": event.device_id,
        "action": event.action,
        "duration_s": event.duration_s,
        "lat": event.lat,
        "lon": event.lon,
        "reliability": event.reliability,
    }


def _fallback_chain(
    conflict: Conflict, index: EventIndex
) -> list[tuple[NormalizedEvent, str]]:
    records = [event for event in (index.get(i) for i in conflict.event_ids) if event]
    records.sort(key=lambda e: (e.ts, e.id))
    return [(event, "ordered record") for event in records]


def explain_conflict(
    conflict: Conflict,
    index: EventIndex,
    rules: list[Rule],
    *,
    temporal_window_s: float = 1800.0,
    max_visited: int = 600,
) -> dict[str, Any]:
    """BFS the evidence/constraint graph and return an ordered chain.

    Start at the first event id on the conflict and search for the last id.
    A direct rule edge or temporal-adjacency edge yields a 2-3 hop explanation;
    otherwise the sorted records are returned as a conservative fallback.
    """
    # Resolve only the affected records; never materialize a million-event map
    # just to explain one conflict.
    involved = [event for event in (index.get(i) for i in conflict.event_ids) if event]
    if not involved:
        return {
            "conflict": conflict.to_dict(),
            "chain": [],
            "narrative": "No records remain for this conflict.",
            "nodes_visited": 0,
        }

    start = conflict.event_ids[0]
    target = conflict.event_ids[-1] if len(conflict.event_ids) > 1 else conflict.event_ids[0]
    entities = {event.entity for event in involved}
    temporal, temporal_edges = _temporal_adjacency(index, entities, temporal_window_s)
    ruled = _rule_adjacency(rules)

    adjacency: dict[str, list[tuple[str, str]]] = {}
    for source, edges in temporal.items():
        adjacency.setdefault(source, []).extend(edges)
    for source, edges in ruled.items():
        adjacency.setdefault(source, []).extend(edges)

    previous: dict[str, tuple[str | None, str]] = {start: (None, "origin")}
    queue: deque[str] = deque([start])
    visited = 0
    found = start == target
    while queue and visited < max_visited and not found:
        node = queue.popleft()
        visited += 1
        for neighbour, label in adjacency.get(node, ()):
            if neighbour in previous:
                continue
            previous[neighbour] = (node, label)
            if neighbour == target:
                found = True
                break
            queue.append(neighbour)

    chain: list[tuple[NormalizedEvent, str]] = []
    if found:
        cursor = target
        hops: list[tuple[NormalizedEvent, str]] = []
        while cursor != start:
            parent, label = previous[cursor]
            event = index.get(cursor)
            if event is not None:
                hops.append((event, label))
            if parent is None:
                break
            cursor = parent
        origin_event = index.get(start)
        if origin_event is not None:
            hops.append((origin_event, "origin"))
        hops.reverse()
        chain = hops
    if not chain:
        chain = _fallback_chain(conflict, index)

    chain_payload: list[dict[str, Any]] = []
    for step, (event, via) in enumerate(chain, start=1):
        chain_payload.append(
            {
                "step": step,
                "via": via,
                "record": _record(event),
            }
        )

    if len(chain_payload) > 1:
        first = chain_payload[0]["record"]
        last = chain_payload[-1]["record"]
        narrative = (
            f"{first['entity']} evidence {first['id']} ({first['source'].upper()}) is "
            f"linked by {len(chain_payload) - 1} hop(s) to {last['id']} "
            f"({last['source'].upper()}). {conflict.detail}"
        )
    else:
        narrative = (
            f"Single-record device-level finding for {conflict.device_id or 'unknown device'}. "
            f"{conflict.detail}"
        )

    return {
        "conflict": conflict.to_dict(),
        "chain": chain_payload,
        "narrative": narrative,
        "nodes_visited": visited,
        "edges_examined": temporal_edges + len(rules) * 2,
    }
