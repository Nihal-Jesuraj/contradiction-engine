"""Detector 2: impossible travel between consecutive sightings.

Algorithm: group sightings by person with our HashTable, merge-sort each
person's sightings, and compare the elapsed minutes between consecutive
sightings with the Dijkstra shortest route between their places. Dijkstra
results are cached per source place.

Checking only consecutive sightings is sound because shortest-path travel
times satisfy the triangle inequality: if a longer jump fits its time budget,
each consecutive leg also fits, and any leg that does not fit is caught.
"""

from __future__ import annotations

from ..algorithms.graph import WeightedGraph
from ..algorithms.hash_table import HashTable
from ..algorithms.sorting import merge_sort
from ..models import Conflict, Evidence, build_place_graph

RULE = "Consecutive sightings must allow at least the shortest road travel time."


def detect(
    records: list[Evidence],
    graph: WeightedGraph | None = None,
) -> list[Conflict]:
    """Find consecutive sightings that imply faster-than-possible travel.

    Inputs: all evidence records and an optional place graph.
    Outputs: one conflict per impossible hop.
    Complexity: O(n log n + V * (V + E) log V) time, O(n + V + E) space.
    """
    road_graph = graph if graph is not None else build_place_graph()
    sightings_by_person = _group_sightings(records)
    cache: dict[str, tuple[dict[str, float], dict[str, str]]] = {}
    conflicts: list[Conflict] = []
    for person in sightings_by_person.keys():
        sightings = merge_sort(
            sightings_by_person.get(person, []),
            key=lambda record: (record.timestamp, record.id),
        )
        for first, second in zip(sightings, sightings[1:]):
            conflict = _check_hop(road_graph, cache, first, second)
            if conflict is not None:
                conflicts.append(conflict)
    return conflicts


def _group_sightings(records: list[Evidence]) -> HashTable:
    """Bucket sighting records by person."""
    grouped: HashTable = HashTable()
    for record in records:
        if record.record_type != "sighting" or not record.person:
            continue
        bucket = grouped.get(record.person)
        if bucket is None:
            bucket = []
            grouped.put(record.person, bucket)
        bucket.append(record)
    return grouped


def _check_hop(
    graph: WeightedGraph,
    cache: dict[str, tuple[dict[str, float], dict[str, str]]],
    first: Evidence,
    second: Evidence,
) -> Conflict | None:
    """Return a conflict when a person outruns the shortest route."""
    if first.place == second.place:
        return None
    if not graph.has_node(first.place) or not graph.has_node(second.place):
        return None

    if first.place not in cache:
        cache[first.place] = graph.dijkstra(first.place)
    distances, previous = cache[first.place]
    required = distances.get(second.place)
    if required is None:
        return None

    elapsed = (
        second.timestamp - first.timestamp
    ).total_seconds() / 60.0
    if elapsed >= required:
        # Equal time is feasible, and tiny shortfalls are still reported:
        # nothing here discards small deltas.
        return None

    shortfall = required - elapsed
    path = graph.shortest_path(previous, first.place, second.place)
    return Conflict(
        kind="location",
        record_ids=(first.id, second.id),
        rule_text=RULE,
        numbers={
            "from_place": first.place,
            "to_place": second.place,
            "elapsed_minutes": round(elapsed, 2),
            "required_minutes": round(required, 2),
            "shortfall_minutes": round(shortfall, 2),
            "shortest_path": " -> ".join(path),
        },
        explanation=_explain(first, second, elapsed, required, path),
        severity=_severity(shortfall),
    )


def _explain(
    first: Evidence,
    second: Evidence,
    elapsed: float,
    required: float,
    path: list[str],
) -> str:
    """Build a plain-English explanation with the real numbers."""
    route = " -> ".join(path) if path else "no route"
    return (
        f"{second.person} was seen at {first.place} at {first.timestamp}, "
        f"then at {second.place} at {second.timestamp}. "
        f"The shortest route ({route}) needs {required:.1f} minutes, "
        f"but only {elapsed:.1f} minutes elapsed."
    )


def _severity(shortfall: float) -> float:
    """Map the size of the time shortfall to a small severity scale."""
    if shortfall >= 20:
        return 0.95
    if shortfall >= 5:
        return 0.85
    return 0.72
