"""Stateful in-memory forensic engine.

The engine owns ingestion, normalization, indexing, analysis, and export.  It is
web-framework agnostic apart from being called by the FastAPI routes.  Every
state transition is guarded by an RLock because FastAPI sync endpoints run in a
thread pool.

The incremental path is genuinely incremental: only newly ingested records and
their neighbourhoods are re-detected, and only the constraint subgraph
reachable from newly added rule edges is re-relaxed.
"""

from __future__ import annotations

import hashlib
import resource
import sys
import threading
import time
import tracemalloc
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.constraint_graph import (
    CycleResult,
    IncrementalConstraintGraph,
    bellman_ford,
)
from core.detectors import (
    DetectionConfig,
    detect_causality,
    detect_clock_skew,
    detect_impossible_travel,
    detect_simultaneity,
    run_detectors,
)
from core.explain import explain_conflict
from core.gaps import find_gaps
from core.generator import GeneratorConfig, generate_dataset, write_dataset
from core.index import EventIndex
from core.normalize import normalize_event
from core.ranking import score_conflicts, top_k
from core.schema import (
    SOURCE_RELIABILITY,
    SOURCES,
    Conflict,
    Event,
    GroundTruth,
    NormalizedEvent,
    Rule,
    iso_utc,
)

from .io import IngestError, ParsedDataset, load_dataset_file, parse_upload

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "backend" / "data"
SAMPLE_PATH = DATA_DIR / "sample_case.jsonl"

KIND_RANK = {
    "constraint_cycle": 1,
    "impossible_travel": 2,
    "impossible_simultaneity": 3,
    "causality": 4,
    "clock_skew": 5,
}


def _rss_mb() -> float:
    """Peak resident set size in MB (macOS reports bytes, Linux kilobytes)."""
    usage = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        usage /= 1024.0 * 1024.0
    else:
        usage /= 1024.0
    return round(usage, 2)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _memory_tracemalloc() -> float:
    current, peak = tracemalloc.get_traced_memory()
    return round(peak / (1024 * 1024), 3)


class ChronoEngine:
    """In-memory dataset + analysis state."""

    def __init__(self, config: DetectionConfig | None = None) -> None:
        self.config = config or DetectionConfig()
        self._lock = threading.RLock()
        self.analyst = "ANALYST-07 // N. HALE"
        self.case_id = "CC-0000-0000"
        self.dataset_name = "NO DATASET"
        self.dataset_meta: dict[str, Any] = {}
        self.raw_events: dict[str, Event] = {}
        self.normalized: dict[str, NormalizedEvent] = {}
        self.rules: list[Rule] = []
        self.ground_truth: list[GroundTruth] = []
        self.offsets: dict[str, float] = {}
        self.index = EventIndex()
        self.conflicts: list[Conflict] = []
        self.incremental_graph = IncrementalConstraintGraph()
        self.pending_events: set[str] = set()
        self.pending_rules: set[str] = set()
        self.last_mode = "idle"
        self.last_analysis_ms = 0.0
        self.last_events_per_sec = 0.0
        self.last_analysis_at: str | None = None
        self.last_new_conflicts: list[str] = []
        self.analysis_runs = 0
        self._has_analysis = False
        self._source_counts: dict[str, int] = {source: 0 for source in SOURCES}
        self._conflict_eval: dict[str, Any] | None = None
        self._last_memory_mb = _rss_mb()

    # ------------------------------------------------------------------ load
    def bootstrap(self) -> None:
        """Load the bundled case (or generate it) so the HUD is never empty."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if SAMPLE_PATH.exists():
            parsed = load_dataset_file(SAMPLE_PATH)
        else:
            dataset = generate_dataset(
                GeneratorConfig(n_events=620, contradictions=16, seed=7, span_days=9.0)
            )
            write_dataset(dataset, SAMPLE_PATH)
            parsed = load_dataset_file(SAMPLE_PATH)
        self.replace_dataset(parsed, analyze=True)
        self.dataset_name = parsed.name or "SYNTHETIC CASE 07"
        if self.dataset_name.upper() in ("SAMPLE_CASE", "SAMPLE CASE"):
            self.dataset_name = "SYNTHETIC CASE 07"

    def _set_case_identity(self, name: str) -> None:
        digest = hashlib.blake2s(
            f"{name}|{self.dataset_meta.get('seed', '')}|{time.time_ns()}".encode(),
            digest_size=3,
        ).hexdigest().upper()
        self.case_id = f"CC-{datetime.now(timezone.utc):%y%m%d}-{digest}"
        if self.dataset_meta.get("case_id"):
            self.case_id = str(self.dataset_meta["case_id"])

    def replace_dataset(self, parsed: ParsedDataset, *, analyze: bool = True) -> dict[str, Any]:
        """Replace the working set with a parsed upload."""
        with self._lock:
            self.raw_events = {event.id: event for event in parsed.events}
            self.rules = self._dedupe_rules(parsed.rules)
            self.ground_truth = list(parsed.ground_truth)
            self.dataset_meta = dict(parsed.meta)
            self.dataset_name = (parsed.name or "UPLOADED CASE").upper()
            self.offsets = {
                str(k): float(v)
                for k, v in (parsed.meta.get("clock_offsets") or {}).items()
            }
            self.normalized = {
                event.id: normalize_event(event, self.offsets)
                for event in parsed.events
            }
            self.index = EventIndex(self.normalized.values())
            self.conflicts = []
            self.pending_events = set(self.normalized)
            self.pending_rules = {rule.id for rule in self.rules}
            self.incremental_graph = IncrementalConstraintGraph()
            self._has_analysis = False
            self.last_mode = "idle"
            self._set_case_identity(self.dataset_name)
            self._refresh_source_counts()
            if analyze:
                self.analyze("full")
            return {
                **parsed.summary(),
                "case_id": self.case_id,
                "warnings": parsed.warnings,
            }

    def append_dataset(self, parsed: ParsedDataset, *, analyze: bool = True) -> dict[str, Any]:
        """Merge an incremental upload into the current case."""
        with self._lock:
            added = 0
            skipped = 0
            for event in parsed.events:
                if event.id in self.raw_events:
                    skipped += 1
                    continue
                self.raw_events[event.id] = event
                normalized = normalize_event(event, self.offsets)
                self.normalized[event.id] = normalized
                self.index.add(normalized)
                self.pending_events.add(event.id)
                added += 1
            existing_rule_ids = {rule.id for rule in self.rules}
            for rule in parsed.rules:
                if rule.id in existing_rule_ids:
                    continue
                self.rules.append(rule)
                self.pending_rules.add(rule.id)
                existing_rule_ids.add(rule.id)
            if parsed.ground_truth:
                self.ground_truth.extend(parsed.ground_truth)
            if parsed.meta:
                self.dataset_meta.update(parsed.meta)
            warnings = list(parsed.warnings)
            if skipped:
                warnings.append(f"{skipped} duplicate event id(s) skipped")
            self._refresh_source_counts()
            if analyze:
                self.analyze("incremental")
            return {
                "name": self.dataset_name,
                "events": added,
                "rules": len(parsed.rules),
                "warnings": warnings,
                "case_id": self.case_id,
            }

    def add_event(self, event: Event, *, analyze: bool = True) -> dict[str, Any]:
        """Add one record and run an incremental re-check."""
        with self._lock:
            if event.id in self.raw_events:
                raise IngestError(f"event id {event.id} already exists")
            if not self._has_analysis:
                # A first single-event ingest still needs a full baseline.
                self.raw_events[event.id] = event
                normalized = normalize_event(event, self.offsets)
                self.normalized[event.id] = normalized
                self.index.add(normalized)
                self.pending_events.add(event.id)
                self._refresh_source_counts()
                self.analyze("full")
            else:
                self.raw_events[event.id] = event
                normalized = normalize_event(event, self.offsets)
                self.normalized[event.id] = normalized
                self.index.add(normalized)
                self.pending_events.add(event.id)
                self._refresh_source_counts()
                self.analyze("incremental")
            return {
                "event": normalized.to_dict(),
                "new_conflicts": [
                    conflict.to_dict()
                    for conflict in self.conflicts
                    if conflict.id in set(self.last_new_conflicts)
                ],
                "total_conflicts": len(self.conflicts),
                "analysis_ms": round(self.last_analysis_ms, 3),
                "mode": self.last_mode,
            }

    # --------------------------------------------------------------- analysis
    def analyze(self, mode: str = "full") -> dict[str, Any]:
        """Run full or incremental analysis under the engine lock."""
        with self._lock:
            if mode not in ("full", "incremental"):
                raise ValueError("mode must be 'full' or 'incremental'")
            if mode == "incremental" and self._has_analysis:
                if not self.pending_events and not self.pending_rules:
                    self.last_mode = "incremental (cached)"
                    self.last_new_conflicts = []
                    self.last_analysis_ms = 0.05
                    return self.stats()
                self._run_incremental()
            else:
                self._run_full()
            return self.stats()

    def _run_full(self) -> None:
        started = time.perf_counter()
        events_by_id = self.normalized
        self.conflicts = run_detectors(self.index, self.rules, self.config)
        times = self._rule_times()
        graph_result = bellman_ford(self.rules, times)
        if graph_result.has_cycle:
            graph_conflict = self._cycle_conflict(graph_result)
            if graph_conflict is not None:
                self.conflicts.append(graph_conflict)
        self.conflicts = self._merge_conflicts([], self.conflicts)
        score_conflicts(self.conflicts, events_by_id, self.index)
        self._sort_conflicts()
        self._rebuild_incremental_graph()
        self._finish_analysis(started, "full")
        self.pending_events.clear()
        self.pending_rules.clear()

    def _run_incremental(self) -> None:
        started = time.perf_counter()
        new_event_ids = set(self.pending_events)
        new_rule_ids = set(self.pending_rules)
        new_rules = [rule for rule in self.rules if rule.id in new_rule_ids]
        additions: list[Conflict] = []
        affected_devices: set[str] = set()

        if new_event_ids:
            additions.extend(
                detect_simultaneity(self.index, self.config, event_ids=new_event_ids)
            )
            additions.extend(
                detect_impossible_travel(self.index, self.config, event_ids=new_event_ids)
            )
            affected_devices = {
                self.normalized[event_id].device_id
                for event_id in new_event_ids
                if event_id in self.normalized
            }

        focus_rules = [
            rule
            for rule in self.rules
            if rule.id in new_rule_ids
            or rule.event_a in new_event_ids
            or rule.event_b in new_event_ids
        ]
        if focus_rules:
            additions.extend(detect_causality(self.normalized, focus_rules))

        if affected_devices:
            additions.extend(
                detect_clock_skew(
                    self.index, self.config, device_ids=affected_devices
                )
            )

        # Constraint graph: add only new rule edges and re-check their reachable
        # subgraphs.  Existing rule edges stay resident.
        graph_cycles: list[CycleResult] = []
        if new_rules:
            endpoint_ids = {
                endpoint
                for rule in new_rules
                for endpoint in (rule.event_a, rule.event_b)
            }
            endpoint_events = [
                self.normalized[i] for i in endpoint_ids if i in self.normalized
            ]
            self.incremental_graph.add_events(endpoint_events)
            self.incremental_graph.add_rules(new_rules)
            graph_cycles = [
                result
                for result in self.incremental_graph.check_new_edges()
                if set(result.cycle_event_ids) & endpoint_ids
            ]
            for result in graph_cycles:
                conflict = self._cycle_conflict(result)
                if conflict is not None:
                    additions.append(conflict)

        # A newly added record can invalidate or refresh a device-level skew
        # finding; drop the stale device conflict before re-merging.
        base = [
            conflict
            for conflict in self.conflicts
            if not (
                conflict.kind == "clock_skew"
                and conflict.device_id in affected_devices
            )
        ]
        old_ids = {conflict.id for conflict in base}
        self.conflicts = self._merge_conflicts(base, additions)
        score_conflicts(self.conflicts, self.normalized, self.index)
        self._sort_conflicts()
        self.last_new_conflicts = [
            conflict.id for conflict in self.conflicts if conflict.id not in old_ids
        ]
        self._finish_analysis(started, "incremental")
        self.pending_events.clear()
        self.pending_rules.clear()

    def _finish_analysis(self, started: float, mode: str) -> None:
        elapsed = time.perf_counter() - started
        self.last_analysis_ms = elapsed * 1000.0
        self.last_events_per_sec = (
            len(self.normalized) / elapsed if elapsed > 0 else 0.0
        )
        self.last_analysis_at = _now_iso()
        self.last_mode = mode
        self.analysis_runs += 1
        self._has_analysis = True
        self._last_memory_mb = _rss_mb()
        self._refresh_source_counts()
        self._conflict_eval = self._evaluate_ground_truth()

    def _rule_times(self) -> dict[str, float]:
        ids = {
            endpoint
            for rule in self.rules
            for endpoint in (rule.event_a, rule.event_b)
        }
        return {
            event_id: event.ts
            for event_id, event in self.normalized.items()
            if event_id in ids
        }

    def _rebuild_incremental_graph(self) -> None:
        endpoint_ids = {
            endpoint
            for rule in self.rules
            for endpoint in (rule.event_a, rule.event_b)
        }
        endpoint_events = [
            self.normalized[i] for i in endpoint_ids if i in self.normalized
        ]
        self.incremental_graph = IncrementalConstraintGraph(endpoint_events)
        self.incremental_graph.add_rules(self.rules)
        self.incremental_graph.mark_clean()

    def _cycle_conflict(self, result: CycleResult) -> Conflict | None:
        event_ids = [item for item in result.cycle_event_ids if item in self.normalized]
        if len(event_ids) < 2:
            return None
        records = [self.normalized[item] for item in event_ids]
        entities = {record.entity for record in records}
        entity = next(iter(entities)) if len(entities) == 1 else None
        path = " → ".join(event_ids)
        severity = min(0.96, 0.78 + min(0.18, abs(result.total_weight) / 3600.0 * 0.05))
        from core.schema import make_conflict

        conflict = make_conflict(
            "constraint_cycle",
            event_ids,
            entity,
            f"Difference-constraint cycle is infeasible: {path}.",
            severity=severity,
            t_delta_s=result.total_weight,
            detected_by="constraint_graph",
            meta={
                "cycle_weight_s": round(result.total_weight, 3),
                "algorithm": result.algorithm,
                "nodes_examined": result.nodes_examined,
                "relaxations": result.relaxations,
            },
        )
        conflict.sources = tuple(sorted({record.source for record in records}))
        return conflict

    def _merge_conflicts(
        self,
        base: Iterable[Conflict],
        additions: Iterable[Conflict],
    ) -> list[Conflict]:
        """Collapse duplicate views of the same contradiction.

        A causality detector and the constraint graph may discover the same
        pair; simultaneity and travel can also share records.  The signature is
        the event-id set (or device for clock skew).  We retain the most
        specific detector while unioning provenance.
        """
        merged: dict[str, Conflict] = {}
        for conflict in base:
            merged[conflict.signature()] = conflict
        for candidate in additions:
            signature = candidate.signature()
            current = merged.get(signature)
            if current is None:
                if not candidate.sources:
                    candidate.sources = self._sources_for(candidate.event_ids)
                merged[signature] = candidate
                continue
            detectors = tuple(
                sorted(set(current.detected_by) | set(candidate.detected_by))
            )
            sources = tuple(
                sorted(set(current.sources) | set(candidate.sources) | set(self._sources_for(candidate.event_ids)))
            )
            current_rank = KIND_RANK.get(current.kind, 0)
            candidate_rank = KIND_RANK.get(candidate.kind, 0)
            replace = (candidate_rank, candidate.severity) > (
                current_rank,
                current.severity,
            )
            if replace:
                candidate.detected_by = detectors
                candidate.sources = sources
                candidate.meta.setdefault(
                    "merged_detectors", sorted(set(current.detected_by))
                )
                merged[signature] = candidate
            else:
                current.detected_by = detectors
                current.sources = sources
                current.meta.setdefault(
                    "merged_detectors", sorted(set(candidate.detected_by))
                )
        return list(merged.values())

    def _sources_for(self, event_ids: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.normalized[event_id].source
                    for event_id in event_ids
                    if event_id in self.normalized
                }
            )
        )

    def _sort_conflicts(self) -> None:
        self.conflicts.sort(
            key=lambda c: (c.confidence, c.severity, c.id), reverse=True
        )

    # ------------------------------------------------------------ presentation
    def _refresh_source_counts(self) -> None:
        counts = Counter(event.source for event in self.normalized.values())
        self._source_counts = {source: counts.get(source, 0) for source in SOURCES}

    def _entity_conflict_map(self) -> dict[str, list[Conflict]]:
        mapping: dict[str, list[Conflict]] = defaultdict(list)
        for conflict in self.conflicts:
            entities: set[str] = set()
            if conflict.entity:
                entities.add(conflict.entity)
            for event_id in conflict.event_ids:
                event = self.normalized.get(event_id)
                if event is not None:
                    entities.add(event.entity)
            for entity in entities:
                mapping[entity].append(conflict)
        return mapping

    def entity_summary(self) -> list[dict[str, Any]]:
        mapping = self._entity_conflict_map()
        entities: list[dict[str, Any]] = []
        for name in self.index.entity_names:
            records = self.index.entity_events(name)
            if not records:
                continue
            conflicts = mapping.get(name, [])
            max_severity = max((c.severity for c in conflicts), default=0.0)
            if not conflicts:
                status = "clean"
            elif max_severity >= 0.64:
                status = "conflicted"
            else:
                status = "suspect"
            source_counts = Counter(record.source for record in records)
            latest = records[-1]
            entities.append(
                {
                    "name": name,
                    "event_count": len(records),
                    "status": status,
                    "conflict_count": len(conflicts),
                    "max_severity": round(max_severity, 3),
                    "sources": {
                        source: source_counts.get(source, 0) for source in SOURCES
                    },
                    "first_event": iso_utc(records[0].ts),
                    "last_event": latest.timestamp,
                    "latest_action": latest.action,
                    "latest_source": latest.source,
                }
            )
        entities.sort(key=lambda item: (item["status"] != "conflicted", item["status"] != "suspect", item["name"]))
        return entities

    def _evaluate_ground_truth(self) -> dict[str, Any] | None:
        if not self.ground_truth:
            return None

        def truth_key(truth: GroundTruth) -> tuple[str, Any]:
            if truth.type == "clock_skew" and truth.device_id:
                return ("clock_skew", truth.device_id)
            return ("events", frozenset(truth.event_ids))

        def detection_key(conflict: Conflict) -> tuple[str, Any]:
            if conflict.kind == "clock_skew" and conflict.device_id:
                return ("clock_skew", conflict.device_id)
            return ("events", frozenset(conflict.event_ids))

        truths = [truth_key(item) for item in self.ground_truth]
        detections = {detection_key(conflict) for conflict in self.conflicts}
        matched = [key for key in truths if key in detections]
        tp = len(matched)
        fp = len(detections) - len(set(matched))
        fn = len(truths) - tp
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        return {
            "planted": len(truths),
            "detected": len(detections),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(
                2 * precision * recall / (precision + recall)
                if precision + recall
                else 0.0,
                4,
            ),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            source_payload = []
            total = max(1, len(self.normalized))
            for source in SOURCES:
                count = self._source_counts.get(source, 0)
                source_payload.append(
                    {
                        "name": source,
                        "count": count,
                        "share": round(count / total, 4),
                        "reliability": SOURCE_RELIABILITY[source],
                    }
                )
            entities = self.entity_summary()
            status_counts = Counter(item["status"] for item in entities)
            critical = sum(1 for c in self.conflicts if c.severity >= 0.8)
            bounds = self.index.bounds
            return {
                "case_id": self.case_id,
                "analyst": self.analyst,
                "dataset": self.dataset_name,
                "dataset_meta": self.dataset_meta,
                "mode": self.last_mode,
                "event_count": len(self.normalized),
                "entity_count": len(entities),
                "rule_count": len(self.rules),
                "ground_truth_count": len(self.ground_truth),
                "source_counts": source_payload,
                "entity_status": {
                    "clean": status_counts.get("clean", 0),
                    "suspect": status_counts.get("suspect", 0),
                    "conflicted": status_counts.get("conflicted", 0),
                },
                "conflicts_found": len(self.conflicts),
                "critical_conflicts": critical,
                "analysis_ms": round(self.last_analysis_ms, 3),
                "analysis_s": round(self.last_analysis_ms / 1000.0, 4),
                "events_per_sec": round(self.last_events_per_sec, 1),
                "memory_mb": self._last_memory_mb,
                "last_analysis_at": self.last_analysis_at,
                "pending_events": len(self.pending_events),
                "pending_rules": len(self.pending_rules),
                "window": {
                    "start": iso_utc(bounds[0]) if bounds else None,
                    "end": iso_utc(bounds[1]) if bounds else None,
                },
                "evaluation": self._conflict_eval,
                "analysis_runs": self.analysis_runs,
                "entities": entities,
                "top_severity": round(
                    max((c.severity for c in self.conflicts), default=0.0), 3
                ),
                "avg_confidence": round(
                    sum(c.confidence for c in self.conflicts) / len(self.conflicts),
                    4,
                )
                if self.conflicts
                else 0.0,
            }

    def conflicts_payload(self, limit: int = 8) -> list[dict[str, Any]]:
        with self._lock:
            if limit <= 0:
                ordered = list(self.conflicts)
            else:
                ordered = top_k(self.conflicts, limit)
            return [conflict.to_dict() for conflict in ordered]

    def explain(self, conflict_id: str) -> dict[str, Any] | None:
        with self._lock:
            conflict = next((c for c in self.conflicts if c.id == conflict_id), None)
            if conflict is None:
                return None
            return explain_conflict(conflict, self.index, self.rules)

    def timeline(
        self,
        *,
        entity: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 2000,
    ) -> dict[str, Any]:
        with self._lock:
            if entity:
                records = self.index.entity_events(entity.upper())
            else:
                records = self.index.all_events()
            if start:
                from core.normalize import parse_timestamp

                start_ts = parse_timestamp(start).timestamp()
                records = [record for record in records if record.end_ts >= start_ts]
            if end:
                from core.normalize import parse_timestamp

                end_ts = parse_timestamp(end).timestamp()
                records = [record for record in records if record.ts <= end_ts]
            total = len(records)
            if limit > 0 and total > limit:
                conflict_event_ids = {
                    event_id
                    for conflict in self.conflicts
                    for event_id in conflict.event_ids
                }
                priority = [r for r in records if r.id in conflict_event_ids]
                remaining = [r for r in records if r.id not in conflict_event_ids]
                records = (priority + remaining)[:limit]
            records.sort(key=lambda record: (record.ts, record.id))
            conflict_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for conflict in self.conflicts:
                for event_id in conflict.event_ids:
                    conflict_by_event[event_id].append(
                        {
                            "id": conflict.id,
                            "kind": conflict.kind,
                            "severity": round(conflict.severity, 3),
                        }
                    )
            payload = []
            for record in records:
                item = record.to_dict()
                item["conflicts"] = conflict_by_event.get(record.id, [])
                payload.append(item)
            return {
                "events": payload,
                "total": total,
                "truncated": len(payload) < total,
                "entity": entity.upper() if entity else None,
                "window": {
                    "start": payload[0]["timestamp"] if payload else None,
                    "end": payload[-1]["timestamp"] if payload else None,
                },
            }

    def gaps_payload(
        self,
        *,
        threshold_s: float = 900.0,
        entity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [
                gap.to_dict()
                for gap in find_gaps(
                    self.index,
                    threshold_s=max(1.0, threshold_s),
                    entity=entity.upper() if entity else None,
                    limit=max(0, limit),
                )
            ]

    def export_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            rows: list[dict[str, Any]] = []
            for conflict in self.conflicts:
                rows.append(
                    {
                        "id": conflict.id,
                        "kind": conflict.kind,
                        "severity": round(conflict.severity, 4),
                        "confidence": round(conflict.confidence, 4),
                        "entity": conflict.entity or "",
                        "device_id": conflict.device_id or "",
                        "t_delta_s": round(conflict.t_delta_s, 3),
                        "sources": ";".join(conflict.sources),
                        "event_ids": ";".join(conflict.event_ids),
                        "detected_by": ";".join(conflict.detected_by),
                        "detail": conflict.detail,
                    }
                )
            return rows

    def export_payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "case_id": self.case_id,
                "dataset": self.dataset_name,
                "analyst": self.analyst,
                "generated_at": _now_iso(),
                "mode": self.last_mode,
                "stats": {
                    "events": len(self.normalized),
                    "entities": len(self.index.entity_names),
                    "rules": len(self.rules),
                    "conflicts": len(self.conflicts),
                },
                "conflicts": [conflict.to_dict() for conflict in self.conflicts],
            }

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _dedupe_rules(rules: Iterable[Rule]) -> list[Rule]:
        seen: set[str] = set()
        out: list[Rule] = []
        for rule in rules:
            if rule.id in seen:
                continue
            seen.add(rule.id)
            out.append(rule)
        return out


def parse_event_upload(filename: str, raw: bytes) -> ParsedDataset:
    return parse_upload(filename, raw)


__all__ = ["ChronoEngine", "SAMPLE_PATH", "parse_event_upload"]
