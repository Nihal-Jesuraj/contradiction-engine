"""Contradiction detectors.

All detectors are deterministic for a given dataset.  Candidate generation is
indexed; no detector compares every event with every other event.

Complexities (n events, k reported overlaps, e events per entity):

1. simultaneity  O(n log e + k) via per-entity interval queries
2. travel        O(n log n) entity grouping + O(n) adjacent scan
3. causality     O(r) for r rules
4. clock skew    O(n log n + n*w) where w is a small neighbour window cap
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from .index import EventIndex
from .schema import Conflict, NormalizedEvent, Rule, make_conflict


@dataclass(slots=True)
class DetectionConfig:
    """Tunable evidentiary thresholds.

    Defaults assume terrestrial urban/suburban movement.  A motorway pursuit can
    raise ``max_speed_mps``; forensic labs should record the chosen value with
    the report because it changes the false-positive rate.
    """

    max_speed_mps: float = 250.0  # 900 km/h
    location_epsilon_m: float = 80.0
    min_overlap_s: float = 0.5
    clock_skew_threshold_s: float = 120.0
    clock_window_s: float = 900.0
    clock_min_samples: int = 4
    clock_mad_max_s: float = 40.0
    neighbour_cap: int = 64


EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres.  O(1) time / O(1) space."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _event_sources(events: list[NormalizedEvent]) -> tuple[str, ...]:
    return tuple(sorted({e.source for e in events}))


def detect_simultaneity(
    index: EventIndex,
    config: DetectionConfig | None = None,
    event_ids: set[str] | None = None,
) -> list[Conflict]:
    """Same entity, overlapping intervals, materially different locations.

    For every event e we query only e's entity interval tree for intervals
    intersecting e.  The tree's ``max_end`` augmentation prunes whole subtrees
    whose intervals finish before e starts, so the cost is O(log e + k).

    ``event_ids`` narrows the scan to newly ingested records for incremental
    analysis; every returned conflict still contains at least one new record.
    """
    cfg = config or DetectionConfig()
    conflicts: list[Conflict] = []
    seen: set[tuple[str, str]] = set()

    if event_ids is None:
        entities = index.entity_names
    else:
        entities = sorted(
            {
                record.entity
                for event_id in event_ids
                if (record := index.get(event_id)) is not None
            }
        )
    for entity in entities:
        tree = index.entity_tree(entity)
        if tree is None:
            continue
        for event in tree.items_in_order():
            if event_ids is not None and event.id not in event_ids:
                continue
            if event.end_ts <= event.ts:
                continue
            for other in tree.overlaps(event.ts, event.end_ts, exclude_id=event.id):
                if other.end_ts <= other.ts:
                    continue
                overlap = min(event.end_ts, other.end_ts) - max(event.ts, other.ts)
                if overlap < cfg.min_overlap_s:
                    continue
                distance = haversine_m(
                    event.lat, event.lon, other.lat, other.lon
                )
                if distance <= cfg.location_epsilon_m:
                    continue
                # Canonical unordered pair prevents double reporting while
                # still finding old neighbours when only a new event is scanned.
                pair = tuple(sorted((event.id, other.id)))
                if pair in seen:
                    continue
                seen.add(pair)
                # More overlap and larger separation both increase certainty.
                severity = min(
                    0.98,
                    0.58
                    + min(0.2, overlap / 3600.0 * 0.2)
                    + min(0.2, distance / 50_000.0 * 0.2),
                )
                conflicts.append(
                    make_conflict(
                        "impossible_simultaneity",
                        [event.id, other.id],
                        entity,
                        (
                            f"{entity} is recorded at two places {distance / 1000:.1f} km "
                            f"apart for {overlap:.1f}s of overlapping time."
                        ),
                        severity=severity,
                        t_delta_s=overlap,
                        detected_by="simultaneity",
                        meta={
                            "distance_m": round(distance, 1),
                            "overlap_s": round(overlap, 3),
                            "sources": sorted({event.source, other.source}),
                        },
                    )
                )
                conflicts[-1].sources = _event_sources([event, other])
    return conflicts


def detect_impossible_travel(
    index: EventIndex,
    config: DetectionConfig | None = None,
    event_ids: set[str] | None = None,
) -> list[Conflict]:
    """Adjacent events per entity imply a physically impossible speed.

    Sorting each entity's events costs O(e log e), so O(n log n) overall.  For
    each adjacent pair we divide great-circle distance by elapsed time.  The
    check intentionally uses *start* times; interval overlap is detector #1's
    job.

    With ``event_ids`` supplied, only the predecessor/successor edges of those
    records are examined — O(new * log e) instead of a full rescan.
    """
    cfg = config or DetectionConfig()
    conflicts: list[Conflict] = []
    seen: set[tuple[str, str]] = set()

    if event_ids is None:
        entities = index.entity_names
    else:
        entities = sorted(
            {
                record.entity
                for event_id in event_ids
                if (record := index.get(event_id)) is not None
            }
        )
    for entity in entities:
        records = index.entity_events(entity)
        if len(records) < 2:
            continue
        pairs: list[tuple[NormalizedEvent, NormalizedEvent]]
        if event_ids is None:
            pairs = list(zip(records, records[1:]))
        else:
            pairs = []
            positions = {record.id: i for i, record in enumerate(records)}
            for event_id in event_ids:
                pos = positions.get(event_id)
                if pos is None:
                    continue
                if pos > 0:
                    pairs.append((records[pos - 1], records[pos]))
                if pos + 1 < len(records):
                    pairs.append((records[pos], records[pos + 1]))
        for first, second in pairs:
            elapsed = second.ts - first.ts
            if elapsed <= 0:
                continue
            distance = haversine_m(first.lat, first.lon, second.lat, second.lon)
            speed = distance / elapsed
            if speed <= cfg.max_speed_mps:
                continue
            pair = (first.id, second.id)
            if pair in seen:
                continue
            seen.add(pair)
            ratio = speed / cfg.max_speed_mps
            severity = min(0.99, 0.62 + min(0.33, 0.14 * math.log2(max(ratio, 1.0))))
            conflicts.append(
                make_conflict(
                    "impossible_travel",
                    [first.id, second.id],
                    entity,
                    (
                        f"{distance / 1000:.1f} km in {elapsed:.0f}s — "
                        f"{speed * 3.6:.0f} km/h exceeds the "
                        f"{cfg.max_speed_mps * 3.6:.0f} km/h plausibility ceiling."
                    ),
                    severity=severity,
                    t_delta_s=round(elapsed, 3),
                    detected_by="impossible_travel",
                    meta={
                        "distance_m": round(distance, 1),
                        "speed_mps": round(speed, 2),
                        "speed_kmh": round(speed * 3.6, 1),
                        "limit_kmh": round(cfg.max_speed_mps * 3.6, 1),
                    },
                )
            )
            conflicts[-1].sources = _event_sources([first, second])
    return conflicts


def detect_causality(
    events_by_id: dict[str, NormalizedEvent],
    rules: list[Rule],
) -> list[Conflict]:
    """Effect timestamped before its cause (``precedes`` / ``min_gap``).

    A ``max_gap`` violation is an excessive delay rather than reversed causality,
    so it is left to the constraint graph and reported as ``constraint_cycle``.
    O(r) for r rules.
    """
    conflicts: list[Conflict] = []
    for rule in rules:
        if rule.type not in ("precedes", "min_gap"):
            continue
        cause = events_by_id.get(rule.event_a)
        effect = events_by_id.get(rule.event_b)
        if cause is None or effect is None:
            continue
        observed = effect.ts - cause.ts
        required = max(0.0, rule.delta_s)
        if observed >= required:
            continue
        deficit = required - observed
        severity = min(0.98, 0.68 + min(0.28, deficit / max(required, 3600.0) * 0.2))
        record = make_conflict(
            "causality",
            [cause.id, effect.id],
            cause.entity if cause.entity == effect.entity else None,
            (
                f"{rule.type.upper()} rule requires {cause.id} → {effect.id} "
                f"gap ≥ {required:.0f}s; observed {observed:.0f}s "
                f"({deficit:.0f}s before the cause)."
            ),
            severity=severity,
            t_delta_s=round(observed, 3),
            detected_by="causality",
            meta={
                "rule_id": rule.id,
                "rule_type": rule.type,
                "required_gap_s": required,
                "observed_gap_s": round(observed, 3),
                "deficit_s": round(deficit, 3),
            },
        )
        record.sources = _event_sources([cause, effect])
        conflicts.append(record)
    return conflicts


def _nearest_cross_source(
    records: list[NormalizedEvent],
    index: int,
    window_s: float,
    cap: int,
) -> tuple[NormalizedEvent | None, float]:
    """Nearest event of a different source within the time window.

    We expand outward from the target position and stop once time distance
    exceeds the window.  The cap prevents dense bursts from degrading to O(k^2).
    """
    target = records[index]
    best: NormalizedEvent | None = None
    best_gap = window_s
    left = index - 1
    right = index + 1
    steps = 0
    while (left >= 0 or right < len(records)) and steps < cap:
        steps += 1
        if left >= 0:
            peer = records[left]
            gap = target.ts - peer.ts
            if gap > window_s:
                left = -1
            else:
                if peer.source != target.source and peer.device_id != target.device_id:
                    if gap < best_gap:
                        best_gap = gap
                        best = peer
                left -= 1
        if right < len(records):
            peer = records[right]
            gap = peer.ts - target.ts
            if gap > window_s:
                right = len(records)
            else:
                if peer.source != target.source and peer.device_id != target.device_id:
                    if gap < best_gap:
                        best_gap = gap
                        best = peer
                right += 1
    return best, best_gap


def detect_clock_skew(
    index: EventIndex,
    config: DetectionConfig | None = None,
    device_ids: set[str] | None = None,
) -> list[Conflict]:
    """Flag a device whose clock is consistently displaced from peer sources.

    For every device record we locate the nearest same-entity record from a
    *different* source inside a window.  The signed delta is a clock observation.
    A device is flagged only when the median delta exceeds the threshold **and**
    the median absolute deviation is small (a coherent offset, not random
    scheduling drift).

    Complexity: O(n log n) grouping + O(n * w) neighbour scans, w capped at 64.
    """
    cfg = config or DetectionConfig()
    observations: dict[str, list[tuple[float, NormalizedEvent]]] = defaultdict(list)

    target_entities: set[str] | None = None
    if device_ids is not None:
        # Find the small set of entities touched by the affected devices.  This
        # turns an incremental clock check into an O(affected entity) scan.
        target_entities = set()
        for entity in index.entity_names:
            if any(record.device_id in device_ids for record in index.entity_events(entity)):
                target_entities.add(entity)

    scanned_entities = target_entities if target_entities is not None else index.entity_names
    for entity in scanned_entities:
        records = index.entity_events(entity)
        if len(records) < 2:
            continue
        for i, event in enumerate(records):
            if device_ids is not None and event.device_id not in device_ids:
                continue
            peer, _gap = _nearest_cross_source(
                records, i, cfg.clock_window_s, cfg.neighbour_cap
            )
            if peer is None:
                continue
            delta = event.ts - peer.ts
            # Very small deltas are ordinary network/recording latency.
            if abs(delta) < 10.0:
                continue
            observations[event.device_id].append((delta, event))

    conflicts: list[Conflict] = []
    for device_id, samples in sorted(observations.items()):
        if device_ids is not None and device_id not in device_ids:
            continue
        if len(samples) < cfg.clock_min_samples:
            continue
        deltas = sorted(delta for delta, _ in samples)
        med = median(deltas)
        mad = median(sorted(abs(delta - med) for delta in deltas))
        if abs(med) < cfg.clock_skew_threshold_s:
            continue
        if mad > cfg.clock_mad_max_s:
            # Incoherent offsets look like unrelated schedules, not skew.
            continue
        # Keep anchor events close to the estimated offset; cap payload size.
        selected = sorted(
            (sample for sample in samples if abs(sample[0] - med) <= max(5.0, 3 * mad + 2)),
            key=lambda item: abs(item[0] - med),
        )[:8]
        if len(selected) < cfg.clock_min_samples:
            continue
        event_ids = tuple(event.id for _delta, event in selected)
        entity_counts: dict[str, int] = defaultdict(int)
        sources: set[str] = set()
        for _delta, event in selected:
            entity_counts[event.entity] += 1
            sources.add(event.source)
        entity = max(entity_counts, key=entity_counts.get)
        severity = min(0.97, 0.55 + min(0.4, (abs(med) - cfg.clock_skew_threshold_s) / 1800.0))
        conflict = make_conflict(
            "clock_skew",
            event_ids,
            entity,
            (
                f"{device_id} runs {med:+.0f}s from {len(selected)} cross-source anchors "
                f"(MAD {mad:.1f}s) — timestamps cannot be trusted until recalibrated."
            ),
            severity=severity,
            t_delta_s=round(med, 3),
            device_id=device_id,
            detected_by="clock_skew",
            meta={
                "offset_s": round(med, 3),
                "mad_s": round(mad, 3),
                "samples": len(samples),
                "anchors_used": len(selected),
            },
        )
        conflict.sources = tuple(sorted(sources))
        conflicts.append(conflict)
    return conflicts


def run_detectors(
    index: EventIndex,
    rules: list[Rule],
    config: DetectionConfig | None = None,
) -> list[Conflict]:
    """Run detectors a-d and return their combined candidates.

    Constraint-cycle detection lives in ``constraint_graph`` and is merged by
    the engine.  O(n log n + k + r).
    """
    cfg = config or DetectionConfig()
    events_by_id = {event.id: event for event in index.all_events()}
    conflicts: list[Conflict] = []
    conflicts.extend(detect_simultaneity(index, cfg))
    conflicts.extend(detect_impossible_travel(index, cfg))
    conflicts.extend(detect_causality(events_by_id, rules))
    conflicts.extend(detect_clock_skew(index, cfg))
    return conflicts
