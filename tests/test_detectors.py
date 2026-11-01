"""Detectors must find every planted contradiction and invent none."""

from __future__ import annotations

from collections import Counter

import pytest

from core.detectors import (
    DetectionConfig,
    detect_clock_skew,
    detect_impossible_travel,
    detect_simultaneity,
    haversine_m,
    run_detectors,
)
from core.generator import GeneratorConfig, generate_dataset
from core.index import EventIndex
from core.normalize import normalize_events
from core.schema import Event


def dataset(seed: int = 1):
    generated = generate_dataset(
        GeneratorConfig(n_events=400, contradictions=9, seed=seed, span_days=5.0)
    )
    index = EventIndex(normalize_events(generated.events))
    return generated, index


def keys(conflicts):
    return {
        ("clock_skew", conflict.device_id)
        if conflict.kind == "clock_skew"
        else (conflict.kind, frozenset(conflict.event_ids))
        for conflict in conflicts
    }


def truth_keys(generated):
    return {
        ("clock_skew", item.device_id)
        if item.type == "clock_skew"
        else (item.type, frozenset(item.event_ids))
        for item in generated.ground_truth
    }


def test_all_planted_contradictions_found_without_false_positives():
    for seed in (1, 2, 3, 9):
        generated, index = dataset(seed)
        conflicts = run_detectors(index, generated.rules)
        assert keys(conflicts) == truth_keys(generated)
        counts = Counter(conflict.kind for conflict in conflicts)
        assert counts["clock_skew"] >= 1


def test_simultaneity_same_location_is_not_flagged():
    generated, index = dataset(2)
    before = len(detect_simultaneity(index, DetectionConfig()))
    # Duplicate an event at the same location: no spatial contradiction.
    original = index.entity_events("SUBJ-001")[0]
    duplicate = Event(
        id="DUP-SAME-LOC",
        timestamp=original.timestamp,
        duration_s=100,
        entity=original.entity,
        lat=original.lat,
        lon=original.lon,
        source="gps",
        device_id="GPS-DUP",
        action=original.action,
        reliability=0.9,
    )
    index.add(normalize_events([duplicate])[0])
    after = detect_simultaneity(index, DetectionConfig())
    assert len(after) == before


def test_simultaneity_different_location_is_flagged():
    generated, index = dataset(3)
    original = index.entity_events("SUBJ-001")[0]
    from core.schema import iso_utc

    duplicate = Event(
        id="DUP-FAR",
        timestamp=original.timestamp,
        duration_s=200,
        entity=original.entity,
        lat=original.lat + 0.2,
        lon=original.lon,
        source="gps",
        device_id="GPS-DUP",
        action=original.action,
        reliability=0.9,
    )
    index.add(normalize_events([duplicate])[0])
    found = detect_simultaneity(index, DetectionConfig())
    assert any("DUP-FAR" in conflict.event_ids for conflict in found)


def test_haversine_known_distance():
    # London -> Paris is roughly 343 km.
    distance = haversine_m(51.5074, -0.1278, 48.8566, 2.3522)
    assert 330_000 < distance < 355_000


def test_travel_speed_threshold_controls_flag():
    generated, index = dataset(4)
    fast = detect_impossible_travel(index, DetectionConfig(max_speed_mps=1.0))
    impossible = detect_impossible_travel(index, DetectionConfig(max_speed_mps=10_000.0))
    assert len(fast) >= len(impossible)
    assert all(conflict.kind == "impossible_travel" for conflict in fast)


def test_clock_skew_can_be_narrowed_by_device():
    generated, index = dataset(1)
    skew_device = next(
        item.device_id for item in generated.ground_truth if item.type == "clock_skew"
    )
    narrowed = detect_clock_skew(index, device_ids={skew_device})
    assert len(narrowed) == 1
    assert narrowed[0].device_id == skew_device
    assert detect_clock_skew(index, device_ids={"NO-SUCH-DEVICE"}) == []


def test_incremental_event_filter_includes_new_record():
    generated, index = dataset(5)
    from core.schema import iso_utc

    original = index.entity_events("SUBJ-002")[0]
    planted = normalize_events(
        [
            Event(
                id="INCR-FAR",
                timestamp=original.timestamp,
                duration_s=180,
                entity=original.entity,
                lat=original.lat + 0.3,
                lon=original.lon,
                source="gps",
                device_id="GPS-INCR",
                action="FIX",
                reliability=0.9,
            )
        ]
    )[0]
    index.add(planted)
    all_found = detect_simultaneity(index, DetectionConfig())
    local = detect_simultaneity(index, DetectionConfig(), event_ids={planted.id})
    assert any(planted.id in conflict.event_ids for conflict in all_found)
    assert local
    assert all(planted.id in conflict.event_ids for conflict in local)
