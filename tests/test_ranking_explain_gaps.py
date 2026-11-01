"""Ranking heap, evidence gaps, and BFS explanations."""

from __future__ import annotations

from core.detectors import detect_causality, detect_impossible_travel, run_detectors
from core.explain import explain_conflict
from core.gaps import find_gaps
from core.generator import GeneratorConfig, generate_dataset
from core.index import EventIndex
from core.normalize import normalize_events
from core.ranking import ConflictMinHeap, score_conflicts, top_k


def build_case(seed: int = 11, n: int = 400):
    generated = generate_dataset(
        GeneratorConfig(n_events=n, contradictions=9, seed=seed, span_days=4.0)
    )
    normalized = normalize_events(generated.events)
    index = EventIndex(normalized)
    conflicts = run_detectors(index, generated.rules)
    events_by_id = {event.id: event for event in normalized}
    score_conflicts(conflicts, events_by_id, index)
    return generated, normalized, index, conflicts, events_by_id


def test_scores_are_bounded_and_ordered():
    _generated, _events, _index, conflicts, _by_id = build_case()
    assert conflicts
    assert all(0.0 <= conflict.confidence <= 1.0 for conflict in conflicts)
    assert all(0.0 <= conflict.severity <= 1.0 for conflict in conflicts)
    assert all(conflict.corroboration >= 0 for conflict in conflicts)
    ranked = top_k(conflicts, 5)
    assert len(ranked) == min(5, len(conflicts))
    assert ranked == sorted(
        ranked, key=lambda c: (c.confidence, c.severity, c.id), reverse=True
    )


def test_min_heap_matches_full_sort():
    _generated, _events, _index, conflicts, _by_id = build_case(seed=13)
    full = sorted(
        conflicts, key=lambda c: (c.confidence, c.severity, c.id), reverse=True
    )[:7]
    heap = ConflictMinHeap(7)
    for conflict in conflicts:
        heap.push(conflict)
    assert [item.id for item in heap.snapshot_descending()] == [item.id for item in full]


def test_top_k_zero_and_large():
    _generated, _events, _index, conflicts, events_by_id = build_case(seed=17)
    assert top_k(conflicts, 0) == []
    assert len(top_k(conflicts, 1000)) == len(conflicts)
    rescored = top_k(conflicts, 3, events_by_id=events_by_id, index=_index)
    assert len(rescored) == 3


def test_gap_detection_uses_event_end_and_threshold():
    generated = generate_dataset(
        GeneratorConfig(n_events=80, contradictions=1, seed=4, span_days=1, entities=2)
    )
    normalized = normalize_events(generated.events)
    index = EventIndex(normalized)
    gaps = find_gaps(index, threshold_s=600.0, entity="SUBJ-001", include_edges=False, limit=50)
    assert all(gap.entity == "SUBJ-001" for gap in gaps)
    assert all(gap.duration_s >= 600.0 for gap in gaps)
    # Interior gaps must refer to existing records.
    for gap in gaps:
        assert gap.after_event is not None
        assert gap.before_event is not None


def test_explain_returns_ordered_chain_for_travel_conflict():
    generated, _normalized, index, conflicts, _by_id = build_case(seed=19)
    travel = next(conflict for conflict in conflicts if conflict.kind == "impossible_travel")
    explanation = explain_conflict(travel, index, generated.rules)
    assert explanation["chain"]
    assert len(explanation["chain"]) >= 2
    assert explanation["narrative"]
    ids = [step["record"]["id"] for step in explanation["chain"]]
    assert set(travel.event_ids).issubset(set(ids))


def test_explain_causality_uses_rule_hop():
    generated, _normalized, index, conflicts, _by_id = build_case(seed=23)
    causal = next(conflict for conflict in conflicts if conflict.kind == "causality")
    explanation = explain_conflict(causal, index, generated.rules)
    vias = [step["via"] for step in explanation["chain"]]
    assert any("MIN_GAP" in via or "PRECEDES" in via or "temporal" in via for via in vias)
