"""Shared data contracts, the fictional place map, and scoring helpers.

Nothing in this module imports Streamlit or pandas. The UI and the tests both
use these plain dataclasses, which keeps the algorithms easy to explain.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from datetime import datetime

from .algorithms.graph import WeightedGraph
from .algorithms.hash_table import HashTable
from .algorithms.sorting import lower_bound, merge_sort, upper_bound

RECORD_TYPES: tuple[str, ...] = (
    "state",
    "activity",
    "sighting",
    "message",
    "login",
    "claim",
)
DEVICE_STATES: tuple[str, ...] = ("ON", "OFF", "SLEEP")
CLAIM_TYPES: tuple[str, ...] = ("did_not_access",)
CONFLICT_KINDS: tuple[str, ...] = (
    "device_state",
    "location",
    "message_order",
    "message_cycle",
    "claim",
)
CSV_FIELDS: tuple[str, ...] = (
    "id",
    "timestamp",
    "record_type",
    "person",
    "device",
    "place",
    "state",
    "action",
    "account",
    "depends_on",
    "claim",
    "end_timestamp",
    "text",
)

EARTH_RADIUS_KM = 6371.0088
ASSUMED_SPEED_KMH = 30.0

# Ten fictional places around a fictional city. Coordinates are trusted
# constants: evidence rows carry a place name, never raw coordinates.
DEFAULT_PLACES: dict[str, tuple[float, float]] = {
    "Harbour": (51.500, -0.120),
    "Station": (51.505, -0.115),
    "Market": (51.510, -0.110),
    "Clinic": (51.515, -0.105),
    "Library": (51.520, -0.100),
    "Dock": (51.495, -0.095),
    "Park": (51.525, -0.115),
    "Museum": (51.505, -0.095),
    "Cafe": (51.515, -0.125),
    "Warehouse": (51.485, -0.110),
}

# Sixteen undirected roads. The Clinic-Park road deliberately takes 20 minutes,
# even though Clinic-Library-Park takes 12, so Dijkstra has something to prove.
# A weight of None means "derive it from the coordinates with haversine".
DEFAULT_ROADS: tuple[tuple[str, str, float | None], ...] = (
    ("Harbour", "Station", 6.0),
    ("Station", "Market", 5.0),
    ("Market", "Clinic", 6.0),
    ("Clinic", "Library", 5.0),
    ("Library", "Park", 7.0),
    ("Park", "Cafe", 8.0),
    ("Cafe", "Harbour", 9.0),
    ("Harbour", "Dock", 7.0),
    ("Dock", "Museum", 8.0),
    ("Museum", "Station", 6.0),
    ("Museum", "Market", 7.0),
    ("Clinic", "Cafe", 9.0),
    ("Dock", "Warehouse", 5.0),
    ("Warehouse", "Station", 12.0),
    ("Market", "Park", 11.0),
    ("Clinic", "Park", 20.0),
)


def haversine_km(
    lat_one: float,
    lon_one: float,
    lat_two: float,
    lon_two: float,
) -> float:
    """Return the great-circle distance between two coordinates in kilometres.

    Inputs: two latitude/longitude pairs in degrees.
    Outputs: a non-negative distance in kilometres.
    Complexity: O(1) time and space.
    """
    first_lat = math.radians(lat_one)
    second_lat = math.radians(lat_two)
    delta_lat = second_lat - first_lat
    delta_lon = math.radians(lon_two - lon_one)
    hav = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(first_lat) * math.cos(second_lat)
        * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(hav)))


def travel_minutes(
    places: dict[str, tuple[float, float]],
    first: str,
    second: str,
    speed_kmh: float = ASSUMED_SPEED_KMH,
) -> float:
    """Estimate road travel time between two known places.

    Inputs: the place table, two place names, and an assumed speed.
    Outputs: whole minutes, at least 2.
    Complexity: O(1) time and space.
    """
    lat_one, lon_one = places[first]
    lat_two, lon_two = places[second]
    hours = haversine_km(lat_one, lon_one, lat_two, lon_two) / speed_kmh
    return float(max(2, round(hours * 60.0)))


def build_place_graph(
    places: dict[str, tuple[float, float]] | None = None,
    roads: list[tuple[str, str, float | None]] | tuple[
        tuple[str, str, float | None], ...
    ] | None = None,
) -> WeightedGraph:
    """Build the weighted road graph from trusted place data.

    Inputs: an optional place table and road list; defaults are used when None.
    Outputs: a connected weighted graph whose weights are travel minutes.
    Complexity: O(V + E) time and space.
    Raises ValueError when a road names an unknown place.
    """
    place_table = dict(DEFAULT_PLACES if places is None else places)
    road_list = list(DEFAULT_ROADS if roads is None else roads)
    graph = WeightedGraph()
    for name in place_table:
        graph.add_node(name)
    for first, second, minutes in road_list:
        if first not in place_table or second not in place_table:
            raise ValueError(f"road references an unknown place: {first}-{second}")
        weight = (
            minutes
            if minutes is not None
            else travel_minutes(place_table, first, second)
        )
        graph.add_edge(first, second, weight)
    return graph


def is_connected(graph: WeightedGraph) -> bool:
    """Return True when every node can be reached from the first node.

    Inputs: a weighted graph.
    Outputs: a boolean.
    Complexity: O(V + E) time and space.
    """
    nodes = graph.nodes()
    if not nodes:
        return False
    seen: set[str] = set()
    stack = [nodes[0]]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for neighbour, _ in graph.neighbors(node):
            stack.append(neighbour)
    return len(seen) == len(nodes)


@dataclass(frozen=True)
class Evidence:
    """One normalized evidence record.

    Inputs: keyword fields described by the loader schema.
    Outputs: an immutable record safe to share between detectors.
    Complexity: O(1) space per record.
    """

    id: str
    timestamp: datetime
    record_type: str
    person: str = ""
    device: str = ""
    place: str = ""
    state: str = ""
    action: str = ""
    account: str = ""
    depends_on: str = ""
    claim: str = ""
    end_timestamp: datetime | None = None
    text: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return the record as string columns for display and CSV export.

        Inputs: none.
        Outputs: a dictionary keyed by ``CSV_FIELDS``.
        Complexity: O(1) time and space.
        """
        data: dict[str, str] = {}
        for name in CSV_FIELDS:
            value = getattr(self, name)
            if isinstance(value, datetime):
                data[name] = value.isoformat()
            elif value is None:
                data[name] = ""
            else:
                data[name] = str(value)
        return data


@dataclass(frozen=True)
class Conflict:
    """One contradiction found by a detector.

    Inputs: the kind, evidence record IDs, rule, numbers, explanation, severity.
    Outputs: an immutable conflict ready for display or scoring.
    Complexity: O(1) space per conflict.
    """

    kind: str
    record_ids: tuple[str, ...]
    rule_text: str
    numbers: dict[str, float | int | str]
    explanation: str
    severity: float

    @property
    def signature(self) -> str:
        """Return a stable identity used to deduplicate conflicts."""
        return self.kind + "|" + "|".join(self.record_ids)


@dataclass(frozen=True)
class GroundTruth:
    """A contradiction that the generator planted on purpose."""

    kind: str
    record_ids: tuple[str, ...]
    note: str = ""


@dataclass
class Case:
    """A full investigation: records, optional truth, and its place map."""

    name: str
    records: list[Evidence]
    ground_truth: list[GroundTruth] = field(default_factory=list)
    places: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict(DEFAULT_PLACES)
    )
    roads: list[tuple[str, str, float | None]] = field(
        default_factory=lambda: list(DEFAULT_ROADS)
    )

    def graph(self) -> WeightedGraph:
        """Build this case's road graph.

        Inputs: none.
        Outputs: a weighted graph.
        Complexity: O(V + E) time and space.
        """
        return build_place_graph(self.places, self.roads)


@dataclass(frozen=True)
class Score:
    """Precision/recall summary. ``available`` is False when no truth exists."""

    precision: float
    recall: float
    f1: float
    matched: int
    detected: int
    planted: int
    available: bool


def score_conflicts(
    conflicts: list[Conflict],
    truth: list[GroundTruth],
) -> Score:
    """Compare detected conflicts with planted ground truth.

    A truth entry matches a conflict of the same kind whose record IDs contain
    every truth ID. Each conflict is used at most once.

    Inputs: detected conflicts and ground-truth entries.
    Outputs: a ``Score``; ``available`` is False when truth is empty.
    Complexity: O(d * t) time for d detected and t truth entries.
    """
    if not truth:
        return Score(0.0, 0.0, 0.0, 0, len(conflicts), 0, False)
    used: set[int] = set()
    matched = 0
    for expected in truth:
        expected_ids = set(expected.record_ids)
        for index, found in enumerate(conflicts):
            if index in used or found.kind != expected.kind:
                continue
            if expected_ids.issubset(set(found.record_ids)):
                used.add(index)
                matched += 1
                break
    detected = len(conflicts)
    planted = len(truth)
    precision = matched / detected if detected else 0.0
    recall = matched / planted if planted else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return Score(precision, recall, f1, matched, detected, planted, True)


class CaseIndex:
    """Read-only query helpers built with our own data structures.

    Inputs: the records of one case.
    Outputs: indexes by person, device, and account, plus a sorted timeline.
    Complexity: O(n log n) build time, O(n) space.
    """

    def __init__(self, records: list[Evidence]) -> None:
        """Build the timeline and the three hash indexes.

        Inputs: ``records``.
        Outputs: none.
        Complexity: O(n log n) time, O(n) space.
        """
        self.records = merge_sort(records, key=lambda row: (row.timestamp, row.id))
        self.person_index: HashTable = HashTable()
        self.device_index: HashTable = HashTable()
        self.account_index: HashTable = HashTable()
        for record in self.records:
            _index_add(self.person_index, record.person, record)
            _index_add(self.device_index, record.device, record)
            _index_add(self.account_index, record.account, record)

    def people(self) -> list[str]:
        """Return non-empty person names in sorted order."""
        return merge_sort([name for name in self.person_index.keys() if name])

    def devices(self) -> list[str]:
        """Return non-empty device names in sorted order."""
        return merge_sort([name for name in self.device_index.keys() if name])

    def accounts(self) -> list[str]:
        """Return non-empty account names in sorted order."""
        return merge_sort([name for name in self.account_index.keys() if name])

    def for_person(self, person: str) -> list[Evidence]:
        """Return records indexed under ``person``."""
        return list(self.person_index.get(person, []))

    def for_device(self, device: str) -> list[Evidence]:
        """Return records indexed under ``device``."""
        return list(self.device_index.get(device, []))

    def for_account(self, account: str) -> list[Evidence]:
        """Return records indexed under ``account``."""
        return list(self.account_index.get(account, []))

    def in_range(self, start: datetime, end: datetime) -> list[Evidence]:
        """Return records whose timestamp is in the closed range.

        Inputs: start and end datetimes.
        Outputs: records in chronological order.
        Complexity: O(log n + k) time for k matches.
        """
        first = lower_bound(self.records, start, key=lambda row: row.timestamp)
        last = upper_bound(self.records, end, key=lambda row: row.timestamp)
        return self.records[first:last]

    def keyword(self, query: str) -> list[Evidence]:
        """Return records whose searchable text contains ``query``.

        Inputs: a query string.
        Outputs: matching records in chronological order.
        Complexity: O(n * m) time for m characters compared per record.
        """
        needle = query.strip().lower()
        if not needle:
            return list(self.records)
        matches: list[Evidence] = []
        for record in self.records:
            haystack = " ".join(
                [record.text, record.action, record.person, record.place]
            ).lower()
            if needle in haystack:
                matches.append(record)
        return matches


def _index_add(
    table: HashTable,
    key: str,
    record: Evidence,
) -> None:
    """Append a record to a hash-table bucket, creating the bucket if needed."""
    if not key:
        return
    bucket = table.get(key)
    if bucket is None:
        bucket = []
        table.put(key, bucket)
    bucket.append(record)


def case_to_csv(case: Case) -> str:
    """Serialize records to the upload CSV format.

    Inputs: a case.
    Outputs: a CSV string with a header row.
    Complexity: O(n) time and space.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in case.records:
        writer.writerow(record.to_dict())
    return buffer.getvalue()


def truth_to_json(case: Case) -> str:
    """Serialize planted ground truth for download.

    Inputs: a case.
    Outputs: a JSON string.
    Complexity: O(t) time and space for t truth entries.
    """
    payload = {
        "ground_truth": [
            {
                "kind": entry.kind,
                "record_ids": list(entry.record_ids),
                "note": entry.note,
            }
            for entry in case.ground_truth
        ]
    }
    return json.dumps(payload, indent=2)


def places_to_json(case: Case) -> str:
    """Serialize the place map and roads for download or re-upload.

    Inputs: a case.
    Outputs: a JSON string.
    Complexity: O(V + E) time and space.
    """
    places = {name: list(coords) for name, coords in case.places.items()}
    edges: list[list[object]] = []
    for first, second, minutes in case.roads:
        if minutes is None:
            edges.append([first, second])
        else:
            edges.append([first, second, minutes])
    return json.dumps({"places": places, "edges": edges}, indent=2)
