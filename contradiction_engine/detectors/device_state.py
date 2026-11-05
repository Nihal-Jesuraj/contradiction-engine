"""Detector 1: local device activity during an OFF or SLEEP interval.

Algorithm: group records by device with our HashTable, merge-sort each
device's state records, treat each state as lasting until the next state, and
binary-search the state that is active at each activity timestamp.
"""

from __future__ import annotations

from ..algorithms.hash_table import HashTable
from ..algorithms.sorting import merge_sort, upper_bound
from ..models import Conflict, Evidence

_RULES = {
    "OFF": "A powered-off device cannot record a local activity.",
    "SLEEP": "A sleeping device is not expected to record local activity.",
}
_SEVERITY = {"OFF": 0.90, "SLEEP": 0.55}


def detect(records: list[Evidence]) -> list[Conflict]:
    """Find activities recorded while their device is OFF or SLEEP.

    Inputs: all evidence records.
    Outputs: one conflict per offending activity.
    Complexity: O(n log n) time, O(n) space.
    """
    states_by_device, activities_by_device = _group_by_device(records)
    conflicts: list[Conflict] = []
    for device in states_by_device.keys():
        states = merge_sort(
            states_by_device.get(device, []),
            key=lambda record: (record.timestamp, record.id),
        )
        activities = merge_sort(
            activities_by_device.get(device, []),
            key=lambda record: (record.timestamp, record.id),
        )
        for activity in activities:
            conflict = _check_activity(device, states, activity)
            if conflict is not None:
                conflicts.append(conflict)
    return conflicts


def _group_by_device(
    records: list[Evidence],
) -> tuple[HashTable, HashTable]:
    """Split state and activity records into per-device buckets."""
    states: HashTable = HashTable()
    activities: HashTable = HashTable()
    for record in records:
        if record.record_type == "state" and record.device:
            _append(states, record.device, record)
        elif record.record_type == "activity" and record.device:
            _append(activities, record.device, record)
    return states, activities


def _append(table: HashTable, key: str, record: Evidence) -> None:
    """Append a record to a hash bucket, creating the bucket on demand."""
    bucket = table.get(key)
    if bucket is None:
        bucket = []
        table.put(key, bucket)
    bucket.append(record)


def _check_activity(
    device: str,
    states: list[Evidence],
    activity: Evidence,
) -> Conflict | None:
    """Return a conflict when the active state forbids local activity."""
    position = upper_bound(
        states, activity.timestamp, key=lambda record: record.timestamp
    ) - 1
    if position < 0:
        # No earlier state means we cannot prove anything; never invent one.
        return None
    state = states[position]
    if state.state not in _RULES:
        return None

    ends_at = (
        states[position + 1].timestamp
        if position + 1 < len(states)
        else None
    )
    minutes_into_state = round(
        (activity.timestamp - state.timestamp).total_seconds() / 60.0, 2
    )
    return Conflict(
        kind="device_state",
        record_ids=(activity.id, state.id),
        rule_text=_RULES[state.state],
        numbers={
            "device": device,
            "state": state.state,
            "activity_time": activity.timestamp.isoformat(),
            "state_since": state.timestamp.isoformat(),
            "state_until": ends_at.isoformat() if ends_at else "open-ended",
            "minutes_into_state": minutes_into_state,
        },
        explanation=_explain(device, activity, state, minutes_into_state),
        severity=_SEVERITY[state.state],
    )


def _explain(
    device: str,
    activity: Evidence,
    state: Evidence,
    minutes_into_state: float,
) -> str:
    """Build a short English explanation with the real timestamps."""
    action = activity.action or "local activity"
    sentence = (
        f"Device {device} recorded '{action}' at {activity.timestamp}, "
        f"but it had been {state.state} since {state.timestamp} "
        f"({minutes_into_state} minutes earlier)."
    )
    if state.state == "SLEEP":
        sentence += (
            " Sleep can still permit background wake events, so this is "
            "suspicious rather than impossible."
        )
    return sentence
