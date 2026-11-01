"""Conflict ranking with a hand-written bounded min-heap.

Confidence blends three independent signals:

    reliability   0.45 * mean(record reliability, source prior)
    severity      0.30 * detector severity
    corroboration 0.25 * min(1, independent source count / 5)

The heap keeps only the best k conflicts while streaming candidates:
O(c log k) time and O(k) space for c candidates.  A full sort would be
O(c log c); for dashboards k is tiny.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .index import EventIndex
from .schema import SOURCE_RELIABILITY, Conflict, NormalizedEvent


@dataclass(slots=True)
class RankedEntry:
    confidence: float
    severity: float
    conflict_id: str
    conflict: Conflict

    def order_key(self) -> tuple[float, float, str]:
        return (self.confidence, self.severity, self.conflict_id)


class ConflictMinHeap:
    """Fixed-capacity min-heap containing the strongest k entries seen.

    The root is the *weakest* retained conflict, making replacement O(log k).
    Ties are deterministic via conflict id.  Hand-written binary heap.
    """

    __slots__ = ("capacity", "_items")

    def __init__(self, capacity: int) -> None:
        self.capacity = max(0, capacity)
        self._items: list[RankedEntry] = []

    def __len__(self) -> int:
        return len(self._items)

    def push(self, conflict: Conflict) -> bool:
        entry = RankedEntry(
            confidence=conflict.confidence,
            severity=conflict.severity,
            conflict_id=conflict.id,
            conflict=conflict,
        )
        if self.capacity == 0:
            return False
        if len(self._items) < self.capacity:
            self._items.append(entry)
            self._sift_up(len(self._items) - 1)
            return True
        if entry.order_key() <= self._items[0].order_key():
            return False
        self._items[0] = entry
        self._sift_down(0)
        return True

    def _sift_up(self, index: int) -> None:
        while index > 0:
            parent = (index - 1) // 2
            if self._items[parent].order_key() <= self._items[index].order_key():
                break
            self._items[parent], self._items[index] = (
                self._items[index],
                self._items[parent],
            )
            index = parent

    def _sift_down(self, index: int) -> None:
        size = len(self._items)
        while True:
            left = 2 * index + 1
            right = left + 1
            smallest = index
            if left < size and self._items[left].order_key() < self._items[smallest].order_key():
                smallest = left
            if right < size and self._items[right].order_key() < self._items[smallest].order_key():
                smallest = right
            if smallest == index:
                break
            self._items[index], self._items[smallest] = (
                self._items[smallest],
                self._items[index],
            )
            index = smallest

    def drain_descending(self) -> list[Conflict]:
        """Destructive sorted drain; O(k log k) time."""
        ordered: list[Conflict] = []
        while self._items:
            top = self._items[0]
            ordered.append(top.conflict)
            last = self._items.pop()
            if self._items:
                self._items[0] = last
                self._sift_down(0)
        ordered.reverse()
        return ordered

    def snapshot_descending(self) -> list[Conflict]:
        return [
            entry.conflict
            for entry in sorted(self._items, key=lambda e: e.order_key(), reverse=True)
        ]


def _event_reliability(event: NormalizedEvent) -> float:
    prior = SOURCE_RELIABILITY.get(event.source, 0.6)
    return max(0.0, min(1.0, 0.6 * event.reliability + 0.4 * prior))


def corroboration_count(
    conflict: Conflict,
    index: EventIndex,
    events_by_id: dict[str, NormalizedEvent],
    window_s: float = 300.0,
) -> tuple[int, tuple[str, ...]]:
    """Distinct independent sources around the conflict, capped by a window.

    Uses the sorted timeline for an O(log n + k) candidate range, then filters
    to the involved entity/entities.  Corroboration is a source count, not a
    raw record count, so five CCTV angles do not masquerade as five witnesses.
    """
    involved = [events_by_id[i] for i in conflict.event_ids if i in events_by_id]
    if not involved:
        return (len(conflict.sources), conflict.sources)
    entities = {event.entity for event in involved}
    lo = min(event.ts for event in involved) - window_s
    hi = max(event.end_ts for event in involved) + window_s
    sources: set[str] = set(conflict.sources)
    for event in involved:
        sources.add(event.source)
    for _ts, event_id in index.timeline.range(lo, hi):
        record = events_by_id.get(event_id)
        if record is not None and record.entity in entities:
            sources.add(record.source)
    return (len(sources), tuple(sorted(sources)))


def score_conflicts(
    conflicts: list[Conflict],
    events_by_id: dict[str, NormalizedEvent],
    index: EventIndex,
) -> list[Conflict]:
    """Attach confidence/corroboration in place and return the list.

    O(c * (log n + k)).  The weights sum to 1.0 and are exported so the
    UI/viva can explain every score.
    """
    for conflict in conflicts:
        involved = [events_by_id[i] for i in conflict.event_ids if i in events_by_id]
        if involved:
            reliability = sum(_event_reliability(e) for e in involved) / len(involved)
            conflict.sources = tuple(sorted({e.source for e in involved} | set(conflict.sources)))
        else:
            reliability = 0.5
        corroboration, sources = corroboration_count(conflict, index, events_by_id)
        conflict.corroboration = corroboration
        conflict.sources = sources
        corroboration_term = min(1.0, corroboration / 5.0)
        conflict.confidence = max(
            0.0,
            min(
                1.0,
                0.45 * reliability
                + 0.30 * conflict.severity
                + 0.25 * corroboration_term,
            ),
        )
    return conflicts


def top_k(
    conflicts: list[Conflict],
    k: int,
    events_by_id: dict[str, NormalizedEvent] | None = None,
    index: EventIndex | None = None,
) -> list[Conflict]:
    """Return the k highest-confidence conflicts via the bounded min-heap.

    If scoring was already done by the engine, pass no index and the existing
    confidence values are used.  O(c log k) time, O(k) space.
    """
    if events_by_id is not None and index is not None:
        score_conflicts(conflicts, events_by_id, index)
    heap = ConflictMinHeap(k)
    for conflict in conflicts:
        heap.push(conflict)
    return heap.drain_descending()
