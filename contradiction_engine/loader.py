"""CSV/JSON upload parsing and validation.

The loader builds a brand-new ``Case`` and never mutates shared state. If any
row is invalid the caller receives ``(None, errors)`` with the first five
reasons, so the UI can keep the previous case untouched.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone

from .models import (
    CLAIM_TYPES,
    CONFLICT_KINDS,
    CSV_FIELDS,
    DEFAULT_PLACES,
    DEFAULT_ROADS,
    DEVICE_STATES,
    RECORD_TYPES,
    Case,
    Evidence,
    GroundTruth,
    build_place_graph,
    is_connected,
)

MAX_ERRORS = 5

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "state": ("device", "state"),
    "activity": ("device", "action"),
    "sighting": ("person", "place"),
    "message": ("person",),
    "login": ("person", "account"),
    "claim": ("person", "claim", "end_timestamp"),
}

CLAIM_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "did_not_access": ("account",),
    "claimed_at": ("place",),
}

ENTITY_FIELDS: tuple[str, ...] = ("person", "device", "account")


def case_variant_warnings(records: list[Evidence]) -> list[str]:
    """Report entity names that differ only by case.

    Inputs: validated evidence records.
    Outputs: one warning per case-insensitive duplicate spelling.
    Complexity: O(n) time, O(n) space.
    """
    seen: dict[tuple[str, str], str] = {}
    reported: set[tuple[str, str]] = set()
    warnings: list[str] = []
    for record in records:
        for name in ENTITY_FIELDS:
            value = getattr(record, name)
            if not value:
                continue
            key = (name, value.casefold())
            original = seen.get(key)
            if original is None:
                seen[key] = value
            elif original != value and key not in reported:
                reported.add(key)
                warnings.append(
                    f"{name} {original!r} and {value!r} differ only by case; "
                    "matching is case-sensitive, so a conflict may be missed."
                )
    return warnings


def parse_timestamp(value: str | datetime, label: str = "timestamp") -> datetime:
    """Parse an ISO-8601 value into an aware UTC datetime.

    Inputs: a string or datetime, and a label used in error messages.
    Outputs: an aware ``datetime`` in UTC.
    Complexity: O(len(value)) time, O(1) space.
    Raises ValueError when the value cannot be parsed.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if not text:
            raise ValueError(f"{label} is empty")
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{label} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_case(
    filename: str,
    data: bytes,
    truth_data: bytes | None = None,
    places_data: bytes | None = None,
) -> tuple[Case | None, list[str]]:
    """Parse and validate an uploaded case.

    Inputs: a filename, its bytes, optional ground-truth bytes, and optional
    places bytes.
    Outputs: ``(case, [])`` on success or ``(None, errors)`` on failure.
    Complexity: O(n log n) time for n rows, O(n) space.
    """
    try:
        rows, embedded_truth, embedded_name = _parse_document(filename, data)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [f"file: {exc}"]

    places: dict[str, tuple[float, float]] = dict(DEFAULT_PLACES)
    roads: list[tuple[str, str, float | None]] = list(DEFAULT_ROADS)
    if places_data is not None:
        try:
            places, roads = _parse_places(places_data)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return None, [f"places file: {exc}"]

    truth_rows = list(embedded_truth)
    if truth_data is not None:
        try:
            truth_rows.extend(_parse_truth_document(truth_data))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return None, [f"ground truth file: {exc}"]

    name = embedded_name or _filename_stem(filename) or "uploaded case"
    case, errors = _build_case(name, rows, truth_rows, places, roads)
    if errors:
        return None, errors[:MAX_ERRORS]
    return case, []


def _parse_document(
    filename: str,
    data: bytes,
) -> tuple[list[dict[str, object]], list[dict[str, object]], str | None]:
    """Parse CSV or JSON bytes into rows, embedded truth, and an optional name."""
    text = data.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("the upload is empty")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    looks_json = text.lstrip().startswith(("{", "["))
    if suffix == "json" or (suffix != "csv" and looks_json):
        return _parse_json_document(text)
    return _parse_csv_document(text), [], None


def _parse_csv_document(text: str) -> list[dict[str, object]]:
    """Read a CSV document into raw dictionaries."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header row")
    return [dict(row) for row in reader]


def _parse_json_document(
    text: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], str | None]:
    """Read a JSON list or an object with records and ground truth."""
    document = json.loads(text)
    if isinstance(document, list):
        return _require_object_rows(document, "records"), [], None
    if not isinstance(document, dict):
        raise ValueError("JSON must be a list or an object")
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("JSON object needs a 'records' list")
    truth = document.get("ground_truth", [])
    if not isinstance(truth, list):
        raise ValueError("'ground_truth' must be a list")
    name = document.get("name")
    return (
        _require_object_rows(records, "records"),
        _require_object_rows(truth, "ground_truth"),
        str(name) if name else None,
    )


def _require_object_rows(
    rows: list[object],
    label: str,
) -> list[dict[str, object]]:
    """Reject non-object entries in a JSON row list."""
    result: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"{label} entry {index} is not an object")
        result.append(row)
    return result


def _parse_truth_document(data: bytes) -> list[dict[str, object]]:
    """Read a standalone ground-truth JSON document."""
    document = json.loads(data.decode("utf-8-sig"))
    if isinstance(document, dict):
        document = document.get("ground_truth")
    if not isinstance(document, list):
        raise ValueError("expected a list of ground-truth entries")
    return _require_object_rows(document, "ground_truth")


def _parse_places(
    data: bytes,
) -> tuple[dict[str, tuple[float, float]], list[tuple[str, str, float | None]]]:
    """Validate a custom place map and road list.

    Inputs: JSON bytes with ``places`` and ``edges``.
    Outputs: a place table and a road list.
    Complexity: O(V + E) time and space.
    """
    document = json.loads(data.decode("utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError("expected a JSON object")
    places = _parse_place_table(document.get("places"))
    roads = _parse_roads(document.get("edges"))
    try:
        graph = build_place_graph(places, roads)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not is_connected(graph):
        raise ValueError("the road network is not connected")
    return places, roads


def _parse_place_table(raw_places: object) -> dict[str, tuple[float, float]]:
    """Validate the place-name to coordinate table."""
    if not isinstance(raw_places, dict) or not raw_places:
        raise ValueError("'places' must be a non-empty object")
    if len(raw_places) < 2:
        raise ValueError("at least two places are required")
    places: dict[str, tuple[float, float]] = {}
    for name, coordinates in raw_places.items():
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
            raise ValueError(f"place {name!r} needs [latitude, longitude]")
        try:
            latitude = float(coordinates[0])
            longitude = float(coordinates[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"place {name!r} has non-numeric coordinates") from exc
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError(f"place {name!r} has non-finite coordinates")
        if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
            raise ValueError(f"place {name!r} is outside valid coordinates")
        places[str(name)] = (latitude, longitude)
    return places


def _parse_roads(raw_edges: object) -> list[tuple[str, str, float | None]]:
    """Validate the road list and optional per-edge minutes."""
    if not isinstance(raw_edges, list):
        raise ValueError("'edges' must be a list")
    roads: list[tuple[str, str, float | None]] = []
    for index, edge in enumerate(raw_edges, start=1):
        if not isinstance(edge, (list, tuple)) or len(edge) not in (2, 3):
            raise ValueError(f"edge {index} must be [a, b] or [a, b, minutes]")
        first, second = str(edge[0]), str(edge[1])
        minutes: float | None = None
        if len(edge) == 3:
            try:
                minutes = float(edge[2])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"edge {index} has non-numeric minutes") from exc
            if not math.isfinite(minutes) or minutes < 0:
                raise ValueError(f"edge {index} needs finite non-negative minutes")
        roads.append((first, second, minutes))
    return roads


def _filename_stem(filename: str) -> str:
    """Return a filename without its directory or extension."""
    base = filename.replace("\\", "/").split("/")[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def _text(value: object) -> str:
    """Convert a raw cell to a stripped string."""
    if value is None:
        return ""
    return str(value).strip()


def _generate_id(values: dict[str, str], row_number: int) -> str:
    """Build a deterministic ID for a row that has none."""
    canonical = "|".join(f"{field}={values[field]}" for field in CSV_FIELDS)
    digest = hashlib.sha1(
        f"{canonical}|row={row_number}".encode("utf-8")
    ).hexdigest()
    return f"UPL-{digest[:10]}"


def _build_case(
    name: str,
    rows: list[dict[str, object]],
    truth_rows: list[dict[str, object]],
    places: dict[str, tuple[float, float]],
    roads: list[tuple[str, str, float | None]],
) -> tuple[Case | None, list[str]]:
    """Turn raw rows into a validated case, collecting errors."""
    errors: list[str] = []
    if not rows:
        return None, ["file: the upload contains no records"]

    records: list[Evidence] = []
    row_numbers: list[int] = []
    records_by_id: dict[str, Evidence] = {}
    seen_ids: set[str] = set()

    for row_number, row in enumerate(rows, start=1):
        try:
            record = _build_record(row, row_number, places, seen_ids)
        except ValueError as exc:
            errors.append(f"row {row_number}: {exc}")
            continue
        records.append(record)
        row_numbers.append(row_number)
        seen_ids.add(record.id)
        records_by_id[record.id] = record

    errors.extend(_check_dependencies(records, row_numbers, records_by_id))
    truth, truth_errors = _build_truth(truth_rows, records_by_id)
    errors.extend(truth_errors)

    if errors:
        return None, errors
    return Case(name=name, records=records, ground_truth=truth,
                places=places, roads=roads), []


def _build_record(
    row: dict[str, object],
    row_number: int,
    places: dict[str, tuple[float, float]],
    seen_ids: set[str],
) -> Evidence:
    """Validate one raw row and return an ``Evidence`` record."""
    values = {field: _text(row.get(field)) for field in CSV_FIELDS}
    record_type = values["record_type"]
    if record_type not in RECORD_TYPES:
        raise ValueError(f"unknown record_type {record_type!r}")
    _validate_row(record_type, values, places)

    timestamp = parse_timestamp(values["timestamp"])
    record_id = values["id"] or _generate_id(values, row_number)
    if record_id in seen_ids:
        raise ValueError(f"duplicate id {record_id!r}")
    end_timestamp = (
        _claim_end(values, timestamp) if record_type == "claim" else None
    )
    return Evidence(
        id=record_id,
        timestamp=timestamp,
        record_type=record_type,
        person=values["person"],
        device=values["device"],
        place=values["place"],
        state=values["state"],
        action=values["action"],
        account=values["account"],
        depends_on=values["depends_on"],
        claim=values["claim"],
        end_timestamp=end_timestamp,
        text=values["text"],
    )


def _validate_row(
    record_type: str,
    values: dict[str, str],
    places: dict[str, tuple[float, float]],
) -> None:
    """Check required fields and type-specific domains."""
    missing = [
        field for field in REQUIRED_FIELDS[record_type] if not values[field]
    ]
    if missing:
        raise ValueError("missing required field(s): " + ", ".join(missing))
    if record_type == "state" and values["state"] not in DEVICE_STATES:
        raise ValueError(f"state must be one of {', '.join(DEVICE_STATES)}")
    if record_type == "sighting" and values["place"] not in places:
        raise ValueError(f"unknown place {values['place']!r}")
    if record_type != "claim":
        return
    claim_type = values["claim"]
    if claim_type not in CLAIM_TYPES:
        raise ValueError(f"claim must be one of {', '.join(CLAIM_TYPES)}")
    claim_missing = [
        field for field in CLAIM_REQUIRED_FIELDS[claim_type] if not values[field]
    ]
    if claim_missing:
        raise ValueError(
            "missing required field(s): " + ", ".join(claim_missing)
        )
    if claim_type == "claimed_at" and values["place"] not in places:
        raise ValueError(f"unknown place {values['place']!r}")


def _claim_end(values: dict[str, str], start: datetime) -> datetime:
    """Parse and validate a claim's end timestamp."""
    end = parse_timestamp(values["end_timestamp"], "end_timestamp")
    if end <= start:
        raise ValueError("end_timestamp must be after timestamp")
    return end


def _check_dependencies(
    records: list[Evidence],
    row_numbers: list[int],
    records_by_id: dict[str, Evidence],
) -> list[str]:
    """Reject message dependencies that do not name an uploaded message."""
    errors: list[str] = []
    for record, row_number in zip(records, row_numbers):
        if not record.depends_on:
            continue
        parent = records_by_id.get(record.depends_on)
        if parent is None or parent.record_type != "message":
            errors.append(
                f"row {row_number}: depends_on {record.depends_on!r} "
                "is not a message in this upload"
            )
    return errors


def _build_truth(
    truth_rows: list[dict[str, object]],
    records_by_id: dict[str, Evidence],
) -> tuple[list[GroundTruth], list[str]]:
    """Validate ground-truth entries and return them with any errors."""
    truth: list[GroundTruth] = []
    errors: list[str] = []
    for index, row in enumerate(truth_rows, start=1):
        kind = _text(row.get("kind"))
        raw_ids = row.get("record_ids")
        if kind not in CONFLICT_KINDS:
            errors.append(f"ground truth {index}: unknown kind {kind!r}")
            continue
        if not isinstance(raw_ids, (list, tuple)) or not raw_ids:
            errors.append(f"ground truth {index}: record_ids must be a non-empty list")
            continue
        record_ids = tuple(_text(value) for value in raw_ids)
        missing = [value for value in record_ids if value not in records_by_id]
        if missing:
            errors.append(
                f"ground truth {index}: unknown record id(s): "
                + ", ".join(missing)
            )
            continue
        truth.append(GroundTruth(kind, record_ids, _text(row.get("note"))))
    return truth, errors
