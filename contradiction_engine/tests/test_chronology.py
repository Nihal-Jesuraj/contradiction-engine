"""Tests for the message chronology detector."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contradiction_engine.detectors.chronology import detect
from contradiction_engine.models import Evidence

BASE = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    """Return a timestamp relative to the test base."""
    return BASE + timedelta(minutes=minutes)


def message(record_id: str, minute: int, depends_on: str = "") -> Evidence:
    """Build one message record."""
    return Evidence(
        record_id,
        at(minute),
        "message",
        person="P1",
        depends_on=depends_on,
        text=record_id,
    )


def test_clean_chain_has_no_conflicts() -> None:
    records = [
        message("M1", 0),
        message("M2", 10, depends_on="M1"),
        message("M3", 20, depends_on="M2"),
    ]
    assert detect(records) == []


def test_reply_before_parent_is_flagged() -> None:
    records = [
        message("M1", 10),
        message("M2", 0, depends_on="M1"),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.kind == "message_order"
    assert conflict.record_ids == ("M1", "M2")
    assert conflict.numbers["seconds_early"] == 600


def test_equal_timestamps_are_allowed() -> None:
    records = [
        message("M1", 0),
        message("M2", 0, depends_on="M1"),
    ]
    assert detect(records) == []


def test_dependency_cycle_is_reported_once() -> None:
    records = [
        message("A", 0, depends_on="C"),
        message("B", 10, depends_on="A"),
        message("C", 20, depends_on="B"),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    assert conflicts[0].kind == "message_cycle"
    assert set(conflicts[0].record_ids) == {"A", "B", "C"}
    assert conflicts[0].numbers["cycle_length"] == 3


def test_self_reply_is_a_cycle() -> None:
    records = [message("A", 0, depends_on="A")]
    conflicts = detect(records)
    assert len(conflicts) == 1
    assert conflicts[0].record_ids == ("A",)


def test_independent_reversed_chains_are_both_reported() -> None:
    records = [
        message("A1", 10),
        message("A2", 0, depends_on="A1"),
        message("B1", 30),
        message("B2", 20, depends_on="B1"),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 2
    assert {conflict.record_ids for conflict in conflicts} == {
        ("A1", "A2"),
        ("B1", "B2"),
    }
