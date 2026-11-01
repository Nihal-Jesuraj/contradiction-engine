"""CSV / JSONL / JSON ingestion without third-party parsers."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.normalize import parse_timestamp
from core.schema import Event, GroundTruth, Rule, SOURCES


class IngestError(ValueError):
    """Raised when an uploaded file cannot be parsed."""


@dataclass(slots=True)
class ParsedDataset:
    events: list[Event]
    rules: list[Rule] = field(default_factory=list)
    ground_truth: list[GroundTruth] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    name: str = "UPLOADED CASE"

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "events": len(self.events),
            "rules": len(self.rules),
            "ground_truth": len(self.ground_truth),
            "warnings": self.warnings,
        }


def _num(value: Any, default: float | None = None) -> float:
    if value is None or value == "":
        if default is None:
            raise IngestError("missing numeric value")
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise IngestError(f"invalid number: {value!r}") from exc


def _event_from_mapping(
    row: dict[str, Any],
    fallback_id: str,
    *,
    line: int | None = None,
) -> Event:
    where = f"line {line}: " if line else ""
    timestamp = row.get("timestamp") or row.get("time")
    if not timestamp:
        raise IngestError(f"{where}missing timestamp")
    try:
        parse_timestamp(str(timestamp))
    except ValueError as exc:
        raise IngestError(f"{where}{exc}") from exc
    source = str(row.get("source", "")).strip().lower()
    if source not in SOURCES:
        raise IngestError(f"{where}unknown source {source!r}; expected one of {SOURCES}")
    entity = str(row.get("entity", "")).strip().upper()
    if not entity:
        raise IngestError(f"{where}missing entity")
    event_id = str(row.get("id") or fallback_id).strip()
    return Event(
        id=event_id,
        timestamp=str(timestamp),
        duration_s=max(0.0, _num(row.get("duration_s", row.get("duration", 0)), 0.0)),
        entity=entity,
        lat=_num(row.get("lat")),
        lon=_num(row.get("lon")),
        source=source,
        device_id=str(row.get("device_id") or f"DEV-{source.upper()}").strip().upper(),
        action=str(row.get("action") or "UNKNOWN"),
        reliability=max(
            0.0, min(1.0, _num(row.get("reliability", 0.7), 0.7))
        ),
    )


def _rule_from_mapping(row: dict[str, Any], *, line: int | None = None) -> Rule:
    where = f"line {line}: " if line else ""
    try:
        return Rule(
            type=str(row.get("type", "")).strip(),
            event_a=str(row.get("event_a", "")).strip(),
            event_b=str(row.get("event_b", "")).strip(),
            delta_s=_num(row.get("delta_s", 0), 0.0),
            id=str(row.get("id") or ""),
            note=str(row.get("note") or ""),
        )
    except ValueError as exc:
        raise IngestError(f"{where}{exc}") from exc


def _truth_from_mapping(row: dict[str, Any]) -> GroundTruth:
    ids = row.get("event_ids") or []
    if isinstance(ids, str):
        ids = [part.strip() for part in ids.split(";") if part.strip()]
    return GroundTruth(
        type=str(row.get("type", "")),
        event_ids=tuple(str(item) for item in ids),
        device_id=row.get("device_id"),
        note=str(row.get("note") or ""),
    )


def _parse_records(records: list[dict[str, Any]], name: str) -> ParsedDataset:
    events: list[Event] = []
    rules: list[Rule] = []
    truth: list[GroundTruth] = []
    meta: dict[str, Any] = {}
    warnings: list[str] = []
    seen_ids: set[str] = set()
    pending_events: list[tuple[int, dict[str, Any]]] = []
    pending_rules: list[dict[str, Any]] = []

    for index, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            warnings.append(f"line {index}: ignored non-object record")
            continue
        record_type = str(row.get("record_type") or row.get("kind") or "").lower()
        if record_type == "meta":
            meta.update({k: v for k, v in row.items() if k != "record_type"})
        elif record_type == "rule" or ("event_a" in row and "event_b" in row and "timestamp" not in row):
            pending_rules.append(row)
        elif record_type == "ground_truth":
            truth.append(_truth_from_mapping(row))
        elif record_type in ("", "event") and ("timestamp" in row or "time" in row):
            pending_events.append((index, row))
        elif record_type in ("", "rule"):
            pending_rules.append(row)
        else:
            warnings.append(f"line {index}: ignored record of type {record_type!r}")

    for index, row in pending_events:
        fallback = f"UPL-{len(events) + 1:08d}"
        try:
            event = _event_from_mapping(row, fallback, line=index)
        except IngestError as exc:
            warnings.append(str(exc))
            continue
        if event.id in seen_ids:
            warnings.append(f"line {index}: duplicate event id {event.id} ignored")
            continue
        seen_ids.add(event.id)
        events.append(event)

    for row in pending_rules:
        try:
            rule = _rule_from_mapping(row)
        except IngestError as exc:
            warnings.append(str(exc))
            continue
        if not rule.event_a or not rule.event_b:
            warnings.append(f"rule {rule.id} has an empty endpoint; ignored")
            continue
        rules.append(rule)

    known = {event.id for event in events}
    missing = {
        endpoint
        for rule in rules
        for endpoint in (rule.event_a, rule.event_b)
        if endpoint not in known
    }
    if missing:
        warnings.append(
            f"{len(missing)} rule endpoint(s) not present in this file; "
            "rules will be ignored until those events are ingested"
        )

    if not events and not rules:
        raise IngestError("file contained no usable events or rules")
    return ParsedDataset(
        events=events,
        rules=rules,
        ground_truth=truth,
        meta=meta,
        warnings=warnings[:50],
        name=str(meta.get("name") or name),
    )


def parse_upload(filename: str, raw: bytes) -> ParsedDataset:
    """Parse CSV, JSONL, or JSON bytes.

    Complexity: O(size of file) time/space.  The whole upload is materialized
    because the engine is in-memory by design.
    """
    suffix = Path(filename).suffix.lower()
    if not raw:
        raise IngestError("uploaded file is empty")
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        if suffix == ".csv":
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                raise IngestError("CSV has no header row")
            rows = [dict(row) for row in reader]
            return _parse_records(rows, Path(filename).stem)
        if suffix in (".jsonl", ".ndjson"):
            rows = []
            for line_number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rows.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise IngestError(f"line {line_number}: invalid JSON ({exc.msg})") from exc
            return _parse_records(rows, Path(filename).stem)
        payload = json.loads(text)
        if isinstance(payload, list):
            return _parse_records(payload, Path(filename).stem)
        if isinstance(payload, dict):
            meta = payload.get("meta") or {}
            name = str(meta.get("name") or Path(filename).stem)
            records: list[dict[str, Any]] = []
            if meta:
                records.append({"record_type": "meta", **meta})
            for event in payload.get("events") or []:
                records.append({"record_type": "event", **event})
            for rule in payload.get("rules") or []:
                records.append({"record_type": "rule", **rule})
            for truth in payload.get("ground_truth") or []:
                records.append({"record_type": "ground_truth", **truth})
            return _parse_records(records, name)
        raise IngestError("JSON root must be an object or array")
    except json.JSONDecodeError as exc:
        raise IngestError(f"invalid JSON: {exc.msg}") from exc
    except UnicodeDecodeError as exc:  # pragma: no cover - decode uses replace
        raise IngestError("file is not valid UTF-8") from exc


def load_dataset_file(path: str | Path) -> ParsedDataset:
    target = Path(path)
    return parse_upload(target.name, target.read_bytes())


__all__ = ["ParsedDataset", "IngestError", "parse_upload", "load_dataset_file"]
