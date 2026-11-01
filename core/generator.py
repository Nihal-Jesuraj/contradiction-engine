"""Synthetic evidence generator with planted ground truth.

The generator produces *clean* records that are deliberately spaced on each
entity's timeline, then appends isolated planted contradictions with dedicated
subjects.  This gives the benchmark a trustworthy precision/recall denominator
without making the clean data unrealistically tidy.

Run:
    python -m core.generator --events 500 --contradictions 12 --out data/sample_case.jsonl

Complexity: O(n) generation, O(n log n) final ID sort, O(n) space.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .schema import (
    Event,
    GroundTruth,
    Rule,
    SOURCE_RELIABILITY,
    iso_utc,
)

ACTIONS: dict[str, list[str]] = {
    "cctv": [
        "PERIMETER_APPROACH",
        "DOORWAY_ENTRY",
        "VEHICLE_DEPARTURE",
        "CORRIDOR_TRANSIT",
        "PLATE_READ",
    ],
    "call": [
        "OUTBOUND_CALL",
        "INBOUND_CALL",
        "VOICEMAIL",
        "CELL_HANDOFF",
        "SMS_EVENT",
    ],
    "gps": [
        "POSITION_FIX",
        "ROUTE_DEVIATION",
        "STOP_DETECTED",
        "GEOFENCE_EXIT",
        "GEOFENCE_ENTRY",
    ],
    "bank": [
        "CARD_PRESENT",
        "ATM_WITHDRAWAL",
        "WIRE_TRANSFER",
        "CONTACTLESS_TAP",
        "ACCOUNT_LOGIN",
    ],
    "device": [
        "DEVICE_UNLOCK",
        "APP_FOREGROUND",
        "NETWORK_JOIN",
        "PAIRING_EVENT",
        "PUSH_RECEIVED",
    ],
    "witness": [
        "STATEMENT_LOGGED",
        "SIGHTING_REPORTED",
        "PHONE_INTERVIEW",
        "PHOTO_IDENTIFICATION",
    ],
}

SOURCE_WEIGHTS = {
    "cctv": 0.24,
    "call": 0.18,
    "gps": 0.20,
    "bank": 0.12,
    "device": 0.18,
    "witness": 0.08,
}

# A fictional urban area.  Coordinates are real-numbered but the subject and
# case identities are completely synthetic.
CITY_LAT = 51.5074
CITY_LON = -0.1278
LAT_SPAN = 0.11
LON_SPAN = 0.16


@dataclass(slots=True)
class GeneratorConfig:
    n_events: int = 500
    contradictions: int = 12
    seed: int = 424242
    span_days: float = 12.0
    entities: int | None = None
    corroboration_ratio: float = 0.22
    start_utc: str = "2026-09-18T00:00:00Z"


@dataclass(slots=True)
class GeneratedDataset:
    events: list[Event]
    rules: list[Rule]
    ground_truth: list[GroundTruth]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "events": [event.to_dict() for event in self.events],
            "rules": [rule.to_dict() for rule in self.rules],
            "ground_truth": [
                {
                    "type": truth.type,
                    "event_ids": list(truth.event_ids),
                    "device_id": truth.device_id,
                    "note": truth.note,
                }
                for truth in self.ground_truth
            ],
        }


def _reliability(source: str, rng: random.Random) -> float:
    base = SOURCE_RELIABILITY[source]
    return max(0.25, min(0.99, base + rng.uniform(-0.055, 0.055)))


def _device_id(source: str, entity_index: int, rng: random.Random) -> str:
    prefix = {
        "cctv": "CAM",
        "call": "TEL",
        "gps": "GPS",
        "bank": "TRM",
        "device": "MOB",
        "witness": "WIT",
    }[source]
    suffix = entity_index if source != "witness" else rng.randint(1, 19)
    return f"{prefix}-{suffix:03d}"


def _entity_count(n_events: int, requested: int | None) -> int:
    if requested is not None:
        return max(1, requested)
    # Keep the status grid meaningful without exploding the UI.
    estimated = int(math.sqrt(max(64, n_events)) / 2.0)
    return max(6, min(96, estimated))


def _source_cycle(rng: random.Random, length: int) -> list[str]:
    sources = list(SOURCE_WEIGHTS)
    weights = [SOURCE_WEIGHTS[s] for s in sources]
    return rng.choices(sources, weights=weights, k=length)


def _iso_from_epoch(ts: float) -> str:
    return iso_utc(ts)


def generate_dataset(config: GeneratorConfig | None = None) -> GeneratedDataset:
    """Generate events, rules, and planted contradictions.

    Steps:
      1. reserve slots for planted two-record anomalies
      2. generate evenly spaced clean per-entity timelines (O(n))
      3. add corroborating cross-source records for ~22% of clean records
      4. choose skewed devices and clone all their records twice so the
         detector can resolve *which* clock is wrong (O(n))
      5. append isolated anomalies with dedicated subjects
      6. add satisfied control rules so constraint-graph tests are not just
         cycle tests.

    O(n log n) due to the final deterministic sort; O(n) space.
    """
    cfg = config or GeneratorConfig()
    if cfg.n_events < 20:
        raise ValueError("n_events must be at least 20")
    rng = random.Random(cfg.seed)
    entity_total = _entity_count(cfg.n_events, cfg.entities)
    start = datetime.fromisoformat(cfg.start_utc.replace("Z", "+00:00")).timestamp()
    span = cfg.span_days * 86400.0
    end = start + span

    total_plants = max(0, min(cfg.contradictions, max(1, cfg.n_events // 20)))
    skew_count = 0
    if total_plants >= 4 and entity_total >= 2:
        skew_count = min(3, max(1, total_plants // 5))
    non_skew_plants = total_plants - skew_count
    planted_event_count = non_skew_plants * 2
    skew_records_per_subject = 6  # 6 skewed records + 2 peers each
    skew_event_count = skew_count * skew_records_per_subject * 3
    available = max(6, cfg.n_events - planted_event_count - skew_event_count)
    base_count = max(2, int(round(available / (1.0 + cfg.corroboration_ratio))))
    corrob_count = max(0, available - base_count)

    events: list[Event] = []
    entity_names = [f"SUBJ-{i + 1:03d}" for i in range(entity_total)]
    entity_homes = {
        name: (
            CITY_LAT + rng.uniform(-LAT_SPAN / 2, LAT_SPAN / 2),
            CITY_LON + rng.uniform(-LON_SPAN / 2, LON_SPAN / 2),
        )
        for name in entity_names
    }
    entity_numbers = {name: i + 1 for i, name in enumerate(entity_names)}
    per_entity = [base_count // entity_total] * entity_total
    for i in range(base_count % entity_total):
        per_entity[i] += 1

    sources_by_entity: dict[str, list[str]] = {}
    event_counter = 0

    def next_id(prefix: str = "EV") -> str:
        nonlocal event_counter
        event_counter += 1
        return f"{prefix}-{event_counter:08d}"

    # --- clean base timeline ------------------------------------------------
    for entity_index, entity in enumerate(entity_names):
        count = per_entity[entity_index]
        if count <= 0:
            continue
        step = span / (count + 1)
        sources = _source_cycle(rng, count)
        sources_by_entity[entity] = sources
        home_lat, home_lon = entity_homes[entity]
        lat, lon = home_lat, home_lon
        for i in range(count):
            t = start + step * (i + 1) + rng.uniform(-step * 0.12, step * 0.12)
            # Small local movement.  The step is chosen so adjacent records are
            # many minutes apart even with a small jitter.
            lat += rng.uniform(-0.0035, 0.0035)
            lon += rng.uniform(-0.0055, 0.0055)
            lat = max(CITY_LAT - LAT_SPAN, min(CITY_LAT + LAT_SPAN, lat))
            lon = max(CITY_LON - LON_SPAN, min(CITY_LON + LON_SPAN, lon))
            source = sources[i]
            duration = min(rng.uniform(90.0, 620.0), step * 0.32)
            events.append(
                Event(
                    id=next_id("EV"),
                    timestamp=_iso_from_epoch(t),
                    duration_s=round(duration, 1),
                    entity=entity,
                    lat=round(lat, 6),
                    lon=round(lon, 6),
                    source=source,
                    device_id=_device_id(source, entity_index + 1, rng),
                    action=rng.choice(ACTIONS[source]),
                    reliability=round(_reliability(source, rng), 3),
                )
            )

    # --- corroborating records ---------------------------------------------
    clones: list[Event] = []
    clone_counter = 0

    def clone_event(original: Event, source: str) -> Event:
        nonlocal clone_counter
        clone_counter += 1
        entity_number = entity_numbers.get(original.entity, 0)
        return Event(
            id=f"COR-{clone_counter:08d}",
            timestamp=_iso_from_epoch(
                datetime.fromisoformat(original.timestamp.replace("Z", "+00:00")).timestamp()
                + rng.uniform(-2.0, 2.0)
            ),
            duration_s=original.duration_s,
            entity=original.entity,
            lat=original.lat,
            lon=original.lon,
            source=source,
            device_id=_device_id(source, entity_number, rng),
            action=original.action,
            reliability=round(_reliability(source, rng), 3),
        )

    if corrob_count and events:
        for _ in range(corrob_count):
            original = rng.choice(events)
            options = [s for s in SOURCE_WEIGHTS if s != original.source]
            clones.append(clone_event(original, rng.choice(options)))
    events.extend(clones)

    # --- dedicated clock-skew subjects -------------------------------------
    # A skew subject lives at one location and contains one device that is
    # retimed plus two independent peer devices left on true UTC.  Isolating
    # the experiment prevents a large offset from creating spurious travel or
    # simultaneity conflicts in otherwise clean lanes, while the two peers let
    # the detector decide *which* clock is wrong instead of accusing both sides
    # of a disagreement symmetrically.
    skew_truth: list[GroundTruth] = []
    skew_devices: list[tuple[str, list[Event], float]] = []
    skew_peer_records = 0
    for skew_index in range(skew_count):
        entity = f"SUBJ-C{skew_index + 1:02d}"
        lat = round(CITY_LAT + rng.uniform(-LAT_SPAN / 2, LAT_SPAN / 2), 6)
        lon = round(CITY_LON + rng.uniform(-LON_SPAN / 2, LON_SPAN / 2), 6)
        offset = rng.choice([300.0, 420.0, 540.0, 660.0, 780.0])
        if rng.random() < 0.25:
            offset = -offset
        skew_device = f"CAM-S{skew_index + 1:02d}"
        peer_specs = [
            ("gps", f"GPS-S{skew_index + 1:02d}"),
            ("device", f"MOB-S{skew_index + 1:02d}"),
        ]
        base_time = start + span * (0.18 + 0.07 * skew_index)
        spacing = max(7200.0, abs(offset) * 4.0, span * 0.045)
        if base_time + spacing * (skew_records_per_subject - 1) > end - 3600:
            base_time = max(start + 3600, end - spacing * (skew_records_per_subject - 1) - 3600)
        shifted_ids: list[str] = []
        for i in range(skew_records_per_subject):
            true_ts = base_time + spacing * i
            shared = dict(
                duration_s=round(rng.uniform(40.0, 120.0), 1),
                entity=entity,
                lat=lat,
                lon=lon,
                reliability=0.9,
            )
            cause_record = Event(
                id=next_id("SKW"),
                timestamp=_iso_from_epoch(true_ts + offset),
                source="cctv",
                device_id=skew_device,
                action="DOORWAY_ENTRY",
                **shared,
            )
            events.append(cause_record)
            shifted_ids.append(cause_record.id)
            for peer_source, peer_device in peer_specs:
                peer = Event(
                    id=next_id("PEER"),
                    timestamp=_iso_from_epoch(true_ts + rng.uniform(-1.2, 1.2)),
                    source=peer_source,
                    device_id=peer_device,
                    action=rng.choice(ACTIONS[peer_source]),
                    **shared,
                )
                events.append(peer)
                skew_peer_records += 1
        skew_devices.append((skew_device, [cause_record], offset))
        skew_truth.append(
            GroundTruth(
                type="clock_skew",
                event_ids=tuple(shifted_ids),
                device_id=skew_device,
                note=f"{skew_device} shifted by {offset:+.0f}s against two peers",
            )
        )

    # --- planted non-skew anomalies ----------------------------------------
    rules: list[Rule] = []
    truth: list[GroundTruth] = list(skew_truth)
    planted_types = ["impossible_simultaneity", "impossible_travel", "causality"]
    for plant_index in range(non_skew_plants):
        kind = planted_types[plant_index % len(planted_types)]
        entity = f"SUBJ-P{plant_index + 1:02d}"
        when = start + span * rng.uniform(0.12, 0.88)
        base_lat, base_lon = (
            CITY_LAT + rng.uniform(-LAT_SPAN / 2, LAT_SPAN / 2),
            CITY_LON + rng.uniform(-LON_SPAN / 2, LON_SPAN / 2),
        )
        if kind == "impossible_simultaneity":
            source_a, source_b = "cctv", "gps"
            first = Event(
                id=next_id("ANO"),
                timestamp=_iso_from_epoch(when),
                duration_s=round(rng.uniform(240, 520), 1),
                entity=entity,
                lat=round(base_lat, 6),
                lon=round(base_lon, 6),
                source=source_a,
                device_id=f"CAM-9{plant_index:02d}",
                action="PERIMETER_APPROACH",
                reliability=0.92,
            )
            second = Event(
                id=next_id("ANO"),
                # Same start, different duration: this is pure simultaneity,
                # not an impossible-travel duplicate.
                timestamp=_iso_from_epoch(when),
                duration_s=round(rng.uniform(240, 520), 1),
                entity=entity,
                lat=round(base_lat + 0.19, 6),
                lon=round(base_lon - 0.08, 6),
                source=source_b,
                device_id=f"GPS-9{plant_index:02d}",
                action="POSITION_FIX",
                reliability=0.87,
            )
            events.extend([first, second])
            truth.append(
                GroundTruth(
                    type=kind,
                    event_ids=(first.id, second.id),
                    note="overlapping intervals, ~23 km separation",
                )
            )
        elif kind == "impossible_travel":
            first = Event(
                id=next_id("ANO"),
                timestamp=_iso_from_epoch(when),
                duration_s=30.0,
                entity=entity,
                lat=round(base_lat, 6),
                lon=round(base_lon, 6),
                source="gps",
                device_id=f"GPS-8{plant_index:02d}",
                action="POSITION_FIX",
                reliability=0.86,
            )
            second = Event(
                id=next_id("ANO"),
                timestamp=_iso_from_epoch(when + rng.uniform(45, 100)),
                duration_s=30.0,
                entity=entity,
                lat=round(base_lat + 0.36, 6),
                lon=round(base_lon + 0.04, 6),
                source="call",
                device_id=f"TEL-8{plant_index:02d}",
                action="CELL_HANDOFF",
                reliability=0.68,
            )
            events.extend([first, second])
            truth.append(
                GroundTruth(
                    type=kind,
                    event_ids=(first.id, second.id),
                    note="~40 km in under two minutes",
                )
            )
        else:
            effect = Event(
                id=next_id("ANO"),
                timestamp=_iso_from_epoch(when),
                duration_s=20.0,
                entity=entity,
                lat=round(base_lat, 6),
                lon=round(base_lon, 6),
                source="bank",
                device_id=f"TRM-7{plant_index:02d}",
                action="WIRE_TRANSFER",
                reliability=0.95,
            )
            cause = Event(
                id=next_id("ANO"),
                timestamp=_iso_from_epoch(when + rng.uniform(90, 240)),
                duration_s=20.0,
                entity=entity,
                lat=round(base_lat, 6),
                lon=round(base_lon, 6),
                source="device",
                device_id=f"MOB-7{plant_index:02d}",
                action="DEVICE_UNLOCK",
                reliability=0.84,
            )
            events.extend([effect, cause])
            rules.append(
                Rule(
                    type="min_gap",
                    event_a=cause.id,
                    event_b=effect.id,
                    delta_s=60.0,
                    note="authorisation must precede transfer",
                )
            )
            truth.append(
                GroundTruth(
                    type="causality",
                    event_ids=(cause.id, effect.id),
                    note="effect timestamped before cause",
                )
            )

    # --- satisfied control rules -------------------------------------------
    # These exercise the constraint graph without creating cycles.
    base_sorted = sorted(
        [event for event in events if event.entity.startswith("SUBJ-") and event.id.startswith("EV-")],
        key=lambda e: (e.entity, e.timestamp, e.id),
    )
    if len(base_sorted) >= 4:
        for i in range(0, min(len(base_sorted) - 1, max(3, total_plants // 2))):
            a, b = base_sorted[i], base_sorted[(i + 3) % len(base_sorted)]
            if a.entity != b.entity:
                continue
            ta = datetime.fromisoformat(a.timestamp.replace("Z", "+00:00")).timestamp()
            tb = datetime.fromisoformat(b.timestamp.replace("Z", "+00:00")).timestamp()
            if tb <= ta:
                continue
            if i % 3 == 0:
                rules.append(
                    Rule(
                        type="max_gap",
                        event_a=a.id,
                        event_b=b.id,
                        delta_s=(tb - ta) + 3600.0,
                        note="control: generous maximum interval",
                    )
                )
            else:
                rules.append(
                    Rule(
                        type="precedes",
                        event_a=a.id,
                        event_b=b.id,
                        delta_s=0.0,
                        note="control: observed order is consistent",
                    )
                )

    # Deduplicate and sort for reproducible artefacts.
    unique_events: dict[str, Event] = {event.id: event for event in events}
    events = list(unique_events.values())
    events.sort(key=lambda e: (e.timestamp, e.id))
    rules.sort(key=lambda r: r.id)
    if len(events) > cfg.n_events:
        protected = {event_id for item in truth for event_id in item.event_ids}
        trimmed: list[Event] = []
        for event in events:
            if len(trimmed) >= cfg.n_events:
                if event.id in protected:
                    # Keep protected events; remove a non-protected record later.
                    replace_index = next(
                        (i for i, e in enumerate(trimmed) if e.id not in protected),
                        None,
                    )
                    if replace_index is not None:
                        trimmed[replace_index] = event
                continue
            trimmed.append(event)
        events = sorted(trimmed, key=lambda e: (e.timestamp, e.id))

    meta = {
        "name": f"SYNTHETIC-CASE-{cfg.seed}",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": cfg.seed,
        "event_count": len(events),
        "entity_count": len({event.entity for event in events}),
        "rule_count": len(rules),
        "planted_contradictions": len(truth),
        "requested_events": cfg.n_events,
        "span_days": cfg.span_days,
        "start_utc": iso_utc(start),
        "end_utc": iso_utc(end),
        "corroboration_records": len(clones) + skew_peer_records,
        "skew_devices": [device for device, _records, _offset in skew_devices],
        "ground_truth_breakdown": {
            kind: sum(1 for item in truth if item.type == kind)
            for kind in (
                "impossible_simultaneity",
                "impossible_travel",
                "causality",
                "clock_skew",
            )
        },
    }
    return GeneratedDataset(events=events, rules=rules, ground_truth=truth, meta=meta)


def write_dataset(dataset: GeneratedDataset, path: str | Path, fmt: str | None = None) -> Path:
    """Write JSON, JSONL, or CSV (events only; use JSON for rules/truth).

    O(n) time/space.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    chosen = (fmt or target.suffix.lstrip(".")).lower()
    if chosen == "jsonl":
        with target.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"record_type": "meta", **dataset.meta}) + "\n")
            for rule in dataset.rules:
                handle.write(json.dumps({"record_type": "rule", **rule.to_dict()}) + "\n")
            for truth in dataset.ground_truth:
                handle.write(
                    json.dumps(
                        {
                            "record_type": "ground_truth",
                            "type": truth.type,
                            "event_ids": list(truth.event_ids),
                            "device_id": truth.device_id,
                            "note": truth.note,
                        }
                    )
                    + "\n"
                )
            for event in dataset.events:
                handle.write(json.dumps({"record_type": "event", **event.to_dict()}) + "\n")
    elif chosen == "csv":
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(Event.__dataclass_fields__))
            writer.writeheader()
            for event in dataset.events:
                writer.writerow(event.to_dict())
    else:
        target.write_text(json.dumps(dataset.to_dict(), indent=2), encoding="utf-8")
    return target


def _main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic ChronoClash evidence")
    parser.add_argument("--events", type=int, default=500)
    parser.add_argument("--contradictions", type=int, default=12)
    parser.add_argument("--seed", type=int, default=424242)
    parser.add_argument("--days", type=float, default=12.0)
    parser.add_argument("--entities", type=int, default=None)
    parser.add_argument("--out", type=str, default="data/sample_case.jsonl")
    parser.add_argument("--format", type=str, default=None, choices=["json", "jsonl", "csv"])
    args = parser.parse_args()
    dataset = generate_dataset(
        GeneratorConfig(
            n_events=args.events,
            contradictions=args.contradictions,
            seed=args.seed,
            span_days=args.days,
            entities=args.entities,
        )
    )
    path = write_dataset(dataset, args.out, args.format)
    print(
        json.dumps(
            {
                "path": str(path),
                "events": len(dataset.events),
                "rules": len(dataset.rules),
                "ground_truth": len(dataset.ground_truth),
                "meta": dataset.meta,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    _main()
