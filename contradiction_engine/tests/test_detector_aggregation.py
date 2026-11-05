"""Aggregation tests for detectors 1-3 on generated cases."""

from __future__ import annotations

from collections import Counter

from contradiction_engine.detectors import run_all_detectors
from contradiction_engine.generator import GeneratorConfig, generate_case


def test_clean_generated_case_has_no_conflicts() -> None:
    """A clean case must not produce false positives."""
    generated = generate_case(
        GeneratorConfig(
            seed=42,
            people=3,
            device_conflicts=0,
            location_conflicts=0,
            message_conflicts=0,
            claim_conflicts=0,
        )
    )
    conflicts = run_all_detectors(
        generated.case.records, generated.case.graph()
    )
    assert conflicts == []


def test_planted_device_location_and_message_conflicts_are_found() -> None:
    """Each planted kind is detected exactly the requested number of times."""
    generated = generate_case(
        GeneratorConfig(
            seed=42,
            people=3,
            device_conflicts=2,
            location_conflicts=2,
            message_conflicts=2,
            claim_conflicts=0,
        )
    )
    conflicts = run_all_detectors(
        generated.case.records, generated.case.graph()
    )
    counts = Counter(conflict.kind for conflict in conflicts)
    assert counts["device_state"] == 2
    assert counts["location"] == 2
    assert counts["message_order"] == 2
    assert counts["message_cycle"] == 0


def test_planted_location_claim_is_found() -> None:
    """A claimed place contradicted by a close sighting is detected."""
    generated = generate_case(
        GeneratorConfig(
            seed=42,
            people=2,
            device_conflicts=0,
            location_conflicts=0,
            message_conflicts=0,
            claim_conflicts=0,
            location_claim_conflicts=1,
        )
    )
    conflicts = run_all_detectors(
        generated.case.records, generated.case.graph()
    )
    counts = Counter(conflict.kind for conflict in conflicts)
    assert counts["claim_location"] == 1
    assert len(conflicts) == 1


def test_planted_device_login_is_found() -> None:
    """The generated OFF-device login reaches the device-state detector."""
    generated = generate_case(
        GeneratorConfig(
            seed=42,
            people=2,
            device_conflicts=2,
            location_conflicts=0,
            message_conflicts=0,
            claim_conflicts=0,
            location_claim_conflicts=0,
        )
    )
    conflicts = run_all_detectors(
        generated.case.records, generated.case.graph()
    )
    device_conflicts = [
        conflict for conflict in conflicts if conflict.kind == "device_state"
    ]
    login_ids = {
        record.id for record in generated.case.records
        if record.record_type == "login" and record.device
    }
    assert len(device_conflicts) == 2
    assert any(
        conflict.record_ids[0] in login_ids for conflict in device_conflicts
    )
