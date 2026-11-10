"""Tests for upload parsing and row validation."""

from __future__ import annotations

import csv
import io
import json

from contradiction_engine.loader import case_variant_warnings, load_case
from contradiction_engine.models import CSV_FIELDS


def make_row(**overrides: str) -> dict[str, str]:
    """Return a full CSV row with sensible empty defaults."""
    row = {field: "" for field in CSV_FIELDS}
    row.update(overrides)
    return row


def to_csv(rows: list[dict[str, str]]) -> bytes:
    """Serialize rows to CSV bytes."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def valid_rows() -> list[dict[str, str]]:
    """Return a small but complete consistent case."""
    return [
        make_row(id="ST1", timestamp="2026-03-02T08:00:00Z",
                 record_type="state", device="D1", state="ON"),
        make_row(id="ACT1", timestamp="2026-03-02T08:10:00Z",
                 record_type="activity", device="D1", action="login"),
        make_row(id="ST2", timestamp="2026-03-02T08:20:00Z",
                 record_type="state", device="D1", state="OFF"),
        make_row(id="SGT1", timestamp="2026-03-02T09:00:00Z",
                 record_type="sighting", person="P1", place="Harbour"),
        make_row(id="MSG1", timestamp="2026-03-02T10:00:00Z",
                 record_type="message", person="P1", text="hello"),
        make_row(id="MSG2", timestamp="2026-03-02T10:05:00Z",
                 record_type="message", person="P1", depends_on="MSG1"),
        make_row(id="LOG1", timestamp="2026-03-02T11:00:00Z",
                 record_type="login", person="P1", account="A1"),
        make_row(id="CLM1", timestamp="2026-03-02T12:00:00Z",
                 record_type="claim", person="P1", account="A1",
                 claim="did_not_access", end_timestamp="2026-03-02T12:30:00Z"),
    ]


def test_valid_csv_loads() -> None:
    """A valid CSV produces a case and no errors."""
    case, errors = load_case("case.csv", to_csv(valid_rows()))
    assert errors == []
    assert case is not None
    assert len(case.records) == 8
    assert case.name == "case"


def test_valid_json_with_embedded_truth() -> None:
    """JSON can carry records, a name, and ground truth together."""
    payload = {
        "name": "json case",
        "records": valid_rows(),
        "ground_truth": [
            {"kind": "location", "record_ids": ["SGT1"], "note": "test"}
        ],
    }
    case, errors = load_case(
        "case.json", json.dumps(payload).encode("utf-8")
    )
    assert errors == []
    assert case is not None
    assert case.name == "json case"
    assert case.ground_truth[0].kind == "location"


def test_missing_ids_are_deterministic_and_unique() -> None:
    """Identical rows without IDs still receive different stable IDs."""
    rows = [
        make_row(timestamp="2026-03-02T09:00:00Z", record_type="sighting",
                 person="P1", place="Harbour"),
        make_row(timestamp="2026-03-02T09:00:00Z", record_type="sighting",
                 person="P1", place="Harbour"),
    ]
    first, errors = load_case("case.csv", to_csv(rows))
    second, _ = load_case("case.csv", to_csv(rows))
    assert errors == []
    assert first is not None and second is not None
    ids = [record.id for record in first.records]
    assert all(record_id.startswith("UPL-") for record_id in ids)
    assert ids[0] != ids[1]
    assert ids == [record.id for record in second.records]


def test_duplicate_ids_are_rejected() -> None:
    """Two records cannot share an ID."""
    rows = [
        make_row(id="X", timestamp="2026-03-02T09:00:00Z",
                 record_type="sighting", person="P1", place="Harbour"),
        make_row(id="X", timestamp="2026-03-02T10:00:00Z",
                 record_type="sighting", person="P2", place="Dock"),
    ]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert any("duplicate id" in error for error in errors)


def test_bad_timestamp_is_rejected() -> None:
    rows = [make_row(id="A", timestamp="yesterday", record_type="sighting",
                     person="P1", place="Harbour")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "ISO-8601" in errors[0]


def test_bad_record_type_is_rejected() -> None:
    rows = [make_row(id="A", timestamp="2026-03-02T09:00:00Z",
                     record_type="rumour", person="P1")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "unknown record_type" in errors[0]


def test_unknown_place_is_rejected() -> None:
    rows = [make_row(id="A", timestamp="2026-03-02T09:00:00Z",
                     record_type="sighting", person="P1", place="Atlantis")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "unknown place" in errors[0]


def test_bad_state_is_rejected() -> None:
    rows = [make_row(id="A", timestamp="2026-03-02T09:00:00Z",
                     record_type="state", device="D1", state="BROKEN")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "state must be one of" in errors[0]


def test_missing_required_field_is_rejected() -> None:
    rows = [make_row(id="A", timestamp="2026-03-02T09:00:00Z",
                     record_type="activity", device="D1")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "missing required field" in errors[0]


def test_claim_end_before_start_is_rejected() -> None:
    rows = [make_row(id="A", timestamp="2026-03-02T12:00:00Z",
                     record_type="claim", person="P1", account="A1",
                     claim="did_not_access",
                     end_timestamp="2026-03-02T11:00:00Z")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "end_timestamp must be after" in errors[0]


def test_unknown_claim_is_rejected() -> None:
    rows = [make_row(id="A", timestamp="2026-03-02T12:00:00Z",
                     record_type="claim", person="P1", account="A1",
                     claim="was_home",
                     end_timestamp="2026-03-02T12:30:00Z")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "claim must be one of" in errors[0]


def test_missing_message_parent_is_rejected() -> None:
    rows = [make_row(id="A", timestamp="2026-03-02T12:00:00Z",
                     record_type="message", person="P1", depends_on="NOPE")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "is not a message in this upload" in errors[0]


def test_only_the_first_five_errors_are_returned() -> None:
    """Six bad rows produce exactly five ordered reasons."""
    rows = [
        make_row(timestamp="bad", record_type="sighting", person="P1",
                 place="Harbour")
        for _ in range(6)
    ]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert len(errors) == 5
    assert errors[0].startswith("row 1:")
    assert errors[-1].startswith("row 5:")


def test_empty_upload_is_rejected() -> None:
    case, errors = load_case("case.csv", b"")
    assert case is None
    assert "empty" in errors[0]


def test_custom_places_are_accepted() -> None:
    """A two-place connected map can replace the built-in one."""
    places = {
        "places": {"X": [51.50, -0.12], "Y": [51.51, -0.11]},
        "edges": [["X", "Y", 4]],
    }
    rows = [make_row(id="A", timestamp="2026-03-02T09:00:00Z",
                     record_type="sighting", person="P1", place="X")]
    case, errors = load_case(
        "case.csv",
        to_csv(rows),
        places_data=json.dumps(places).encode("utf-8"),
    )
    assert errors == []
    assert case is not None
    assert set(case.places) == {"X", "Y"}


def test_disconnected_places_are_rejected() -> None:
    places = {
        "places": {"X": [51.50, -0.12], "Y": [51.51, -0.11]},
        "edges": [],
    }
    rows = [make_row(id="A", timestamp="2026-03-02T09:00:00Z",
                     record_type="sighting", person="P1", place="X")]
    case, errors = load_case(
        "case.csv",
        to_csv(rows),
        places_data=json.dumps(places).encode("utf-8"),
    )
    assert case is None
    assert "not connected" in errors[0]


def test_ground_truth_with_unknown_id_is_rejected() -> None:
    truth = {"ground_truth": [{"kind": "location", "record_ids": ["MISSING"]}]}
    case, errors = load_case(
        "case.csv",
        to_csv(valid_rows()),
        truth_data=json.dumps(truth).encode("utf-8"),
    )
    assert case is None
    assert "unknown record id" in errors[0]


def test_claimed_at_claim_loads() -> None:
    """A claimed_at row needs a place instead of an account."""
    rows = valid_rows() + [
        make_row(id="CLM2", timestamp="2026-03-02T13:00:00Z",
                 record_type="claim", person="P1", place="Harbour",
                 claim="claimed_at", end_timestamp="2026-03-02T13:10:00Z"),
    ]
    case, errors = load_case("case.csv", to_csv(rows))
    assert errors == []
    assert case is not None
    claim = case.records[-1]
    assert claim.claim == "claimed_at"
    assert claim.place == "Harbour"
    assert claim.account == ""


def test_claimed_at_without_place_is_rejected() -> None:
    rows = [make_row(id="C", timestamp="2026-03-02T13:00:00Z",
                     record_type="claim", person="P1",
                     claim="claimed_at",
                     end_timestamp="2026-03-02T13:10:00Z")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "missing required field(s): place" in errors[0]


def test_claimed_at_with_unknown_place_is_rejected() -> None:
    rows = [make_row(id="C", timestamp="2026-03-02T13:00:00Z",
                     record_type="claim", person="P1", place="Atlantis",
                     claim="claimed_at",
                     end_timestamp="2026-03-02T13:10:00Z")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "unknown place" in errors[0]


def test_denied_access_without_account_is_rejected() -> None:
    rows = [make_row(id="C", timestamp="2026-03-02T13:00:00Z",
                     record_type="claim", person="P1",
                     claim="did_not_access",
                     end_timestamp="2026-03-02T13:10:00Z")]
    case, errors = load_case("case.csv", to_csv(rows))
    assert case is None
    assert "missing required field(s): account" in errors[0]


def test_case_variant_warnings_flag_case_only_names() -> None:
    """A second spelling that differs only by case is reported to the UI."""
    rows = valid_rows() + [
        make_row(id="SGT2", timestamp="2026-03-02T09:30:00Z",
                 record_type="sighting", person="p1", place="Station"),
    ]
    case, errors = load_case("case.csv", to_csv(rows))
    assert errors == []
    assert case is not None
    warnings = case_variant_warnings(case.records)
    assert len(warnings) == 1
    assert "person 'P1' and 'p1'" in warnings[0]
    assert "case-sensitive" in warnings[0]


def test_consistent_names_produce_no_warnings() -> None:
    """A case that uses one spelling per entity needs no warning."""
    case, errors = load_case("case.csv", to_csv(valid_rows()))
    assert errors == []
    assert case is not None
    assert case_variant_warnings(case.records) == []
