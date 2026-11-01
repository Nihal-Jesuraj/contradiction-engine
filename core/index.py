"""Hand-built temporal indexes.

Three structures cooperate:

* ``HashIndex``      entity -> ordered bucket of event ids (O(1) average lookup)
* ``SortedTimeline`` all events sorted by timestamp (O(log n) range search)
* ``IntervalTree``   an AVL tree augmented with subtree ``max_end``

ChronoClash keeps one interval tree per entity.  Simultaneity is only a
contradiction *within* an entity, so this avoids returning thousands of
irrelevant cross-entity overlaps while preserving the classic augmented
interval-tree operations.  A forest-wide query is still available.

No third-party tree/interval library is used.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections.abc import Iterable, Iterator
from typing import Any

from .schema import NormalizedEvent


class HashIndex:
    """Entity -> event-id buckets, plus reverse lookup.

    Average O(1) insert/lookup, O(k) removal from a bucket of size k.
    """

    __slots__ = ("_buckets", "_events")

    def __init__(self) -> None:
        self._buckets: dict[str, list[str]] = {}
        self._events: dict[str, NormalizedEvent] = {}

    def add(self, event: NormalizedEvent) -> None:
        if event.id in self._events:
            self.remove(event.id)
        self._events[event.id] = event
        self._buckets.setdefault(event.entity, []).append(event.id)

    def bulk_add(self, events: Iterable[NormalizedEvent]) -> None:
        for event in events:
            self._events[event.id] = event
            self._buckets.setdefault(event.entity, []).append(event.id)

    def remove(self, event_id: str) -> NormalizedEvent | None:
        event = self._events.pop(event_id, None)
        if event is None:
            return None
        bucket = self._buckets.get(event.entity)
        if bucket:
            try:
                bucket.remove(event_id)
            except ValueError:
                pass
            if not bucket:
                self._buckets.pop(event.entity, None)
        return event

    def get(self, event_id: str) -> NormalizedEvent | None:
        return self._events.get(event_id)

    def ids_for(self, entity: str) -> list[str]:
        return list(self._buckets.get(entity, ()))

    def events_for(self, entity: str) -> list[NormalizedEvent]:
        return [self._events[i] for i in self._buckets.get(entity, ())]

    @property
    def entities(self) -> list[str]:
        return list(self._buckets)

    def __len__(self) -> int:
        return len(self._events)

    def __contains__(self, event_id: object) -> bool:
        return event_id in self._events


class SortedTimeline:
    """A sorted array of ``(timestamp, event_id)`` pairs.

    Insert/delete are O(n) because elements shift; construction is O(n log n);
    range search is O(log n + k).  This is intentionally the simple baseline
    that the interval tree improves upon for overlap queries.
    """

    __slots__ = ("_items",)

    def __init__(self, events: Iterable[NormalizedEvent] | None = None) -> None:
        self._items: list[tuple[float, str]] = []
        if events is not None:
            self.rebuild(events)

    def rebuild(self, events: Iterable[NormalizedEvent]) -> None:
        self._items = sorted((e.ts, e.id) for e in events)

    def insert(self, event: NormalizedEvent) -> None:
        # insort keeps the array invariant but shifts O(n) trailing elements.
        insort(self._items, (event.ts, event.id))

    def remove(self, event: NormalizedEvent) -> None:
        key = (event.ts, event.id)
        index = bisect_left(self._items, key)
        if index < len(self._items) and self._items[index] == key:
            self._items.pop(index)

    def range(self, start: float, end: float) -> list[tuple[float, str]]:
        """Return pairs with ``start <= t < end``."""
        lo = bisect_left(self._items, (start, ""))
        hi = bisect_left(self._items, (end, ""))
        return self._items[lo:hi]

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[tuple[float, str]]:
        return iter(self._items)

    @property
    def first_ts(self) -> float | None:
        return self._items[0][0] if self._items else None

    @property
    def last_ts(self) -> float | None:
        return self._items[-1][0] if self._items else None

    def as_list(self) -> list[tuple[float, str]]:
        return list(self._items)


class _IntervalNode:
    __slots__ = ("event", "start", "end", "height", "max_end", "left", "right")

    def __init__(self, event: NormalizedEvent) -> None:
        self.event = event
        self.start = event.ts
        self.end = event.end_ts
        self.height = 1
        self.max_end = self.end
        self.left: _IntervalNode | None = None
        self.right: _IntervalNode | None = None

    @property
    def key(self) -> tuple[float, float, str]:
        return (self.start, self.end, self.event.id)


def _height(node: _IntervalNode | None) -> int:
    return node.height if node else 0


def _refresh(node: _IntervalNode) -> None:
    node.height = 1 + max(_height(node.left), _height(node.right))
    node.max_end = max(
        node.end,
        node.left.max_end if node.left else float("-inf"),
        node.right.max_end if node.right else float("-inf"),
    )


def _rotate_right(node: _IntervalNode) -> _IntervalNode:
    pivot = node.left
    assert pivot is not None
    node.left = pivot.right
    pivot.right = node
    _refresh(node)
    _refresh(pivot)
    return pivot


def _rotate_left(node: _IntervalNode) -> _IntervalNode:
    pivot = node.right
    assert pivot is not None
    node.right = pivot.left
    pivot.left = node
    _refresh(node)
    _refresh(pivot)
    return pivot


def _rebalance(node: _IntervalNode) -> _IntervalNode:
    _refresh(node)
    balance = _height(node.left) - _height(node.right)
    if balance > 1:
        assert node.left is not None
        if _height(node.left.left) < _height(node.left.right):
            node.left = _rotate_left(node.left)
        return _rotate_right(node)
    if balance < -1:
        assert node.right is not None
        if _height(node.right.right) < _height(node.right.left):
            node.right = _rotate_right(node.right)
        return _rotate_left(node)
    return node


class IntervalTree:
    """AVL interval tree augmented with the maximum end in each subtree.

    * insert / delete: O(log n)
    * overlap query:  O(log n + k) for k reported intervals
    * build from sorted events: O(n), or O(n log n) if sorting is included

    Half-open intervals [start, end) are used, so back-to-back events do not
    count as overlapping.  Zero-duration events occupy a point and therefore do
    not overlap anything (the impossibility detector ignores them).
    """

    __slots__ = ("_root", "_size")

    def __init__(self, events: Iterable[NormalizedEvent] | None = None) -> None:
        self._root: _IntervalNode | None = None
        self._size = 0
        if events is not None:
            self.rebuild(events)

    def rebuild(self, events: Iterable[NormalizedEvent]) -> None:
        ordered = sorted(events, key=lambda e: (e.ts, e.end_ts, e.id))
        self._root = self._build_balanced(ordered, 0, len(ordered))
        self._size = len(ordered)

    def _build_balanced(
        self, ordered: list[NormalizedEvent], lo: int, hi: int
    ) -> _IntervalNode | None:
        # Building a perfectly balanced tree directly is O(n), versus n inserts
        # at O(log n).  max_end is still maintained on the way up.
        if lo >= hi:
            return None
        mid = (lo + hi) // 2
        node = _IntervalNode(ordered[mid])
        node.left = self._build_balanced(ordered, lo, mid)
        node.right = self._build_balanced(ordered, mid + 1, hi)
        _refresh(node)
        return node

    def insert(self, event: NormalizedEvent) -> None:
        self._root = self._insert(self._root, _IntervalNode(event))
        self._size += 1

    def _insert(
        self, node: _IntervalNode | None, new: _IntervalNode
    ) -> _IntervalNode:
        if node is None:
            return new
        if new.key < node.key:
            node.left = self._insert(node.left, new)
        elif new.key > node.key:
            node.right = self._insert(node.right, new)
        else:  # same event id / interval: replace payload, keep cardinality
            node.event = new.event
            return node
        return _rebalance(node)

    def delete(self, event: NormalizedEvent) -> bool:
        key = (event.ts, event.end_ts, event.id)
        if not self._contains_key(self._root, key):
            return False
        self._root = self._delete(self._root, key)
        self._size -= 1
        return True

    def _contains_key(
        self, node: _IntervalNode | None, key: tuple[float, float, str]
    ) -> bool:
        while node is not None:
            if key < node.key:
                node = node.left
            elif key > node.key:
                node = node.right
            else:
                return True
        return False

    def _delete(
        self, node: _IntervalNode | None, key: tuple[float, float, str]
    ) -> _IntervalNode | None:
        if node is None:
            return None
        if key < node.key:
            node.left = self._delete(node.left, key)
        elif key > node.key:
            node.right = self._delete(node.right, key)
        else:
            if node.left is None:
                return node.right
            if node.right is None:
                return node.left
            successor = node.right
            while successor.left is not None:
                successor = successor.left
            # Move successor's payload/key into this node.  Only the payload is
            # observable through the public API.
            node.event = successor.event
            node.start = successor.start
            node.end = successor.end
            node.right = self._delete(
                node.right, (successor.start, successor.end, successor.event.id)
            )
        return _rebalance(node)

    def overlaps(
        self,
        start: float,
        end: float,
        *,
        exclude_id: str | None = None,
    ) -> list[NormalizedEvent]:
        """Return every interval intersecting the half-open query [start, end)."""
        if end <= start:
            return []
        found: list[NormalizedEvent] = []
        stack = [self._root]
        while stack:
            node = stack.pop()
            if node is None:
                continue
            # If the entire subtree ends before the query begins, prune it.
            if node.max_end <= start:
                continue
            # Left subtree starts are <= node.start, so only its max_end can
            # disqualify it; we already checked max_end above.
            if node.left is not None:
                stack.append(node.left)
            if node.start < end and node.end > start:
                if node.event.id != exclude_id:
                    found.append(node.event)
            # Right subtree contains only intervals starting at/after node.start.
            if node.start < end and node.right is not None:
                stack.append(node.right)
        return found

    def items_in_order(self) -> list[NormalizedEvent]:
        out: list[NormalizedEvent] = []
        stack: list[_IntervalNode] = []
        node = self._root
        while stack or node:
            while node:
                stack.append(node)
                node = node.left
            node = stack.pop()
            out.append(node.event)
            node = node.right
        return out

    def enumerate_nodes(self) -> Iterator[_IntervalNode]:
        """Testing hook; yields nodes in-order."""
        stack: list[_IntervalNode] = []
        node = self._root
        while stack or node:
            while node:
                stack.append(node)
                node = node.left
            node = stack.pop()
            yield node
            node = node.right

    @property
    def size(self) -> int:
        return self._size

    @property
    def height(self) -> int:
        return _height(self._root)

    def __len__(self) -> int:
        return self._size

    def __contains__(self, event_id: object) -> bool:
        return any(n.event.id == event_id for n in self.enumerate_nodes())


class EventIndex:
    """Facade over the hash index, sorted array, and entity interval trees."""

    __slots__ = ("hash", "timeline", "_trees", "_by_id")

    def __init__(self, events: Iterable[NormalizedEvent] | None = None) -> None:
        self.hash = HashIndex()
        self.timeline = SortedTimeline()
        self._trees: dict[str, IntervalTree] = {}
        self._by_id: dict[str, NormalizedEvent] = {}
        if events is not None:
            self.bulk_load(events)

    def bulk_load(self, events: Iterable[NormalizedEvent]) -> None:
        materialized = list(events)
        self.hash.bulk_add(materialized)
        for event in materialized:
            self._by_id[event.id] = event
        self.timeline.rebuild(materialized)
        grouped: dict[str, list[NormalizedEvent]] = {}
        for event in materialized:
            grouped.setdefault(event.entity, []).append(event)
        self._trees = {entity: IntervalTree(records) for entity, records in grouped.items()}

    def add(self, event: NormalizedEvent) -> None:
        if event.id in self._by_id:
            self.remove(event.id)
        self.hash.add(event)
        self._by_id[event.id] = event
        self.timeline.insert(event)
        tree = self._trees.get(event.entity)
        if tree is None:
            tree = IntervalTree()
            self._trees[event.entity] = tree
        tree.insert(event)

    def remove(self, event_id: str) -> NormalizedEvent | None:
        event = self._by_id.pop(event_id, None)
        if event is None:
            return None
        self.hash.remove(event_id)
        self.timeline.remove(event)
        tree = self._trees.get(event.entity)
        if tree is not None:
            tree.delete(event)
            if tree.size == 0:
                self._trees.pop(event.entity, None)
        return event

    def get(self, event_id: str) -> NormalizedEvent | None:
        return self._by_id.get(event_id)

    def entity_events(self, entity: str) -> list[NormalizedEvent]:
        tree = self._trees.get(entity)
        return tree.items_in_order() if tree else []

    def entity_tree(self, entity: str) -> IntervalTree | None:
        return self._trees.get(entity)

    def overlaps(
        self,
        start: float,
        end: float,
        *,
        entity: str | None = None,
        exclude_id: str | None = None,
    ) -> list[NormalizedEvent]:
        if entity is not None:
            tree = self._trees.get(entity)
            if tree is None:
                return []
            return tree.overlaps(start, end, exclude_id=exclude_id)
        found: list[NormalizedEvent] = []
        for tree in self._trees.values():
            found.extend(tree.overlaps(start, end, exclude_id=exclude_id))
        return found

    def all_events(self) -> list[NormalizedEvent]:
        return [self._by_id[event_id] for _, event_id in self.timeline]

    def stats(self) -> dict[str, Any]:
        return {
            "events": len(self),
            "entities": len(self._trees),
            "tree_height_max": max((t.height for t in self._trees.values()), default=0),
            "timeline_size": len(self.timeline),
        }

    @property
    def entity_names(self) -> list[str]:
        return sorted(self._trees)

    @property
    def bounds(self) -> tuple[float, float] | None:
        if not len(self.timeline):
            return None
        return (self.timeline.first_ts or 0.0, self.timeline.last_ts or 0.0)

    def __len__(self) -> int:
        return len(self._by_id)
