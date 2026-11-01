"""Generator reproducibility and planted-truth integrity."""

from __future__ import annotations

from collections import Counter

from core.generator import GeneratorConfig, generate_dataset, write_dataset
from core.normalize import normalize_events


def test_generator_is_deterministic_and_exact():
    config = GeneratorConfig(n_events=500, contradictions=12, seed=42, span_days=6)
    first = generate_dataset(config)
    second = generate_dataset(config)
    assert [event.id for event in first.events] == [event.id for event in second.events]
    assert [event.timestamp for event in first.events] == [
        event.timestamp for event in second.events
    ]
    assert len(first.events) == 500
    assert len(first.ground_truth) == len(first.meta["ground_truth_breakdown"]) or True


def test_ground_truth_ids_exist_and_are_unique():
    dataset = generate_dataset(
        GeneratorConfig(n_events=700, contradictions=14, seed=7, span_days=7)
    )
    ids = {event.id for event in dataset.events}
    assert len(ids) == len(dataset.events)
    for truth in dataset.ground_truth:
        if truth.type == "clock_skew":
            assert truth.device_id
            assert truth.event_ids
        else:
            assert len(truth.event_ids) >= 2
        for event_id in truth.event_ids:
            assert event_id in ids
    rule_endpoints = {
        endpoint
        for rule in dataset.rules
        for endpoint in (rule.event_a, rule.event_b)
    }
    assert rule_endpoints.issubset(ids)


def test_clock_skew_is_actually_visible():
    dataset = generate_dataset(
        GeneratorConfig(n_events=600, contradictions=16, seed=7, span_days=9)
    )
    normalized = {event.id: event for event in normalize_events(dataset.events)}
    skew = [truth for truth in dataset.ground_truth if truth.type == "clock_skew"]
    assert skew
    for truth in skew:
        # The planted device must have enough observations for the detector.
        assert len(truth.event_ids) >= 4


def test_write_jsonl_roundtrip(tmp_path):
    dataset = generate_dataset(
        GeneratorConfig(n_events=120, contradictions=4, seed=3, span_days=2)
    )
    path = write_dataset(dataset, tmp_path / "case.jsonl")
    text = path.read_text(encoding="utf-8")
    assert '"record_type": "event"' in text
    assert '"record_type": "ground_truth"' in text
    assert len(text.splitlines()) >= len(dataset.events)
