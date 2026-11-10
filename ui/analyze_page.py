"""Analyze & Conflicts page."""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from contradiction_engine.detectors import run_all_detectors
from contradiction_engine.models import Case, Conflict, score_conflicts

from .status_tiles import render_status_tiles
from .widgets import (
    case_graph,
    KIND_LABELS,
    RECORD_TYPE_LABELS,
    highest_severity,
    numbers_frame,
    page_header,
    record_frame,
    render_detector_docs,
    render_severity,
)

ROUTE_KINDS = ("location", "claim_location")
PAGE_SIZE = 15


def render_analyze_page() -> None:
    """Run the detectors and show the conflict detail."""
    case = st.session_state.case
    page_header(
        "Analyze & conflicts",
        "Run the detectors, then inspect each broken rule and its evidence.",
    )
    if case is None:
        st.info("Generate or upload a case on the first page.")
        return
    if st.button("ANALYZE", type="primary"):
        _run_analysis(case)
    if not st.session_state.analysis_done:
        st.info("Not analysed yet. Press ANALYZE.")
        return
    _render_results()


def _reset_pages() -> None:
    """Forget how many conflict cards each tab had expanded."""
    for key in [key for key in st.session_state if str(key).startswith("shown_")]:
        del st.session_state[key]


def _run_analysis(case: Case) -> None:
    """Run all detectors, timing only the detector call."""
    _reset_pages()
    with st.status("Running detectors", expanded=False) as status:
        graph = case_graph(case)
        started = time.perf_counter()
        conflicts = run_all_detectors(case.records, graph)
        runtime_ms = (time.perf_counter() - started) * 1000.0
        score = score_conflicts(conflicts, case.ground_truth)
        status.update(
            label=f"Analysed {len(case.records)} records",
            state="complete",
        )
    st.session_state.conflicts = conflicts
    st.session_state.score = score
    st.session_state.runtime_ms = runtime_ms
    st.session_state.analysis_done = True
    st.toast(f"Analysis complete: {len(conflicts)} conflict(s) in {runtime_ms:.0f} ms")


def _render_results() -> None:
    """Render metrics, scoring, conflicts, and detector documentation."""
    case = st.session_state.case
    conflicts = st.session_state.conflicts
    _render_kpis(len(case.records), conflicts)
    _render_score()
    render_status_tiles(case, conflicts)
    if conflicts:
        _render_conflicts(case, conflicts)
    else:
        st.warning(
            "No contradictions found. This means the records are consistent "
            "under these rules, not that they are true."
        )
    render_detector_docs()


def _render_kpis(record_count: int, conflicts: list[Conflict]) -> None:
    """Show records, conflict count, highest severity, and runtime."""
    columns = st.columns(4)
    columns[0].metric("Records", record_count)
    columns[1].metric("Conflicts", len(conflicts))
    severity = highest_severity(conflicts)
    columns[2].metric("Highest severity", "None" if severity is None else f"{severity:.2f}")
    columns[3].metric("Runtime", f"{st.session_state.runtime_ms:.0f} ms")


def _render_score() -> None:
    """Show ground-truth scoring in its own bordered panel."""
    score = st.session_state.score
    with st.container(border=True):
        st.caption("Scored against ground truth")
        if score is None or not score.available:
            st.write("Ground truth not available")
            return
        columns = st.columns(4)
        columns[0].metric("Precision", f"{score.precision:.2f}")
        columns[1].metric("Recall", f"{score.recall:.2f}")
        columns[2].metric("F1", f"{score.f1:.2f}")
        columns[3].metric("Matched", f"{score.matched}/{score.planted}")
        st.caption(
            "A score of 1.0 on generated data holds by construction: planted "
            "conflicts are isolated and every match is counted."
        )


def _render_conflicts(case: Case, conflicts: list[Conflict]) -> None:
    """Group conflicts into tabs by readable kind."""
    groups = _group_conflicts(conflicts)
    tabs = st.tabs([f"{KIND_LABELS.get(kind, kind)} ({len(items)})"
                    for kind, items in groups])
    for tab, (kind, items) in zip(tabs, groups):
        with tab:
            _render_tab(case, kind, items)


def _show_more(key: str) -> None:
    """Callback: reveal another page of conflict cards."""
    st.session_state[key] = st.session_state.get(key, PAGE_SIZE) + PAGE_SIZE


def _render_tab(case: Case, kind: str, items: list[Conflict]) -> None:
    """Render the first cards of one tab, with a Show more button."""
    key = f"shown_{kind}"
    shown = st.session_state.get(key, PAGE_SIZE)
    for conflict in items[:shown]:
        _render_conflict(case, conflict)
    if len(items) > shown:
        st.caption(f"Showing {shown} of {len(items)}")
        st.button("Show more", key=f"more_{kind}", on_click=_show_more,
                  args=(key,))


def _group_conflicts(
    conflicts: list[Conflict],
) -> list[tuple[str, list[Conflict]]]:
    """Return conflicts grouped in readable-kind order."""
    groups: list[tuple[str, list[Conflict]]] = []
    for kind in KIND_LABELS:
        items = [conflict for conflict in conflicts if conflict.kind == kind]
        if items:
            groups.append((kind, items))
    known = set(KIND_LABELS)
    unknown: dict[str, list[Conflict]] = {}
    for conflict in conflicts:
        if conflict.kind not in known:
            unknown.setdefault(conflict.kind, []).append(conflict)
    groups.extend(unknown.items())
    return groups


def _render_conflict(case: Case, conflict: Conflict) -> None:
    """Render one conflict as a bordered evidence card."""
    with st.container(border=True):
        render_severity(conflict.severity)
        st.caption(KIND_LABELS.get(conflict.kind, conflict.kind))
        _render_records(case, conflict)
        st.markdown("**Broken rule**")
        st.write(conflict.rule_text)
        st.markdown("**Numbers**")
        st.dataframe(numbers_frame(conflict.numbers), hide_index=True,
                     width="stretch")
        st.markdown("**Explanation**")
        st.write(conflict.explanation)
        if conflict.kind in ROUTE_KINDS:
            _render_route(case, conflict)
        if conflict.kind == "device_state":
            _render_device_timeline(conflict)


def _render_records(case: Case, conflict: Conflict) -> None:
    """Show the conflicting records side by side as small tables."""
    by_id = {record.id: record for record in case.records}
    records = [by_id[record_id] for record_id in conflict.record_ids
               if record_id in by_id]
    if not records:
        st.caption("Referenced records are not present in this case.")
        return
    columns = st.columns(min(len(records), 3))
    for index, record in enumerate(records):
        with columns[index % len(columns)]:
            label = RECORD_TYPE_LABELS.get(record.record_type, record.record_type)
            st.caption(f"{record.id} · {label}")
            st.dataframe(record_frame(record), hide_index=True, width="stretch")


def _render_route(case: Case, conflict: Conflict) -> None:
    """Draw the road map with the conflict's shortest route highlighted."""
    path = _shortest_path(case, conflict)
    if not path:
        return
    st.markdown("**Shortest road route**")
    required = conflict.numbers.get("required_minutes")
    if required is not None:
        st.caption(f"{' -> '.join(path)} · {required} minutes required")
    else:
        st.caption(" -> ".join(path))
    st.graphviz_chart(case_graph(case).to_dot(path), width="stretch")


def _shortest_path(case: Case, conflict: Conflict) -> list[str]:
    """Recover the shortest path recorded in the conflict numbers."""
    text = str(conflict.numbers.get("shortest_path", ""))
    path = [place for place in text.split(" -> ") if place]
    if path:
        return path
    start = conflict.numbers.get("from_place") or conflict.numbers.get("claimed_place")
    target = conflict.numbers.get("to_place") or conflict.numbers.get("seen_place")
    if not isinstance(start, str) or not isinstance(target, str):
        return []
    distances, previous = case_graph(case).dijkstra(start)
    if target not in distances:
        return []
    return case_graph(case).shortest_path(previous, start, target)


def _render_device_timeline(conflict: Conflict) -> None:
    """Plot the off-state interval against the activity time."""
    since = _parse_time(conflict.numbers.get("state_since"))
    until = _parse_time(conflict.numbers.get("state_until"))
    activity = _parse_time(conflict.numbers.get("activity_time"))
    offset = conflict.numbers.get("minutes_into_state")
    if since is None or until is None or activity is None or offset is None:
        return
    st.markdown("**State timeline**")
    st.caption(
        f"Off from {since:%H:%M:%S} to {until:%H:%M:%S}; "
        f"activity at {activity:%H:%M:%S}."
    )
    frame = pd.DataFrame(
        {
            "Moment": ("State begins", "Activity", "State ends"),
            "Minutes after state start": (
                0.0,
                float(offset),
                (until - since).total_seconds() / 60.0,
            ),
        }
    )
    st.bar_chart(frame, x="Moment", y="Minutes after state start",
                 horizontal=True)


def _parse_time(value: object) -> datetime | None:
    """Parse an ISO timestamp from a conflict's numbers."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
