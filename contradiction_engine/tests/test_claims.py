"""Tests for the interview-claim detector."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contradiction_engine.detectors.claims import detect
from contradiction_engine.models import Evidence

BASE = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    """Return a timestamp relative to the test base."""
    return BASE + timedelta(minutes=minutes)


def login(
    record_id: str,
    minute: int,
    account: str = "A1",
    person: str = "P1",
) -> Evidence:
    """Build one login record."""
    return Evidence(record_id, at(minute), "login",
                    person=person, account=account)


def claim(
    record_id: str,
    start: int,
    end: int,
    account: str = "A1",
    person: str = "P1",
) -> Evidence:
    """Build one did_not_access claim."""
    return Evidence(
        record_id, at(start), "claim", person=person, account=account,
        claim="did_not_access", end_timestamp=at(end),
    )


def test_claim_without_logins_is_clean() -> None:
    records = [login("L1", 0), claim("C1", 30, 60)]
    assert detect(records) == []


def test_login_inside_window_is_a_conflict() -> None:
    records = [login("L1", 15), claim("C1", 0, 30)]
    conflicts = detect(records)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.kind == "claim"
    assert conflict.record_ids == ("C1", "L1")
    assert conflict.numbers["login_count"] == 1
    assert conflict.numbers["minutes_after_claim_start"] == 15


def test_login_on_the_start_boundary_counts() -> None:
    records = [login("L1", 0), claim("C1", 0, 30)]
    assert len(detect(records)) == 1


def test_login_on_the_end_boundary_counts() -> None:
    records = [login("L1", 30), claim("C1", 0, 30)]
    assert len(detect(records)) == 1


def test_login_outside_window_is_clean() -> None:
    records = [login("L1", 31), claim("C1", 0, 30)]
    assert detect(records) == []


def test_login_on_another_account_is_clean() -> None:
    records = [login("L1", 10, account="A2"), claim("C1", 0, 30, account="A1")]
    assert detect(records) == []


def test_login_by_another_person_is_clean() -> None:
    """A colleague using the same account does not contradict the claimant."""
    records = [login("L1", 15, person="P2"), claim("C1", 0, 30, person="P1")]
    assert detect(records) == []


def test_login_by_the_claimant_is_flagged() -> None:
    """The same person on the same account inside the window is a conflict."""
    records = [login("L1", 15, person="P1"), claim("C1", 0, 30, person="P1")]
    assert len(detect(records)) == 1


def test_multiple_logins_produce_one_conflict() -> None:
    records = [
        login("L1", 5),
        login("L2", 10),
        claim("C1", 0, 30),
    ]
    conflicts = detect(records)
    assert len(conflicts) == 1
    assert conflicts[0].numbers["login_count"] == 2
    assert conflicts[0].record_ids == ("C1", "L1")
