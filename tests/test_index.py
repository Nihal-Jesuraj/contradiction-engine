"""Index structure correctness and complexity-shape tests."""

from __future__ import annotations

import random

from core.index import EventIndex, HashIndex, IntervalTree, SortedTimeline
from core.normalize import normalize_event
from core.schema import Event


def event(i: int, start: float, duration: float = 10.0, entity: str = "E") -> Event:
    return Event(
        id=f"E{i:04d}",
        timestamp=f"2026-01-01T00:00:{int(start) % 60:02d}Z",
        duration_s=duration,
        entity=entity,
        lat=51.5,
        lon=-0.1,
        source="gps",
        device_id="GPS-1",
        action="FIX",
        reliability=0.8,
    )


def norm(i: int, start: float, duration: float = 10.0, entity: str = "E"):
    from datetime import datetime, timezone

    return normalize_event(
        Event(
            id=f"E{i:04d}",
            timestamp=datetime.fromtimestamp(
                1_700_000_000 + start, timezone.utc
            ).isoformat(),
            duration_s=duration,
            entity=entity,
            lat=51.5,
            lon=-0.1,
            source="gps",
            device_id="GPS-1",
            action="FIX",
            reliability=0.8,
        )
    )


def brute_overlaps(events, start, end):
    return {
        e.id
        for e in events
        if e.ts < end and e.end_ts > start
    }


def test_hash_index_add_remove():
    index = HashIndex()
    for i in range(10):
        index.add(norm(i, i * 10))
    assert len(index) == 10
    assert len(index.ids_for("E")) == 10
    removed = index.remove("E0003")
    assert removed is not None
    assert len(index) == 9
    assert "E0003" not in index
    assert index.remove("missing") is None


def test_sorted_timeline_range():
    records = [norm(i, i * 10) for i in range(10)]
    timeline = SortedTimeline(records)
    base = timeline.first_ts
    assert len(timeline) == 10
    assert [event_id for _, event_id in timeline.range(base + 30, base + 60)] == [
        "E0003",
        "E0004",
        "E0005",
    ]
    timeline.insert(norm(20, 35))
    assert timeline.range(base + 30, base + 40)[1][1] == "E0020"
    timeline.remove(norm(20, 35))
    assert len(timeline) == 10


def test_interval_tree_against_brute_force():
    rng = random.Random(99)
    records = []
    for i in range(300):
        start = rng.uniform(0, 10_000)
        duration = rng.uniform(0, 400)
        records.append(norm(i, start, duration))
    tree = IntervalTree(records)
    for _ in range(400):
        start = rng.uniform(0, 10_000)
        end = start + rng.uniform(1, 500)
        got = {e.id for e in tree.overlaps(start, end)}
        assert got == brute_overlaps(records, start, end)
    assert tree.height <= 2 * (len(records).bit_length() + 1)


def test_interval_tree_insert_delete_maintains_augmentation():
    records = [norm(i, i * 100, 30) for i in range(64)]
    tree = IntervalTree(records)
    for record in records[::3]:
        assert tree.delete(record)
    remaining = [record for record in records if record.id not in {r.id for r in records[::3]}]
    assert len(tree) == len(remaining)
    for start, end in [(0, 500), (900, 2600), (3000, 8000)]:
        assert {e.id for e in tree.overlaps(start, end)} == brute_overlaps(
            remaining, start, end
        )
    # Deletion must preserve AVL height and subtree max_end.
    nodes = list(tree.enumerate_nodes())
    assert nodes
    assert max(node.height for node in nodes) <= 2 * (len(records).bit_length() + 1)
    for node in nodes:
        expected = max(
            [node.end]
            + ([node.left.max_end] if node.left else [])
            + ([node.right.max_end] if node.right else [])
        )
        assert node.max_end == expected


def test_event_index_entity_forest_queries():
    records = [
        norm(0, 0, 100, entity="A"),
        norm(1, 50, 100, entity="A"),
        norm(2, 50, 100, entity="B"),
    ]
    index = EventIndex(records)
    base = index.bounds[0]
    assert index.overlaps(base + 40, base + 60, entity="A")[0].entity == "A"
    assert len(index.overlaps(base + 40, base + 60, entity="A")) == 2
    assert len(index.overlaps(base + 40, base + 60)) == 3
    index.remove("E0001")
    assert len(index.overlaps(base + 40, base + 60, entity="A")) == 1
    assert index.stats()["entities"] == 2
