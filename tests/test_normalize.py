"""Normalization, offset correction, and timestamp parsing tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.normalize import (
    apply_offsets,
    estimate_device_offsets,
    normalize_event,
    normalize_events,
    parse_timestamp,
    timestamp_to_epoch,
)
from core.schema import Event


def make_event(**overrides) -> Event:
    data = dict(
        id="E1",
        timestamp="2026-01-01T12:00:00Z",
        duration_s=10,
        entity="subject-1",
        lat=51.5,
        lon=-0.1,
        source="cctv",
        device_id="CAM-1",
        action="APPROACH",
        reliability=0.9,
    )
    data.update(overrides)
    return Event(**data)


def test_parse_timestamp_z_and_offsets():
    assert parse_timestamp("2026-01-01T12:00:00Z") == datetime(
        2026, 1, 1, 12, tzinfo=timezone.utc
    )
    plus = parse_timestamp("2026-01-01T17:30:00+05:30")
    assert plus == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    naive = parse_timestamp("2026-01-01T12:00:00")
    assert naive.tzinfo is not None
    assert timestamp_to_epoch("2026-01-01T12:00:00Z") == plus.timestamp()


def test_clock_offset_is_subtracted():
    event = make_event(device_id="CAM-7")
    corrected = normalize_event(event, {"CAM-7": 30.0})
    raw = parse_timestamp(event.timestamp).timestamp()
    assert corrected.ts == pytest.approx(raw - 30.0)
    assert corrected.clock_offset_s == 30.0
    assert corrected.timestamp.startswith("2026-01-01T11:59:30")


def test_normalize_batch_and_entity_case():
    events = normalize_events(
        [
            make_event(id="A", entity="subj-x", timestamp="2026-01-01T12:00:00Z"),
            make_event(id="B", timestamp="2026-01-01T13:00:00+01:00"),
        ]
    )
    assert [event.id for event in events] == ["A", "B"]
    assert events[0].entity == "SUBJ-X"
    assert events[0].ts == events[1].ts


def test_apply_offsets_restores_raw_clock():
    original = normalize_event(make_event(), {})
    shifted = apply_offsets([original], {"CAM-1": 45.0})
    assert shifted[0].clock_offset_s == 45.0
    assert shifted[0].ts == original.ts - 45.0
    restored = apply_offsets(shifted, {"CAM-1": 0.0})
    assert restored[0].ts == pytest.approx(original.ts)


def test_estimate_device_offsets_uses_robust_median():
    # Device A is consistently +120s relative to alternating independent peers.
    events = []
    for i in range(10):
        base = 1_700_000_000 + i * 600
        events.append(
            normalize_event(
                make_event(
                    id=f"A{i}",
                    timestamp=datetime.fromtimestamp(base + 120, timezone.utc).isoformat(),
                    device_id="A",
                    source="cctv",
                    entity="SUBJ-1",
                )
            )
        )
        peer_source = "gps" if i % 2 == 0 else "device"
        events.append(
            normalize_event(
                make_event(
                    id=f"P{i}",
                    timestamp=datetime.fromtimestamp(base, timezone.utc).isoformat(),
                    device_id=f"P{peer_source}",
                    source=peer_source,
                    entity="SUBJ-1",
                )
            )
        )
    offsets = estimate_device_offsets(events, window_s=200, min_samples=3)
    assert offsets["A"] == pytest.approx(120.0, abs=1.0)
