"""Tests for the impossible-travel detector."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contradiction_engine.detectors.location import detect
from contradiction_engine.models import Evidence

BASE = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


def at(minutes: int = 0, seconds: int = 0) -> datetime:
    """Return a timestamp relative to the test base."""
    return BASE + timedelta(minutes=minutes, seconds=seconds)


def sighting(
    record_id: str,
    place: str,
    minutes: int = 0,
    seconds: int = 0,
    person: str = "P1",
) -> Evidence:
    """Build one sighting record."""
    return Evidence(
        record_id, at(minutes, seconds), "sighting", person=person, place=place
    )


def test_clean_hop_with_enough_time() -> None:
    records = [
        sighting("S1", "Harbour", 0),
        sighting("S2", "Station", 6),
    ]
    assert detect(records) == []


def test_impossible_hop_is_flagged() -> None:
    records = [
        sighting("S1", "Harbour", 0),
        sighting("S2", "Library", 1),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.kind == "location"
    assert conflict.record_ids == ("S1", "S2")
    assert conflict.numbers["required_minutes"] == 22
    assert conflict.numbers["elapsed_minutes"] == 1
    assert conflict.numbers["shortfall_minutes"] == 21


def test_zero_duration_distant_sightings_are_flagged() -> None:
    records = [
        sighting("S1", "Harbour", 0),
        sighting("S2", "Library", 0),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    assert conflicts[0].numbers["elapsed_minutes"] == 0


def test_exactly_equal_travel_time_is_allowed() -> None:
    records = [
        sighting("S1", "Harbour", 0),
        sighting("S2", "Station", 6),
    ]
    assert detect(records) == []


def test_same_place_at_zero_gap_is_allowed() -> None:
    records = [
        sighting("S1", "Harbour", 0),
        sighting("S2", "Harbour", 0),
    ]
    assert detect(records) == []


def test_shortest_route_beats_the_slower_direct_road() -> None:
    """Clinic to Park takes 12 minutes through Library, not 20 directly."""
    records = [
        sighting("S1", "Clinic", 0),
        sighting("S2", "Park", 12),
    ]
    assert detect(records) == []


def test_a_small_shortfall_is_not_discarded() -> None:
    """One second short of the required time is still a conflict."""
    records = [
        sighting("S1", "Harbour", 0),
        sighting("S2", "Station", 5, seconds=59),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    assert conflicts[0].numbers["shortfall_minutes"] == 0.02


def test_people_are_checked_independently() -> None:
    records = [
        sighting("S1", "Harbour", 0, person="P1"),
        sighting("S2", "Station", 6, person="P1"),
        sighting("S3", "Library", 0, person="P2"),
        sighting("S4", "Dock", 1, person="P2"),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    assert conflicts[0].record_ids == ("S3", "S4")
