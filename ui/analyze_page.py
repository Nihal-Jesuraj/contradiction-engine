"""Analyze & Conflicts page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from contradiction_engine.detectors import run_all_detectors
from contradiction_engine.models import Conflict, score_conflicts

from .widgets import (
    KIND_LABELS,
    page_header,
    render_detector_docs,
    render_severity,
)


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
        conflicts = run_all_detectors(case.records, case.graph())
        st.session_state.conflicts = conflicts
        st.session_state.score = score_conflicts(conflicts, case.ground_truth)
        st.session_state.analysis_done = True
    _render_results()


def _render_results() -> None:
    """Render metrics, scoring, and the conflict explorer."""
    case = st.session_state.case
    conflicts = st.session_state.conflicts
    _analysis_metrics(len(case.records), conflicts)
    _render_score()
    if not conflicts:
        st.warning(
            "No contradictions found. This means the records are consistent "
            "under these rules, not that they are true."
        )
    else:
        _conflict_table(case.records, conflicts)
    render_detector_docs()


def _analysis_metrics(record_count: int, conflicts: list[Conflict]) -> None:
    """Show record and per-kind conflict counts."""
    columns = st.columns(7)
    columns[0].metric("Records", record_count)
    columns[1].metric("Conflicts", len(conflicts))
    for column, (kind, label) in zip(columns[2:], KIND_LABELS.items()):
        column.metric(label, sum(1 for conflict in conflicts if conflict.kind == kind))


def _render_score() -> None:
    """Show precision, recall, and F1 when ground truth exists."""
    score = st.session_state.score
    if score is None or not score.available:
        st.caption("Ground truth not available")
        return
    st.write(
        f"Precision **{score.precision:.2f}** · Recall **{score.recall:.2f}** · "
        f"F1 **{score.f1:.2f}** · {score.matched}/{score.planted} matched"
    )


def _conflict_table(records: list, conflicts: list[Conflict]) -> None:
    """Show the conflict table and the selected conflict's detail."""
    table = [
        {
            "kind": KIND_LABELS.get(conflict.kind, conflict.kind),
            "severity": conflict.severity,
            "records": ", ".join(conflict.record_ids),
            "rule": conflict.rule_text,
        }
        for conflict in conflicts
    ]
    st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)
    choice = st.selectbox(
        "Inspect a conflict",
        range(len(conflicts)),
        format_func=lambda index: (
            f"{KIND_LABELS.get(conflicts[index].kind, conflicts[index].kind)}: "
            + ", ".join(conflicts[index].record_ids)
        ),
    )
    _render_conflict(records, conflicts[choice])


def _render_conflict(records: list, conflict: Conflict) -> None:
    """Show the conflicting records next to the rule and numbers."""
    by_id = {record.id: record for record in records}
    left, right = st.columns(2)
    with left:
        st.subheader("Conflicting records")
        for record_id in conflict.record_ids:
            record = by_id.get(record_id)
            if record is not None:
                st.caption(f"{record_id} · {record.record_type}")
                st.json(record.to_dict())
    with right:
        st.subheader("Broken rule")
        st.write(conflict.rule_text)
        st.write(conflict.explanation)
        st.table(pd.DataFrame(
            [{"number": key, "value": str(value)}
             for key, value in conflict.numbers.items()]
        ))
        render_severity(conflict.severity)
