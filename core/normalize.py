"""UTC normalization and per-device clock-offset correction.

Clock convention
----------------
A device offset is the number of seconds that the device's clock is *ahead* of
true UTC.  If a camera stamped 10:00:00 while true UTC was 09:59:30, its offset
is +30 s and the corrected time is ``recorded - 30``.

Complexity: O(n) time, O(n) space for n events.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone

from .schema import Event, NormalizedEvent, iso_utc


def parse_timestamp(value: str | datetime) -> datetime:
    """Parse ISO-8601 into an aware UTC datetime.

    Naive values are interpreted as UTC.  ``Z`` suffixes are accepted on every
    supported Python version.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:  # pragma: no cover - error message detail
            raise ValueError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def timestamp_to_epoch(value: str | datetime) -> float:
    return parse_timestamp(value).timestamp()


def normalize_event(
    event: Event,
    clock_offsets: Mapping[str, float] | None = None,
) -> NormalizedEvent:
    """Convert one record to corrected UTC epoch seconds.

    The original timestamp is retained for auditability.  Duration is measured
    by the recording device and is therefore unaffected by a clock offset.
    """
    offsets = clock_offsets or {}
    raw_dt = parse_timestamp(event.timestamp)
    offset = float(offsets.get(event.device_id, 0.0))
    corrected = raw_dt.timestamp() - offset
    return NormalizedEvent(
        id=event.id,
        ts=corrected,
        timestamp=iso_utc(corrected),
        original_timestamp=event.timestamp,
        duration_s=max(0.0, float(event.duration_s)),
        entity=event.entity.strip().upper(),
        lat=float(event.lat),
        lon=float(event.lon),
        source=event.source.strip().lower(),
        device_id=event.device_id.strip().upper(),
        action=event.action,
        reliability=max(0.0, min(1.0, float(event.reliability))),
        clock_offset_s=offset,
    )


def normalize_events(
    events: Iterable[Event],
    clock_offsets: Mapping[str, float] | None = None,
) -> list[NormalizedEvent]:
    """Normalize a batch; order is preserved.

    O(n) time, O(n) space.
    """
    return [normalize_event(event, clock_offsets) for event in events]


def estimate_device_offsets(
    events: Iterable[NormalizedEvent],
    *,
    window_s: float = 240.0,
    min_samples: int = 3,
    rounding_s: float = 1.0,
) -> dict[str, float]:
    """Estimate robust offsets from cross-source corroboration.

    For each event, find the closest same-entity event from a different source
    inside ``window_s``.  The per-device median of ``device_time - peer_time``
    is a robust estimate of that device's offset.  The median resists one bad
    witness statement.  This is used for *advisory* correction; the detector
    still reports suspected skew because an inferred offset is not evidence.

    Complexity: O(n log n) to group/sort + O(n log n) nearest-neighbour scans.
    """
    from bisect import bisect_left

    by_entity: dict[str, list[NormalizedEvent]] = {}
    for event in events:
        by_entity.setdefault(event.entity, []).append(event)
    per_device: dict[str, list[float]] = {}
    for records in by_entity.values():
        records.sort(key=lambda e: (e.ts, e.id))
        times = [e.ts for e in records]
        for i, event in enumerate(records):
            best: NormalizedEvent | None = None
            best_gap = window_s
            # Walk outward from the event's position; stop when the time gap
            # exceeds the window, which keeps this near O(k log n).
            j = bisect_left(times, event.ts - window_s)
            while j < len(records):
                peer = records[j]
                gap = abs(peer.ts - event.ts)
                if peer.ts - event.ts > window_s:
                    break
                if peer.source != event.source and peer.device_id != event.device_id:
                    if gap < best_gap:
                        best_gap = gap
                        best = peer
                j += 1
                if j - i > 64:  # cap pathological dense bursts
                    break
            if best is not None:
                per_device.setdefault(event.device_id, []).append(event.ts - best.ts)

    offsets: dict[str, float] = {}
    for device_id, deltas in per_device.items():
        if len(deltas) < min_samples:
            continue
        deltas.sort()
        median = deltas[len(deltas) // 2]
        if rounding_s > 0:
            median = round(median / rounding_s) * rounding_s
        # Tiny latency differences are not clock errors.
        if abs(median) >= 5.0:
            offsets[device_id] = median
    return offsets


def apply_offsets(
    events: Iterable[NormalizedEvent],
    offsets: Mapping[str, float],
) -> list[NormalizedEvent]:
    """Re-time already-normalized events after offsets are learned.

    O(n) time, O(n) space.
    """
    corrected: list[NormalizedEvent] = []
    for event in events:
        offset = float(offsets.get(event.device_id, event.clock_offset_s))
        # If the event was already corrected by its old offset, first restore
        # the raw clock then apply the new offset.
        raw_ts = event.ts + event.clock_offset_s
        new_ts = raw_ts - offset
        corrected.append(
            NormalizedEvent(
                id=event.id,
                ts=new_ts,
                timestamp=iso_utc(new_ts),
                original_timestamp=event.original_timestamp,
                duration_s=event.duration_s,
                entity=event.entity,
                lat=event.lat,
                lon=event.lon,
                source=event.source,
                device_id=event.device_id,
                action=event.action,
                reliability=event.reliability,
                clock_offset_s=offset,
            )
        )
    return corrected
