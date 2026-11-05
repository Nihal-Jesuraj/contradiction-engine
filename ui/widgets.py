"""Shared HUD widgets, labels, and session-state helpers."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from contradiction_engine.algorithms.graph import WeightedGraph
from contradiction_engine.models import Case, CaseIndex, Conflict, Evidence

PAGES: tuple[str, ...] = (
    "Generate / Upload",
    "Analyze & Conflicts",
    "Evidence Explorer",
)

KIND_LABELS: dict[str, str] = {
    "device_state": "Device was off",
    "location": "Impossible travel",
    "message_order": "Reply before original",
    "message_cycle": "Circular replies",
    "claim": "Denied access vs login",
    "claim_location": "Claimed place vs sighting",
}

RECORD_TYPE_LABELS: dict[str, str] = {
    "state": "Device state",
    "activity": "Activity",
    "sighting": "Sighting",
    "message": "Message",
    "login": "Login",
    "claim": "Claim",
}

CLAIM_LABELS: dict[str, str] = {
    "did_not_access": "Denied access",
    "claimed_at": "Claimed place",
}

NUMBER_LABELS: dict[str, str] = {
    "device": "Device",
    "state": "State",
    "record_type": "Record type",
    "activity_time": "Activity time",
    "state_since": "State since",
    "state_until": "State until",
    "minutes_into_state": "Minutes into state",
    "from_place": "From place",
    "to_place": "To place",
    "elapsed_minutes": "Elapsed minutes",
    "required_minutes": "Required minutes",
    "shortfall_minutes": "Shortfall minutes",
    "shortest_path": "Shortest path",
    "parent_time": "Parent time",
    "child_time": "Child time",
    "seconds_early": "Seconds early",
    "parent_topological_index": "Parent order index",
    "child_topological_index": "Child order index",
    "cycle_length": "Cycle length",
    "cycle": "Cycle",
    "account": "Account",
    "claim_start": "Claim start",
    "claim_end": "Claim end",
    "first_login": "First login",
    "login_count": "Login count",
    "minutes_after_claim_start": "Minutes after claim start",
    "claimed_place": "Claimed place",
    "seen_place": "Seen place",
    "window_start": "Window start",
    "window_end": "Window end",
    "seen_at": "Seen at",
    "nearest_edge_minutes": "Nearer edge minutes",
}

DETECTOR_DOCS: tuple[tuple[str, str, str], ...] = (
    ("Device was off", "HashTable grouping, merge-sorted state intervals, binary search", "O(n log n)"),
    ("Impossible travel", "HashTable, merge sort, Dijkstra with a min-heap, cached per source", "O(n log n + V(V+E) log V)"),
    ("Reply before original / Circular replies", "Directed dependency graph, colouring DFS, topological order", "O(V + E)"),
    ("Denied access vs login", "HashTable, merge sort, lower/upper binary-search bounds", "O(n log n + c log n)"),
    ("Claimed place vs sighting", "HashTable, merge sort, window bounds, Dijkstra from the claimed place", "O(n log n + V(V+E) log V)"),
)

RESPONSIBLE_USE = (
    "Investigative-support prototype. A conflict means records disagree under "
    "the stated rules, not that a person is guilty or lying."
)


def ensure_state() -> None:
    """Create the session keys shared by every page."""
    defaults: dict[str, object] = {
        "case": None,
        "index": None,
        "conflicts": [],
        "score": None,
        "analysis_done": False,
        "runtime_ms": 0.0,
        "case_source": "No case loaded",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def case_graph(case: Case) -> WeightedGraph:
    """Return the case's road graph, building it once per case object."""
    cached = st.session_state.get("graph_cache")
    if cached is None or cached[0] is not case:
        cached = (case, case.graph())
        st.session_state.graph_cache = cached
    return cached[1]


def store_case(case: Case, source: str) -> None:
    """Replace the active case and clear the previous analysis."""
    st.session_state.case = case
    st.session_state.index = CaseIndex(case.records)
    st.session_state.conflicts = []
    st.session_state.score = None
    st.session_state.analysis_done = False
    st.session_state.runtime_ms = 0.0
    st.session_state.case_source = source


def render_sidebar() -> str:
    """Render navigation, the current-case card, and the responsibility note."""
    with st.sidebar:
        page = st.radio("Page", PAGES)
        st.divider()
        st.caption("Current case")
        with st.container(border=True):
            _render_case_card()
        st.warning(RESPONSIBLE_USE)
    return page


def _render_case_card() -> None:
    """Show the compact case identity used on every page."""
    case = st.session_state.case
    if case is None:
        st.write("No case loaded")
        return
    index = st.session_state.index
    st.write(case.name)
    st.caption(f"{len(case.records)} records · {len(index.people())} people")
    st.caption(f"{len(index.devices())} devices · {len(case.places)} places")
    st.caption(f"Source · {st.session_state.case_source}")


def render_app_header() -> None:
    """Render the slim application identity line."""
    st.caption("Contradiction Engine")
    st.write("Temporal evidence consistency for fictional investigations.")


def page_header(title: str, description: str) -> None:
    """Render the page title and its one-sentence description."""
    st.title(title)
    st.write(description)


def hero_strip() -> None:
    """Render the three-step workflow strip with directional arrows."""
    steps = (
        ("1", "Generate or upload"),
        ("2", "Analyze"),
        ("3", "Explore"),
    )
    with st.container(border=True):
        columns = st.columns([1, 0.18, 1, 0.18, 1])
        for index, (number, label) in enumerate(steps):
            with columns[index * 2]:
                st.caption(f"Step {number}")
                st.write(f"**{number}** · {label}")
            if index < len(steps) - 1:
                with columns[index * 2 + 1]:
                    st.write("→")


def severity_word(severity: float) -> tuple[str, str]:
    """Return the severity word and badge colour for a conflict."""
    if severity >= 0.85:
        return "HIGH", "red"
    if severity >= 0.50:
        return "MEDIUM", "orange"
    return "LOW", "gray"


def render_severity(severity: float) -> None:
    """Render the text-and-colour severity badge."""
    word, colour = severity_word(severity)
    st.badge(f"{word} {severity:.2f}", color=colour)


def format_time(value: datetime) -> str:
    """Return a timestamp as HH:mm:ss."""
    return value.strftime("%H:%M:%S")


def format_datetime(value: datetime) -> str:
    """Return a timestamp as a readable date and time."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def record_frame(record: Evidence) -> pd.DataFrame:
    """Return a two-column table of a record's non-empty fields."""
    values = record.to_dict()
    labels = (
        ("timestamp", "Time"),
        ("record_type", "Type"),
        ("id", "ID"),
        ("person", "Person"),
        ("device", "Device"),
        ("place", "Place"),
        ("state", "State"),
        ("action", "Action"),
        ("account", "Account"),
        ("depends_on", "Depends on"),
        ("claim", "Claim"),
        ("end_timestamp", "End"),
        ("text", "Text"),
    )
    rows: list[dict[str, str]] = []
    for name, label in labels:
        value = _record_value(name, values.get(name, ""), record)
        if value:
            rows.append({"Field": label, "Value": value})
    return pd.DataFrame(rows)


def _record_value(name: str, raw: str, record: Evidence) -> str:
    """Format one record field for a compact detail table."""
    if not raw:
        return ""
    if name == "timestamp":
        return format_datetime(record.timestamp)
    if name == "end_timestamp" and record.end_timestamp is not None:
        return format_datetime(record.end_timestamp)
    if name == "record_type":
        return RECORD_TYPE_LABELS.get(raw, raw)
    if name == "claim":
        return CLAIM_LABELS.get(raw, raw.replace("_", " "))
    return raw


def records_frame(records: list[Evidence]) -> pd.DataFrame:
    """Return the explorer table with time and record type first."""
    rows: list[dict[str, str]] = []
    for record in records:
        rows.append({
            "Time": format_time(record.timestamp),
            "Type": RECORD_TYPE_LABELS.get(record.record_type, record.record_type),
            "Date": record.timestamp.strftime("%Y-%m-%d"),
            "ID": record.id,
            "Person": record.person,
            "Device": record.device,
            "Place": record.place,
            "State": record.state,
            "Action": record.action,
            "Account": record.account,
            "Depends on": record.depends_on,
            "Claim": CLAIM_LABELS.get(record.claim, record.claim.replace("_", " ")),
            "End": (
                format_datetime(record.end_timestamp)
                if record.end_timestamp is not None
                else ""
            ),
            "Text": record.text,
        })
    frame = pd.DataFrame(rows)
    for column in list(frame.columns):
        if column in ("Time", "Type", "Date", "ID"):
            continue
        if frame[column].eq("").all():
            frame = frame.drop(columns=column)
    return frame


def numbers_frame(numbers: dict[str, object]) -> pd.DataFrame:
    """Return a compact two-column table for conflict numbers."""
    rows = [
        {
            "Metric": NUMBER_LABELS.get(key, key.replace("_", " ").capitalize()),
            "Value": _number_text(value),
        }
        for key, value in numbers.items()
    ]
    return pd.DataFrame(rows)


def _number_text(value: object) -> str:
    """Format one conflict number without mixing column types."""
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def highest_severity(conflicts: list[Conflict]) -> float | None:
    """Return the largest conflict severity, or None when there are none."""
    if not conflicts:
        return None
    highest = conflicts[0].severity
    for conflict in conflicts[1:]:
        if conflict.severity > highest:
            highest = conflict.severity
    return highest


def render_detector_docs() -> None:
    """List each detector's algorithm and complexity."""
    with st.expander("How the detectors work"):
        st.table(pd.DataFrame(
            DETECTOR_DOCS,
            columns=("Detector", "Algorithm", "Complexity"),
        ))
