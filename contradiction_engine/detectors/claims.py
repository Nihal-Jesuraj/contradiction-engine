"""Detector 4: a denied-access claim that overlaps a real login.

Algorithm: group login records by account with our HashTable, merge-sort each
account's logins, and use lower/upper binary-search bounds to find logins in
the closed claim window.
"""

from __future__ import annotations

from ..algorithms.hash_table import HashTable
from ..algorithms.sorting import lower_bound, merge_sort, upper_bound
from ..models import Conflict, Evidence

RULE = "A denied-access claim cannot overlap a login to the same account."


def detect(records: list[Evidence]) -> list[Conflict]:
    """Find did_not_access claims that overlap an account login.

    Inputs: all evidence records.
    Outputs: one conflict per claim with at least one matching login.
    Complexity: O(n log n + c log n + k) time, O(n) space.
    """
    logins_by_account = _group_logins(records)
    conflicts: list[Conflict] = []
    for claim in records:
        if claim.record_type != "claim" or claim.claim != "did_not_access":
            continue
        if claim.end_timestamp is None:
            continue
        logins = merge_sort(
            logins_by_account.get(claim.account, []),
            key=lambda record: (record.timestamp, record.id),
        )
        matches = _logins_in_window(logins, claim)
        if matches:
            conflicts.append(_conflict(claim, matches))
    return conflicts


def _group_logins(records: list[Evidence]) -> HashTable:
    """Bucket login records by account."""
    grouped: HashTable = HashTable()
    for record in records:
        if record.record_type != "login" or not record.account:
            continue
        bucket = grouped.get(record.account)
        if bucket is None:
            bucket = []
            grouped.put(record.account, bucket)
        bucket.append(record)
    return grouped


def _logins_in_window(logins: list[Evidence], claim: Evidence) -> list[Evidence]:
    """Return logins inside the closed ``[start, end]`` claim window."""
    start = claim.timestamp
    end = claim.end_timestamp
    if end is None:
        return []
    first = lower_bound(logins, start, key=lambda record: record.timestamp)
    last = upper_bound(logins, end, key=lambda record: record.timestamp)
    return logins[first:last]


def _conflict(claim: Evidence, matches: list[Evidence]) -> Conflict:
    """Build one conflict from a claim and its matching logins."""
    first = matches[0]
    minutes_after_start = (
        first.timestamp - claim.timestamp
    ).total_seconds() / 60.0
    return Conflict(
        kind="claim",
        record_ids=(claim.id, first.id),
        rule_text=RULE,
        numbers={
            "account": claim.account,
            "claim_start": claim.timestamp.isoformat(),
            "claim_end": (
                claim.end_timestamp.isoformat()
                if claim.end_timestamp is not None
                else ""
            ),
            "first_login": first.timestamp.isoformat(),
            "login_count": len(matches),
            "minutes_after_claim_start": round(minutes_after_start, 2),
        },
        explanation=(
            f"{claim.person or 'The subject'} denied accessing account "
            f"{claim.account} between {claim.timestamp} and "
            f"{claim.end_timestamp}, but a login occurred at "
            f"{first.timestamp} ({len(matches)} matching login(s))."
        ),
        severity=0.85,
    )
