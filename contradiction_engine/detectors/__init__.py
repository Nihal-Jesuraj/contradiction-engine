"""Aggregate every detector and remove duplicate conflicts.

The detectors only ever see ``case.records`` (and, for the two location-aware
detectors, a place graph). Ground truth is never passed in; scoring happens
afterwards in ``models.score_conflicts``.
"""

from __future__ import annotations

from ..algorithms.graph import WeightedGraph
from ..algorithms.hash_table import HashTable
from ..algorithms.sorting import merge_sort
from ..models import Conflict, Evidence, build_place_graph
from . import chronology, claims, device_state, location, location_claims


def run_all_detectors(
    records: list[Evidence],
    graph: WeightedGraph | None = None,
) -> list[Conflict]:
    """Run every detector, deduplicate, and return a stable order.

    Inputs: evidence records and an optional place graph.
    Outputs: conflicts sorted by kind, then by their first record ID.
    Complexity: O(n log n) time dominated by sorting, O(n) space.
    """
    road_graph = graph if graph is not None else build_place_graph()
    found: list[Conflict] = []
    found.extend(device_state.detect(records))
    found.extend(location.detect(records, road_graph))
    found.extend(location_claims.detect(records, road_graph))
    found.extend(chronology.detect(records))
    found.extend(claims.detect(records))

    seen: HashTable = HashTable()
    unique: list[Conflict] = []
    for conflict in found:
        if seen.contains(conflict.signature):
            continue
        seen.put(conflict.signature, True)
        unique.append(conflict)
    return merge_sort(
        unique,
        key=lambda conflict: (
            conflict.kind,
            conflict.record_ids[0] if conflict.record_ids else "",
        ),
    )
