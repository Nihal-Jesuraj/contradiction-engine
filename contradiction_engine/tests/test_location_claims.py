"""Tests for the claimed-location detector."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contradiction_engine.detectors.location_claims import detect
from contradiction_engine.models import Evidence

BASE = datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    """Return a timestamp relative to the test base."""
    return BASE + timedelta(minutes=minutes)


def sighting(
    record_id: str,
    place: str,
    minute: int,
    person: str = "P1",
) -> Evidence:
    """Build one sighting record."""
    return Evidence(record_id, at(minute), "sighting",
                    person=person, place=place)


def claim(
    record_id: str,
    start: int,
    end: int,
    place: str = "Harbour",
    person: str = "P1",
) -> Evidence:
    """Build one claimed_at claim."""
    return Evidence(
        record_id, at(start), "claim", person=person, place=place,
        claim="claimed_at", end_timestamp=at(end),
    )


def test_sighting_with_enough_time_is_clean() -> None:
    """The check is both-edges, not throughout: a middle sighting can pass."""
    records = [claim("C1", 0, 60), sighting("S1", "Library", 30)]
    assert detect(records) == []


def test_close_sighting_elsewhere_is_a_conflict() -> None:
    """Harbour to Library needs 22 minutes, but only 3 are available."""
    records = [claim("C1", 0, 6), sighting("S1", "Library", 3)]
    conflicts = detect(records)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.kind == "claim_location"
    assert conflict.record_ids == ("C1", "S1")
    assert conflict.numbers["claimed_place"] == "Harbour"
    assert conflict.numbers["seen_place"] == "Library"
    assert conflict.numbers["required_minutes"] == 22
    assert conflict.numbers["nearest_edge_minutes"] == 3
    assert conflict.numbers["shortfall_minutes"] == 19
    assert conflict.severity == 0.88
    assert "Harbour" in conflict.explanation


def test_sighting_at_the_claimed_place_is_clean() -> None:
    records = [claim("C1", 0, 6), sighting("S1", "Harbour", 3)]
    assert detect(records) == []


def test_sighting_outside_the_window_is_clean() -> None:
    records = [claim("C1", 0, 6), sighting("S1", "Library", 7)]
    assert detect(records) == []


def test_exactly_enough_time_is_allowed() -> None:
    """Harbour to Station takes 6 minutes, and exactly 6 are available."""
    records = [claim("C1", 0, 12), sighting("S1", "Station", 6)]
    assert detect(records) == []


def test_unknown_claimed_place_is_ignored() -> None:
    records = [claim("C1", 0, 6, place="Atlantis"), sighting("S1", "Library", 3)]
    assert detect(records) == []


def test_unknown_sighting_place_is_ignored() -> None:
    records = [claim("C1", 0, 6), sighting("S1", "Atlantis", 3)]
    assert detect(records) == []


def test_only_the_claimants_sightings_are_checked() -> None:
    records = [
        claim("C1", 0, 6),
        sighting("S1", "Library", 3, person="P2"),
    ]
    assert detect(records) == []


def test_multiple_sightings_produce_multiple_conflicts() -> None:
    records = [
        claim("C1", 0, 6),
        sighting("S1", "Library", 2),
        sighting("S2", "Dock", 4),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 2
    assert {conflict.record_ids for conflict in conflicts} == {
        ("C1", "S1"),
        ("C1", "S2"),
    }


def test_default_graph_is_used_when_none_is_passed() -> None:
    records = [claim("C1", 0, 6), sighting("S1", "Library", 3)]
    assert len(detect(records, None)) == 1
