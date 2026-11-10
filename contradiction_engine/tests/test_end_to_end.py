"""End-to-end: generate or upload, analyze, then compare with truth."""

from __future__ import annotations

import csv
import io

from contradiction_engine.detectors import run_all_detectors
from contradiction_engine.generator import GeneratorConfig, generate_case
from contradiction_engine.loader import load_case
from contradiction_engine.models import CSV_FIELDS, score_conflicts


def test_generated_case_reaches_perfect_precision_and_recall() -> None:
    """All planted conflicts are found and nothing extra is invented."""
    generated = generate_case(
        GeneratorConfig(
            seed=42,
            people=3,
            device_conflicts=2,
            location_conflicts=2,
            message_conflicts=2,
            claim_conflicts=2,
            location_claim_conflicts=2,
        )
    )
    conflicts = run_all_detectors(
        generated.case.records, generated.case.graph()
    )
    score = score_conflicts(conflicts, generated.truth)
    assert score.matched == score.planted == 10
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.f1 == 1.0


def test_clean_generated_case_has_zero_conflicts() -> None:
    """The clean timeline produces no false positives."""
    generated = generate_case(
        GeneratorConfig(
            seed=7,
            people=3,
            device_conflicts=0,
            location_conflicts=0,
            message_conflicts=0,
            claim_conflicts=0,
        )
    )
    assert run_all_detectors(generated.case.records, generated.case.graph()) == []


def test_uploaded_csv_can_be_analyzed() -> None:
    """A small uploaded case yields the expected device conflict."""
    rows = [
        {"id": "S1", "timestamp": "2026-03-02T08:00:00Z",
         "record_type": "state", "device": "D1", "state": "ON"},
        {"id": "A1", "timestamp": "2026-03-02T08:10:00Z",
         "record_type": "activity", "device": "D1", "action": "login"},
        {"id": "S2", "timestamp": "2026-03-02T08:20:00Z",
         "record_type": "state", "device": "D1", "state": "OFF"},
        {"id": "A2", "timestamp": "2026-03-02T08:30:00Z",
         "record_type": "activity", "device": "D1", "action": "file access"},
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
    case, errors = load_case("upload.csv", buffer.getvalue().encode("utf-8"))
    assert errors == []
    assert case is not None
    conflicts = run_all_detectors(case.records, case.graph())
    assert [conflict.kind for conflict in conflicts] == ["device_state"]
    assert conflicts[0].record_ids == ("A2", "S2")


def test_invalid_upload_returns_errors_and_no_case() -> None:
    """A bad file never produces a partial case."""
    data = b"timestamp,record_type,place\nnot-a-time,sighting,Atlantis\n"
    case, errors = load_case("upload.csv", data)
    assert case is None
    assert errors


def test_uploaded_claimed_location_is_detected() -> None:
    """A claimed_at row from CSV reaches the location-claim detector."""
    rows = [
        {"id": "S1", "timestamp": "2026-03-02T14:00:00Z",
         "record_type": "sighting", "person": "P1", "place": "Library"},
        {"id": "C1", "timestamp": "2026-03-02T13:57:00Z",
         "record_type": "claim", "person": "P1", "place": "Harbour",
         "claim": "claimed_at", "end_timestamp": "2026-03-02T14:03:00Z"},
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
    case, errors = load_case("upload.csv", buffer.getvalue().encode("utf-8"))
    assert errors == []
    assert case is not None
    conflicts = run_all_detectors(case.records, case.graph())
    assert [conflict.kind for conflict in conflicts] == ["claim_location"]
    assert conflicts[0].record_ids == ("C1", "S1")
