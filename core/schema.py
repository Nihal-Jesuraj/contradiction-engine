"""Core data contracts shared by every ChronoClash algorithm.

The web layer converts Pydantic payloads into these plain dataclasses.  Keeping
the core free of Pydantic means the algorithms can be used in a notebook, a CLI
benchmark, or a test without pulling in a web framework.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

SOURCES: tuple[str, ...] = ("cctv", "call", "gps", "bank", "device", "witness")

# Prior reliability attached to each evidence family. Individual records may
# override this with their own reliability field.
SOURCE_RELIABILITY: dict[str, float] = {
    "cctv": 0.90,
    "call": 0.66,
    "gps": 0.86,
    "bank": 0.95,
    "device": 0.80,
    "witness": 0.56,
}

RULE_TYPES: tuple[str, ...] = ("precedes", "min_gap", "max_gap")

CONFLICT_KINDS: tuple[str, ...] = (
    "impossible_simultaneity",
    "impossible_travel",
    "causality",
    "clock_skew",
    "constraint_cycle",
)


@dataclass(frozen=True, slots=True)
class Event:
    """A raw evidence record as supplied by an investigator.

    ``timestamp`` is an ISO-8601 string.  It may carry any UTC offset; the
    normalizer converts it to UTC before any temporal reasoning happens.
    """

    id: str
    timestamp: str
    duration_s: float
    entity: str
    lat: float
    lon: float
    source: str
    device_id: str
    action: str
    reliability: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "duration_s": self.duration_s,
            "entity": self.entity,
            "lat": self.lat,
            "lon": self.lon,
            "source": self.source,
            "device_id": self.device_id,
            "action": self.action,
            "reliability": self.reliability,
        }


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """An event whose clock has been corrected to UTC epoch seconds."""

    id: str
    ts: float
    timestamp: str
    original_timestamp: str
    duration_s: float
    entity: str
    lat: float
    lon: float
    source: str
    device_id: str
    action: str
    reliability: float
    clock_offset_s: float = 0.0

    @property
    def end_ts(self) -> float:
        # Zero-length events still need a non-inverted interval.
        return self.ts + max(0.0, self.duration_s)

    @property
    def interval(self) -> tuple[float, float]:
        return (self.ts, self.end_ts)

    def at_time(self, ts: float) -> "NormalizedEvent":
        """Return a copy with a different corrected timestamp."""
        return replace(self, ts=ts, timestamp=iso_utc(ts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "original_timestamp": self.original_timestamp,
            "ts": round(self.ts, 6),
            "duration_s": self.duration_s,
            "end_ts": round(self.end_ts, 6),
            "entity": self.entity,
            "lat": self.lat,
            "lon": self.lon,
            "source": self.source,
            "device_id": self.device_id,
            "action": self.action,
            "reliability": self.reliability,
            "clock_offset_s": self.clock_offset_s,
        }


@dataclass(frozen=True, slots=True)
class Rule:
    """A temporal rule relating two events."""

    type: str
    event_a: str
    event_b: str
    delta_s: float
    id: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.type not in RULE_TYPES:
            raise ValueError(f"unknown rule type: {self.type!r}")
        if not self.id:
            digest = hashlib.blake2s(
                f"{self.type}|{self.event_a}|{self.event_b}|{self.delta_s}".encode(),
                digest_size=5,
            ).hexdigest().upper()
            object.__setattr__(self, "id", f"RUL-{digest}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "event_a": self.event_a,
            "event_b": self.event_b,
            "delta_s": self.delta_s,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class GroundTruth:
    """A planted contradiction, used for precision/recall benchmarking."""

    type: str
    event_ids: tuple[str, ...] = ()
    device_id: str | None = None
    note: str = ""

    def key(self) -> tuple[str, tuple[str, ...] | str]:
        if self.type == "clock_skew" and self.device_id:
            return ("clock_skew", self.device_id)
        return (self.type, tuple(sorted(self.event_ids)))


@dataclass(slots=True)
class Conflict:
    """A detected contradiction."""

    id: str
    kind: str
    severity: float
    event_ids: tuple[str, ...]
    entity: str | None
    detail: str
    t_delta_s: float = 0.0
    device_id: str | None = None
    confidence: float = 0.0
    corroboration: int = 0
    sources: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)
    detected_by: tuple[str, ...] = ()

    def signature(self) -> str:
        """A dedupe key: two detectors must not double-report one event set."""
        if self.kind == "clock_skew" and self.device_id:
            return f"clock_skew:{self.device_id}"
        return "events:" + ",".join(sorted(self.event_ids))

    def to_dict(self, include_meta: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "severity": round(self.severity, 4),
            "event_ids": list(self.event_ids),
            "entity": self.entity,
            "device_id": self.device_id,
            "detail": self.detail,
            "t_delta_s": round(self.t_delta_s, 3),
            "confidence": round(self.confidence, 4),
            "corroboration": self.corroboration,
            "sources": list(self.sources),
            "detected_by": list(self.detected_by),
        }
        if include_meta:
            out["meta"] = self.meta
        return out


def make_conflict(
    kind: str,
    event_ids: list[str] | tuple[str, ...],
    entity: str | None,
    detail: str,
    *,
    severity: float = 0.7,
    t_delta_s: float = 0.0,
    device_id: str | None = None,
    detected_by: str = "",
    meta: dict[str, Any] | None = None,
) -> Conflict:
    """Create a conflict with a deterministic, shareable identifier."""
    ordered = tuple(event_ids)
    digest = hashlib.blake2s(
        f"{kind}|{'|'.join(sorted(ordered))}|{device_id or ''}".encode(),
        digest_size=6,
    ).hexdigest().upper()
    return Conflict(
        id=f"CFL-{digest}",
        kind=kind,
        severity=max(0.0, min(1.0, severity)),
        event_ids=ordered,
        entity=entity,
        device_id=device_id,
        detail=detail,
        t_delta_s=t_delta_s,
        meta=meta or {},
        detected_by=(detected_by,) if detected_by else (),
    )


def iso_utc(ts: float) -> str:
    """Epoch seconds -> canonical UTC ISO-8601 (millisecond precision)."""
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
