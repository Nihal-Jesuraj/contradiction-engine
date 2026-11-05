"""Tests for the seeded generator and its planted truth."""

from __future__ import annotations

from collections import Counter

from contradiction_engine.generator import GeneratorConfig, generate_case


def test_same_seed_is_deterministic() -> None:
    """Two runs with the same seed produce identical records and truth."""
    first = generate_case(GeneratorConfig(seed=7))
    second = generate_case(GeneratorConfig(seed=7))
    assert first.case.records == second.case.records
    assert first.truth == second.truth


def test_different_seeds_differ() -> None:
    """Changing the seed changes the generated walks."""
    first = generate_case(GeneratorConfig(seed=7))
    second = generate_case(GeneratorConfig(seed=8))
    assert first.case.records != second.case.records


def test_requested_conflict_counts_are_planted() -> None:
    """Each detector's requested count appears in the truth list."""
    generated = generate_case(
        GeneratorConfig(
            seed=42,
            device_conflicts=2,
            location_conflicts=2,
            message_conflicts=2,
            claim_conflicts=2,
        )
    )
    counts = Counter(entry.kind for entry in generated.truth)
    assert counts == {
        "device_state": 2,
        "location": 2,
        "message_order": 2,
        "claim": 2,
    }


def test_truth_ids_exist_in_the_case() -> None:
    """Every planted record ID points at a real evidence record."""
    generated = generate_case(GeneratorConfig(seed=3))
    record_ids = {record.id for record in generated.case.records}
    for entry in generated.truth:
        assert set(entry.record_ids).issubset(record_ids)


def test_clean_generation_has_no_truth() -> None:
    """Zero requested conflicts yields an empty truth list."""
    generated = generate_case(
        GeneratorConfig(
            seed=11,
            device_conflicts=0,
            location_conflicts=0,
            message_conflicts=0,
            claim_conflicts=0,
        )
    )
    assert generated.truth == []
    assert generated.case.records


def test_case_keeps_a_copy_of_the_truth_list() -> None:
    """The case exposes the same planted truth for display and scoring."""
    generated = generate_case(GeneratorConfig(seed=5))
    assert generated.case.ground_truth == generated.truth
