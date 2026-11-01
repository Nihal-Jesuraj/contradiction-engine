"""Benchmark harness: naive vs indexed detection, and graph algorithm baselines.

Every measurement is reproducible from (size, seed, contradictions).  Timings
use ``time.perf_counter`` and memory uses ``tracemalloc`` peak.  Naive pairwise
detection is intentionally skipped above a cap (default 10k events) because
O(n^2) at 100k would require billions of interval comparisons; the JSON records
that it was skipped rather than fabricating a number.

Run:
    python -m core.bench --sizes 1000 10000 100000 1000000 --out backend/results

Outputs:
    chronoclash_bench.json
    chronoclash_bench.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
import tracemalloc
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .constraint_graph import (
    IncrementalConstraintGraph,
    bellman_ford,
    floyd_warshall,
)
from .detectors import (
    DetectionConfig,
    detect_causality,
    detect_clock_skew,
    detect_impossible_travel,
    detect_simultaneity,
    haversine_m,
)
from .gaps import find_gaps
from .generator import GeneratorConfig, generate_dataset
from .index import EventIndex
from .normalize import normalize_events
from .ranking import score_conflicts, top_k
from .schema import Conflict, GroundTruth, NormalizedEvent, Rule

KIND_RANK = {
    "constraint_cycle": 1,
    "impossible_travel": 2,
    "impossible_simultaneity": 3,
    "causality": 4,
    "clock_skew": 5,
}


def _mb(value: int | float) -> float:
    return round(float(value) / (1024.0 * 1024.0), 3)


def naive_simultaneity(
    events: list[NormalizedEvent],
    config: DetectionConfig,
) -> int:
    """Plain pairwise O(n^2) overlap detector used as the baseline.

    Grouping by entity reduces constant factors but the worst case remains
    quadratic (all events belong to one subject).
    """
    grouped: dict[str, list[NormalizedEvent]] = defaultdict(list)
    for event in events:
        grouped[event.entity].append(event)
    pairs = 0
    for records in grouped.values():
        for i, first in enumerate(records):
            for second in records[i + 1 :]:
                if first.ts >= second.end_ts:
                    continue
                if second.ts >= first.end_ts:
                    continue
                overlap = min(first.end_ts, second.end_ts) - max(first.ts, second.ts)
                if overlap < config.min_overlap_s:
                    continue
                if haversine_m(first.lat, first.lon, second.lat, second.lon) > config.location_epsilon_m:
                    pairs += 1
    return pairs


def dedupe_conflicts(conflicts: list[Conflict]) -> list[Conflict]:
    """Same signature policy as the API engine, without importing web code."""
    merged: dict[str, Conflict] = {}
    for conflict in conflicts:
        signature = conflict.signature()
        current = merged.get(signature)
        if current is None:
            merged[signature] = conflict
            continue
        if (KIND_RANK.get(conflict.kind, 0), conflict.severity) > (
            KIND_RANK.get(current.kind, 0),
            current.severity,
        ):
            merged[signature] = conflict
    return list(merged.values())


def evaluate_conflicts(
    conflicts: list[Conflict],
    truth: list[GroundTruth],
) -> dict[str, Any]:
    def truth_key(item: GroundTruth) -> tuple[str, Any]:
        if item.type == "clock_skew" and item.device_id:
            return ("clock_skew", item.device_id)
        return ("events", frozenset(item.event_ids))

    def detection_key(item: Conflict) -> tuple[str, Any]:
        if item.kind == "clock_skew" and item.device_id:
            return ("clock_skew", item.device_id)
        return ("events", frozenset(item.event_ids))

    truths = [truth_key(item) for item in truth]
    detections = {detection_key(item) for item in conflicts}
    matched = [key for key in truths if key in detections]
    tp = len(matched)
    fp = len(detections) - len(set(matched))
    fn = len(truths) - tp
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
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


def _build_stress_graph(
    events: list[NormalizedEvent],
    *,
    cap: int = 160,
) -> tuple[list[Rule], Rule, dict[str, float], int]:
    """Consistent max-gap chain plus one violating edge.

    The chain exercises every node while staying satisfiable.  The final rule
    forces effect-before-cause, creating exactly one negative cycle.
    """
    ordered = sorted(events, key=lambda e: (e.ts, e.id))[: max(3, cap)]
    times = {event.id: event.ts for event in ordered}
    rules: list[Rule] = []
    for first, second in zip(ordered, ordered[1:]):
        gap = second.ts - first.ts
        rules.append(
            Rule(
                type="max_gap",
                event_a=first.id,
                event_b=second.id,
                delta_s=max(0.0, gap + 3600.0),
                note="stress: satisfied chain",
            )
        )
    first, last = ordered[0], ordered[-1]
    violation = Rule(
        type="min_gap",
        event_a=last.id,
        event_b=first.id,
        delta_s=(last.ts - first.ts) + 3600.0,
        note="stress: injected contradiction",
    )
    return rules, violation, times, len(ordered)


def _graph_benchmark(
    events: list[NormalizedEvent],
    *,
    floyd_cap: int,
) -> dict[str, Any]:
    graph_sample = min(len(events), max(24, min(160, 20 + int(math.sqrt(len(events))))))
    rules, violation, times, nodes_count = _build_stress_graph(events, cap=graph_sample)
    all_rules = rules + [violation]

    t0 = time.perf_counter()
    full = bellman_ford(all_rules, times)
    full_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    incremental = IncrementalConstraintGraph(
        [event for event in events if event.id in times]
    )
    incremental.add_rules(rules)
    incremental.mark_clean()
    incremental.add_rule(violation)
    cycles = incremental.check_new_edges()
    incremental_ms = (time.perf_counter() - t0) * 1000.0

    floyd_ms: float | None = None
    floyd_cycle = False
    if nodes_count <= floyd_cap:
        t0 = time.perf_counter()
        fw = floyd_warshall(all_rules, times)
        floyd_ms = (time.perf_counter() - t0) * 1000.0
        floyd_cycle = fw.has_cycle

    graph_edges = 2 * nodes_count + len(all_rules)
    return {
        "graph_nodes": nodes_count,
        "graph_edges": graph_edges,
        "bellman_ford_ms": round(full_ms, 3),
        "incremental_ms": round(incremental_ms, 3),
        "floyd_warshall_ms": round(floyd_ms, 3) if floyd_ms is not None else None,
        "floyd_warshall_skipped": floyd_ms is None,
        "floyd_node_cap": floyd_cap,
        "bellman_ford_cycle": full.has_cycle,
        "incremental_cycle": bool(cycles and cycles[0].has_cycle),
        "floyd_cycle": floyd_cycle,
        "graph_speedup_incremental": round(full_ms / incremental_ms, 2)
        if incremental_ms > 0
        else None,
    }


@dataclass(slots=True)
class BenchConfig:
    sizes: list[int]
    contradictions: int = 8
    seed: int = 424242
    include_naive: bool = True
    max_naive_events: int = 10_000
    floyd_node_cap: int = 160
    span_days: float = 12.0


def _one_size(size: int, cfg: BenchConfig) -> dict[str, Any]:
    result: dict[str, Any] = {
        "events_requested": size,
        "events": 0,
        "contradictions": cfg.contradictions,
        "seed": cfg.seed,
        "status": "ok",
    }
    tracemalloc.start()
    try:
        t0 = time.perf_counter()
        dataset = generate_dataset(
            GeneratorConfig(
                n_events=size,
                contradictions=cfg.contradictions,
                seed=cfg.seed,
                span_days=cfg.span_days,
            )
        )
        generate_ms = (time.perf_counter() - t0) * 1000.0
        _, gen_peak = tracemalloc.get_traced_memory()
        result["generate_ms"] = round(generate_ms, 3)
        result["generation_peak_mb"] = _mb(gen_peak)
        result["events"] = len(dataset.events)
        result["planted_conflicts"] = len(dataset.ground_truth)
        result["rules"] = len(dataset.rules)
        result["entity_count"] = len({event.entity for event in dataset.events})

        tracemalloc.reset_peak()
        t0 = time.perf_counter()
        normalized = normalize_events(dataset.events)
        normalize_ms = (time.perf_counter() - t0) * 1000.0
        result["normalize_ms"] = round(normalize_ms, 3)

        t0 = time.perf_counter()
        index = EventIndex(normalized)
        index_ms = (time.perf_counter() - t0) * 1000.0
        _, index_peak = tracemalloc.get_traced_memory()
        result["index_build_ms"] = round(index_ms, 3)
        result["index_peak_mb"] = _mb(index_peak)
        result["index_height"] = max(
            (tree.height for tree in index._trees.values()), default=0
        )
        result["timeline_insert_complexity"] = "O(n) per insert; O(n log n) bulk build"
        result["interval_tree_query"] = "O(log e + k)"

        detection = DetectionConfig()
        detected: list[Conflict] = []
        timings: dict[str, float] = {}

        t0 = time.perf_counter()
        simultaneity = detect_simultaneity(index, detection)
        timings["simultaneity"] = (time.perf_counter() - t0) * 1000.0
        detected.extend(simultaneity)

        t0 = time.perf_counter()
        travel = detect_impossible_travel(index, detection)
        timings["impossible_travel"] = (time.perf_counter() - t0) * 1000.0
        detected.extend(travel)

        t0 = time.perf_counter()
        causality = detect_causality({e.id: e for e in normalized}, dataset.rules)
        timings["causality"] = (time.perf_counter() - t0) * 1000.0
        detected.extend(causality)

        t0 = time.perf_counter()
        skew = detect_clock_skew(index, detection)
        timings["clock_skew"] = (time.perf_counter() - t0) * 1000.0
        detected.extend(skew)
        result["detector_ms"] = {key: round(value, 3) for key, value in timings.items()}
        result["detector_total_ms"] = round(sum(timings.values()), 3)

        t0 = time.perf_counter()
        normalized_by_id = {event.id: event for event in normalized}
        rule_times = {
            endpoint: normalized_by_id[endpoint].ts
            for endpoint in {
                endpoint
                for rule in dataset.rules
                for endpoint in (rule.event_a, rule.event_b)
            }
            if endpoint in normalized_by_id
        }
        graph = bellman_ford(dataset.rules, rule_times)
        graph_ms = (time.perf_counter() - t0) * 1000.0
        result["constraint_graph_ms"] = round(graph_ms, 3)
        if graph.has_cycle:
            from .schema import make_conflict

            record = make_conflict(
                "constraint_cycle",
                graph.cycle_event_ids,
                None,
                "benchmark constraint cycle",
                severity=0.82,
                detected_by="constraint_graph",
            )
            detected.append(record)

        deduped = dedupe_conflicts(detected)
        t0 = time.perf_counter()
        score_conflicts(deduped, normalized_by_id, index)
        top = top_k(deduped, 8)
        result["ranking_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        result["top_confidence"] = round(top[0].confidence, 4) if top else 0.0
        result["top_k"] = [item.id for item in top]

        evaluation = evaluate_conflicts(deduped, dataset.ground_truth)
        result.update(evaluation)
        result["detected_total"] = len(deduped)
        result["detected_breakdown"] = dict(Counter(item.kind for item in deduped))

        result["tree_simultaneity_pairs"] = len(simultaneity)
        if cfg.include_naive and len(normalized) <= cfg.max_naive_events:
            t0 = time.perf_counter()
            naive_pairs = naive_simultaneity(normalized, detection)
            naive_ms = (time.perf_counter() - t0) * 1000.0
            result["naive_ms"] = round(naive_ms, 3)
            result["naive_pairs"] = naive_pairs
            result["naive_skipped"] = False
            result["tree_speedup_vs_naive"] = (
                round(naive_ms / timings["simultaneity"], 2)
                if timings["simultaneity"] > 0
                else None
            )
        else:
            result["naive_ms"] = None
            result["naive_pairs"] = None
            result["naive_skipped"] = True
            result["naive_skip_reason"] = (
                f"skipped above max_naive_events={cfg.max_naive_events}"
            )

        t0 = time.perf_counter()
        gaps = find_gaps(index, threshold_s=1200.0, limit=20)
        result["gap_scan_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        result["gaps_found_sample"] = len(gaps)

        result.update(_graph_benchmark(normalized, floyd_cap=cfg.floyd_node_cap))

        t0 = time.perf_counter()
        bf2 = bellman_ford(dataset.rules, rule_times)
        result["full_analysis_ms"] = round(
            sum(timings.values())
            + graph_ms
            + result["ranking_ms"]
            + result["gap_scan_ms"],
            3,
        )
        _, peak = tracemalloc.get_traced_memory()
        result["peak_traced_mb"] = _mb(peak)
        result["events_per_sec"] = round(
            len(normalized) / max(0.000001, result["full_analysis_ms"] / 1000.0), 1
        )
        result["bellman_cycle_confirmed"] = bf2.has_cycle
        return result
    except MemoryError:
        result["status"] = "memory_error"
        result["error"] = "MemoryError"
        return result
    except Exception as exc:  # benchmark should report, not crash the suite
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()


def run_benchmark(
    sizes: list[int],
    *,
    contradictions: int = 8,
    seed: int = 424242,
    include_naive: bool = True,
    max_naive_events: int = 10_000,
    floyd_node_cap: int = 160,
    span_days: float = 12.0,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    config = BenchConfig(
        sizes=sorted({int(size) for size in sizes if int(size) > 0}),
        contradictions=max(0, contradictions),
        seed=seed,
        include_naive=include_naive,
        max_naive_events=max_naive_events,
        floyd_node_cap=floyd_node_cap,
        span_days=span_days,
    )
    results: list[dict[str, Any]] = []
    for size in config.sizes:
        if progress:
            progress(f"benchmarking {size:,} events")
        result = _one_size(size, config)
        results.append(result)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "sizes": config.sizes,
            "contradictions": config.contradictions,
            "seed": config.seed,
            "include_naive": config.include_naive,
            "max_naive_events": config.max_naive_events,
            "floyd_node_cap": config.floyd_node_cap,
        },
        "results": results,
        "methodology": {
            "timing": "time.perf_counter, milliseconds",
            "memory": "tracemalloc peak, MiB",
            "naive": "same-entity pairwise scan O(n^2) in the worst case",
            "interval_tree": "per-entity AVL interval tree, O(log e + k)",
            "precision_recall": "planted event-id sets / skew device ids; duplicates collapsed by signature",
            "graph": "consistent max-gap chain plus one injected negative cycle",
        },
    }
    payload["summary"] = summarize(payload)
    return payload


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("results") or []
    ok = [row for row in rows if row.get("status") == "ok"]
    return {
        "sizes": [row["events"] for row in rows],
        "events_tested": sum(row.get("events", 0) for row in rows),
        "max_events": max((row.get("events", 0) for row in rows), default=0),
        "fastest_analysis_ms": min(
            (row.get("full_analysis_ms", 0.0) for row in ok), default=0.0
        ),
        "avg_precision": round(
            sum(row.get("precision", 0.0) for row in ok) / len(ok), 4
        )
        if ok
        else 0.0,
        "avg_recall": round(
            sum(row.get("recall", 0.0) for row in ok) / len(ok), 4
        )
        if ok
        else 0.0,
        "results_ok": len(ok),
        "results_failed": len(rows) - len(ok),
    }


def write_results(
    payload: dict[str, Any],
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Write the canonical benchmark JSON and flat CSV into ``output_dir``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "chronoclash_bench.json"
    csv_path = out / "chronoclash_bench.csv"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows = payload.get("results") or []
    flat_fields = [
        "events_requested",
        "events",
        "status",
        "entity_count",
        "planted_conflicts",
        "generate_ms",
        "normalize_ms",
        "index_build_ms",
        "detector_total_ms",
        "constraint_graph_ms",
        "ranking_ms",
        "gap_scan_ms",
        "full_analysis_ms",
        "naive_ms",
        "tree_simultaneity_pairs",
        "tree_speedup_vs_naive",
        "graph_nodes",
        "graph_edges",
        "bellman_ford_ms",
        "incremental_ms",
        "floyd_warshall_ms",
        "precision",
        "recall",
        "f1",
        "tp",
        "fp",
        "fn",
        "generation_peak_mb",
        "index_peak_mb",
        "peak_traced_mb",
        "events_per_sec",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=flat_fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return json_path, csv_path


def _main() -> None:
    parser = argparse.ArgumentParser(description="ChronoClash benchmark harness")
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=[1000, 10000, 100000, 1000000],
    )
    parser.add_argument("--contradictions", type=int, default=8)
    parser.add_argument("--seed", type=int, default=424242)
    parser.add_argument("--out", type=str, default="backend/results")
    parser.add_argument("--max-naive-events", type=int, default=10000)
    parser.add_argument("--floyd-node-cap", type=int, default=160)
    parser.add_argument("--no-naive", action="store_true")
    args = parser.parse_args()
    payload = run_benchmark(
        args.sizes,
        contradictions=args.contradictions,
        seed=args.seed,
        include_naive=not args.no_naive,
        max_naive_events=args.max_naive_events,
        floyd_node_cap=args.floyd_node_cap,
        progress=lambda message: print(message, flush=True),
    )
    json_path, csv_path = write_results(payload, args.out)
    print(json.dumps(payload["summary"], indent=2))
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")


if __name__ == "__main__":
    _main()
