"""Tests for the device-state detector."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contradiction_engine.detectors.device_state import detect
from contradiction_engine.models import Evidence

BASE = datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    """Return a timestamp a number of minutes after the test base."""
    return BASE + timedelta(minutes=minutes)


def state(record_id: str, minute: int, value: str, device: str = "D1") -> Evidence:
    """Build a device state record."""
    return Evidence(record_id, at(minute), "state", device=device, state=value)


def activity(
    record_id: str,
    minute: int,
    device: str = "D1",
    action: str = "local login",
) -> Evidence:
    """Build a local activity record."""
    return Evidence(record_id, at(minute), "activity", device=device, action=action)


def login(
    record_id: str,
    minute: int,
    device: str = "D1",
    person: str = "P1",
    account: str = "A1",
) -> Evidence:
    """Build an account login that may name the local device."""
    return Evidence(record_id, at(minute), "login",
                    person=person, account=account, device=device)


def test_clean_timeline_has_no_conflicts() -> None:
    records = [
        state("S1", 0, "ON"),
        activity("A1", 10),
        state("S2", 20, "OFF"),
        state("S3", 40, "ON"),
        activity("A2", 50),
    ]
    assert detect(records) == []


def test_activity_during_off_is_a_conflict() -> None:
    records = [
        state("S1", 0, "ON"),
        state("S2", 20, "OFF"),
        activity("A1", 30),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.kind == "device_state"
    assert conflict.record_ids == ("A1", "S2")
    assert conflict.numbers["state"] == "OFF"
    assert conflict.severity == 0.90
    assert "OFF" in conflict.explanation


def test_activity_during_sleep_has_lower_severity() -> None:
    records = [
        state("S1", 0, "ON"),
        state("S2", 20, "SLEEP"),
        activity("A1", 30),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    assert conflicts[0].severity == 0.55
    assert "suspicious rather than impossible" in conflicts[0].explanation


def test_activity_at_off_transition_conflicts() -> None:
    records = [state("S1", 0, "ON"), state("S2", 20, "OFF"), activity("A1", 20)]
    assert len(detect(records)) == 1


def test_activity_at_on_transition_is_allowed() -> None:
    records = [
        state("S1", 0, "OFF"),
        state("S2", 20, "ON"),
        activity("A1", 20),
    ]
    assert detect(records) == []


def test_last_state_wins_for_duplicate_timestamps() -> None:
    records = [
        state("S1", 0, "OFF"),
        state("S2", 20, "OFF"),
        state("S3", 20, "ON"),
        activity("A1", 30),
    ]
    assert detect(records) == []


def test_activity_before_any_state_is_ignored() -> None:
    records = [state("S1", 20, "OFF"), activity("A1", 10)]
    assert detect(records) == []


def test_devices_are_independent() -> None:
    records = [
        state("S1", 0, "ON", device="D1"),
        state("S2", 0, "OFF", device="D2"),
        activity("A1", 10, device="D1"),
        activity("A2", 10, device="D2"),
    ]
    conflicts = detect(records)
    assert [conflict.record_ids for conflict in conflicts] == [("A2", "S2")]


def test_login_during_off_is_a_conflict() -> None:
    """A login that names an OFF device is local activity."""
    records = [
        state("S1", 0, "ON"),
        state("S2", 20, "OFF"),
        login("L1", 30),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.record_ids == ("L1", "S2")
    assert conflict.numbers["record_type"] == "login"
    assert "'account login'" in conflict.explanation


def test_login_during_on_is_clean() -> None:
    """An operational device can process a login."""
    records = [state("S1", 0, "ON"), login("L1", 10)]
    assert detect(records) == []


def test_login_without_a_device_is_ignored() -> None:
    """A login with no device cannot be tied to a device state."""
    records = [
        state("S1", 0, "ON"),
        state("S2", 20, "OFF"),
        login("L1", 30, device=""),
    ]
    assert detect(records) == []
