"""Detector 5: a claimed-location statement contradicted by a sighting.

Algorithm: group sightings by person with our HashTable, merge-sort each
person's sightings, use binary-search bounds for the closed claim window, and
run Dijkstra from the claimed place. The claim is read as "present at the
claimed place at both the start and end of the window". A sighting elsewhere is
a conflict only when the travel time from the claimed place does not fit before
the nearer window edge; otherwise the person could have been at the claimed
place at that edge and still reached the sighting. This is a both-edges check,
not a strictly continuous "throughout the window" check: a sighting at a
neighbouring place in the middle of a long window can pass.
"""

from __future__ import annotations

from ..algorithms.graph import WeightedGraph
from ..algorithms.hash_table import HashTable
from ..algorithms.sorting import lower_bound, merge_sort, upper_bound
from ..models import Conflict, Evidence, build_place_graph

RULE = (
    "A claimed presence at both edges of a window must leave enough time to "
    "travel between the claimed place and every place where the person is "
    "seen inside that window."
)


def detect(
    records: list[Evidence],
    graph: WeightedGraph | None = None,
) -> list[Conflict]:
    """Find claimed-location statements broken by a sighting elsewhere.

    Inputs: all evidence records and an optional place graph.
    Outputs: one conflict per irreconcilable claim/sighting pair.
    Complexity: O(n log n + V(V+E) log V) time, O(n + V + E) space.
    """
    road_graph = graph if graph is not None else build_place_graph()
    sightings_by_person = _group_sightings(records)
    cache: dict[str, tuple[dict[str, float], dict[str, str]]] = {}
    conflicts: list[Conflict] = []
    for claim in records:
        if claim.record_type != "claim" or claim.claim != "claimed_at":
            continue
        if claim.end_timestamp is None or not claim.place:
            continue
        if not road_graph.has_node(claim.place):
            continue
        sightings = merge_sort(
            sightings_by_person.get(claim.person, []),
            key=lambda record: (record.timestamp, record.id),
        )
        for sighting in _sightings_in_window(sightings, claim):
            conflict = _check(road_graph, cache, claim, sighting)
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


def _sightings_in_window(
    sightings: list[Evidence],
    claim: Evidence,
) -> list[Evidence]:
    """Return sightings inside the closed ``[start, end]`` claim window."""
    end = claim.end_timestamp
    if end is None:
        return []
    first = lower_bound(sightings, claim.timestamp,
                        key=lambda record: record.timestamp)
    last = upper_bound(sightings, end,
                       key=lambda record: record.timestamp)
    return sightings[first:last]


def _check(
    graph: WeightedGraph,
    cache: dict[str, tuple[dict[str, float], dict[str, str]]],
    claim: Evidence,
    sighting: Evidence,
) -> Conflict | None:
    """Return a conflict when the nearer edge leaves too little travel time."""
    if sighting.place == claim.place or not graph.has_node(sighting.place):
        return None
    required = _distances(graph, cache, claim.place).get(sighting.place)
    if required is None:
        return None
    before = (sighting.timestamp - claim.timestamp).total_seconds() / 60.0
    after = (claim.end_timestamp - sighting.timestamp).total_seconds() / 60.0
    margin = min(before, after)
    if margin >= required:
        return None
    return _conflict(graph, cache, claim, sighting, required, margin)


def _distances(
    graph: WeightedGraph,
    cache: dict[str, tuple[dict[str, float], dict[str, str]]],
    place: str,
) -> dict[str, float]:
    """Return cached Dijkstra distances from a claimed place."""
    if place not in cache:
        cache[place] = graph.dijkstra(place)
    return cache[place][0]


def _conflict(
    graph: WeightedGraph,
    cache: dict[str, tuple[dict[str, float], dict[str, str]]],
    claim: Evidence,
    sighting: Evidence,
    required: float,
    margin: float,
) -> Conflict:
    """Build one conflict for an irreconcilable claim and sighting."""
    previous = cache[claim.place][1]
    path = graph.shortest_path(previous, claim.place, sighting.place)
    shortfall = required - margin
    return Conflict(
        kind="claim_location",
        record_ids=(claim.id, sighting.id),
        rule_text=RULE,
        numbers={
            "claimed_place": claim.place,
            "seen_place": sighting.place,
            "window_start": claim.timestamp.isoformat(),
            "window_end": claim.end_timestamp.isoformat(),
            "seen_at": sighting.timestamp.isoformat(),
            "required_minutes": round(required, 2),
            "nearest_edge_minutes": round(margin, 2),
            "shortfall_minutes": round(shortfall, 2),
            "shortest_path": " -> ".join(path),
        },
        explanation=(
            f"{sighting.person or 'The subject'} claimed to be at "
            f"{claim.place} at both the start and end of the window "
            f"{claim.timestamp} to {claim.end_timestamp}, but was seen at "
            f"{sighting.place} at {sighting.timestamp}. "
            f"The shortest route ({' -> '.join(path)}) needs "
            f"{required:.1f} minutes, and only {margin:.1f} minutes separate "
            f"the sighting from the nearer edge of the claimed window."
        ),
        severity=_severity(shortfall),
    )


def _severity(shortfall: float) -> float:
    """Map the size of the time shortfall to a small severity scale."""
    if shortfall >= 10:
        return 0.88
    if shortfall >= 4:
        return 0.78
    return 0.68
