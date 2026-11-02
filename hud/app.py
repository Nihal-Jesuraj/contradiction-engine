"""ChronoClash HUD - a Python-only Streamlit command terminal.

Run with:
    streamlit run hud/app.py

The FastAPI service must be running (see README). Every algorithmic result is
read from that API; this file only renders and orchestrates interactions.

Interactions deliberately use Streamlit buttons, segmented controls and
dialogs rather than query-string anchors. A click still reruns the script, but
the browser stays on the same page and never performs a full navigation.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hud import render  # noqa: E402
from hud.client import ApiClient, ApiError  # noqa: E402
from hud.formatting import fmt_ms, fmt_pct  # noqa: E402


ASSETS = Path(__file__).resolve().parent / "assets"
SOURCES = ("cctv", "call", "gps", "bank", "device", "witness")
BENCH_SIZES = (1_000, 10_000, 100_000, 1_000_000)
TOP_K_OPTIONS = (5, 8, 12, 20)
GAP_THRESHOLDS = (300, 900, 1800, 3600)
ALL_SUBJECTS = "ALL SUBJECTS"


st.set_page_config(
    page_title="ChronoClash // Temporal Contradiction Terminal",
    page_icon="CC",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def _flash(message: str, tone: str = "success", detail: str = "") -> None:
    st.session_state["flash"] = {"message": message, "tone": tone, "detail": detail}


def _inject_css() -> None:
    css = (ASSETS / "hud.css").read_text(encoding="utf-8")
    fonts = (ASSETS / "fonts.css").read_text(encoding="utf-8")
    streamlit_css = (ASSETS / "streamlit.css").read_text(encoding="utf-8")
    refined = (ASSETS / "refined.css").read_text(encoding="utf-8")
    st.markdown(
        f"<style>{fonts}\n{css}\n{streamlit_css}\n{refined}</style>",
        unsafe_allow_html=True,
    )


def _apply_pending() -> None:
    """Move deferred selections into widget state before those widgets exist."""
    for pending, key in (
        ("pending_entity", "entity_filter"),
        ("pending_top_k", "top_k_ctl"),
        ("pending_conflict", "focused_conflict"),
    ):
        if pending in st.session_state:
            st.session_state[key] = st.session_state.pop(pending)


def _defaults() -> None:
    st.session_state.setdefault("entity_filter", ALL_SUBJECTS)
    st.session_state.setdefault("top_k_ctl", 8)
    st.session_state.setdefault("timeline_zoom", 1.0)
    st.session_state.setdefault("gap_threshold", 900)


def _run_scan(client: ApiClient, mode: str) -> None:
    label = "FULL RESCAN" if mode == "full" else "INCREMENTAL SWEEP"
    with st.spinner(f"{label} // rebuilding detector cascade"):
        result = client.analyze(mode)
    _flash(
        f"{label} COMPLETE",
        "success",
        f'{result.get("conflicts_found", 0)} conflicts - '
        f'{fmt_ms(result.get("analysis_ms"))} - '
        f'{result.get("events_per_sec", 0):,.0f} ev/s',
    )
    st.rerun()


def _bench(client: ApiClient) -> dict[str, Any] | None:
    live = st.session_state.get("bench_live")
    if live:
        return live
    try:
        return client.latest_bench()
    except ApiError:
        return None


# --------------------------------------------------------------------------
# Dialogs. Each dialog is only invoked from its button branch, so closing it
# or submitting a form simply ends the rerun without reopening the modal.
# --------------------------------------------------------------------------

@st.dialog("APPEND EVIDENCE", width="large")
def _add_dialog(client: ApiClient, state: dict[str, Any], selected: str | None) -> None:
    default_ts = (state.get("window") or {}).get("end") or datetime.now(
        timezone.utc
    ).isoformat()
    default_ts = str(default_ts).replace(".000", "")
    st.markdown(
        '<p class="dialog-lead">Insert one normalized record into the active case. '
        "Only the local interval neighbourhood is rechecked; existing conflicts remain "
        "untouched until a full rescan.</p>",
        unsafe_allow_html=True,
    )
    with st.form("dlg-add-form", border=False):
        c1, c2 = st.columns(2, gap="small")
        with c1:
            timestamp = st.text_input("TIMESTAMP (ISO-8601)", value=default_ts)
            entity = st.text_input("SUBJECT", value=selected or "SUBJ-INC-01")
            source = st.selectbox("SOURCE", SOURCES, index=0)
        with c2:
            device = st.text_input("DEVICE ID", value="DEV-INC-001")
            action_text = st.text_input("ACTION", value="MANUAL_OBSERVATION")
            duration = st.number_input(
                "DURATION (SECONDS)", min_value=0.0, value=0.0, step=30.0
            )
        c3, c4, c5 = st.columns(3, gap="small")
        with c3:
            lat = st.number_input(
                "LATITUDE",
                min_value=-90.0,
                max_value=90.0,
                value=51.5074,
                step=0.0001,
                format="%.4f",
            )
        with c4:
            lon = st.number_input(
                "LONGITUDE",
                min_value=-180.0,
                max_value=180.0,
                value=-0.1278,
                step=0.0001,
                format="%.4f",
            )
        with c5:
            reliability = st.number_input(
                "RELIABILITY", min_value=0.0, max_value=1.0, value=0.7, step=0.01
            )
        submitted = st.form_submit_button("INJECT RECORD", width="stretch")

    if submitted:
        payload = {
            "timestamp": timestamp,
            "duration_s": float(duration),
            "entity": entity.strip().upper(),
            "lat": float(lat),
            "lon": float(lon),
            "source": source,
            "device_id": device.strip().upper(),
            "action": action_text.strip() or "UNKNOWN",
            "reliability": float(reliability),
        }
        try:
            result = client.add_event(payload)
        except ApiError as exc:
            st.error(str(exc))
        else:
            new_conflicts = result.get("new_conflicts") or []
            if new_conflicts:
                st.session_state["pending_conflict"] = new_conflicts[0]["id"]
                st.session_state["pending_entity"] = new_conflicts[0].get("entity") or entity.strip().upper()
            _flash(
                "RECORD INJECTED",
                "success",
                f'{len(new_conflicts)} new conflict(s) - '
                f'{fmt_ms(result.get("analysis_ms"))} - {result.get("mode")}',
            )
            st.rerun()


@st.dialog("INGEST EVIDENCE ARCHIVE", width="large")
def _upload_dialog(client: ApiClient) -> None:
    st.markdown(
        '<p class="dialog-lead">Accepted formats: JSONL, NDJSON, JSON and CSV. '
        "Rule and ground-truth rows are parsed alongside event records.</p>",
        unsafe_allow_html=True,
    )
    with st.form("dlg-upload-form", border=False):
        upload = st.file_uploader(
            "EVIDENCE ARCHIVE",
            type=["jsonl", "ndjson", "json", "csv"],
            accept_multiple_files=False,
        )
        append = st.checkbox("APPEND TO ACTIVE CASE", value=False)
        submitted = st.form_submit_button("INGEST ARCHIVE", width="stretch")

    if submitted:
        if upload is None:
            st.error("Select a JSONL, JSON, or CSV archive first.")
        else:
            try:
                with st.spinner("PARSING ARCHIVE // rebuilding index"):
                    result = client.upload(
                        upload.name, upload.getvalue(), append=append
                    )
            except ApiError as exc:
                st.error(str(exc))
            else:
                if not append:
                    st.session_state["pending_entity"] = ALL_SUBJECTS
                warnings = result.get("warnings") or []
                detail = (
                    f'{result.get("events", 0):,} records - '
                    f'{result.get("conflicts", 0):,} conflicts - '
                    f'{fmt_ms(result.get("analysis_ms"))}'
                )
                if warnings:
                    detail += " - warnings: " + "; ".join(str(w) for w in warnings[:2])
                _flash(
                    "ARCHIVE APPENDED" if append else "DATASET REPLACED",
                    "success" if not warnings else "warn",
                    detail,
                )
                st.rerun()


@st.dialog("LIVE PERFORMANCE PROBE", width="large")
def _bench_dialog(client: ApiClient) -> None:
    st.markdown(
        '<p class="dialog-lead">Generate a fresh synthetic case with planted truth, '
        "then time the complete detector and constraint-graph pipeline. Probe results "
        "are written under backend/results/runs/ and never replace the canonical run.</p>",
        unsafe_allow_html=True,
    )
    with st.form("dlg-bench-form", border=False):
        sizes = st.multiselect(
            "DATASET SCALES",
            options=list(BENCH_SIZES),
            default=[1_000, 10_000],
            format_func=lambda value: f"{value:,}",
        )
        c1, c2, c3 = st.columns(3, gap="small")
        with c1:
            contradictions = st.number_input(
                "CONTRADICTIONS", min_value=0, max_value=5000, value=8, step=1
            )
        with c2:
            seed = st.number_input("SEED", min_value=0, value=424242, step=1)
        with c3:
            include_naive = st.checkbox("NAIVE BASELINE", value=True)
        st.markdown(
            '<p class="warn-note">A 1M-event probe can take several minutes and roughly '
            "1.1 GB of traced memory.</p>",
            unsafe_allow_html=True,
        )
        submitted = st.form_submit_button("RUN LIVE PROBE", width="stretch")

    if submitted:
        if not sizes:
            st.error("Select at least one dataset scale.")
        else:
            try:
                with st.spinner("BENCHMARK RUNNING // generating, indexing, detecting"):
                    payload = client.bench(
                        sizes=[int(size) for size in sizes],
                        contradictions=int(contradictions),
                        seed=int(seed),
                        include_naive=bool(include_naive),
                        persist=False,
                    )
            except ApiError as exc:
                st.error(str(exc))
            else:
                summary = payload.get("summary") or {}
                st.session_state["bench_live"] = payload
                st.session_state["bench_probe"] = True
                _flash(
                    "BENCHMARK COMPLETE",
                    "success",
                    f'{summary.get("results_ok", 0)} scales - '
                    f'P {fmt_pct(summary.get("avg_precision"), 1)} / '
                    f'R {fmt_pct(summary.get("avg_recall"), 1)}',
                )
                st.rerun()


@st.dialog("BFS EVIDENCE INTERROGATION", width="large")
def _explain_dialog(
    client: ApiClient, conflict_id: str, selected: str | None, top_k: int
) -> None:
    try:
        explanation = client.explain(conflict_id)
    except ApiError as exc:
        explanation = {
            "conflict": {"id": conflict_id, "kind": "unknown", "detail": str(exc)},
            "chain": [],
            "narrative": str(exc),
            "nodes_visited": 0,
        }
    st.markdown(
        render.explain_body_html(explanation, selected=selected, top_k=top_k),
        unsafe_allow_html=True,
    )
    conflict = explanation.get("conflict") or {}
    if conflict.get("entity"):
        with st.form("dlg-locate-form", border=False):
            submitted = st.form_submit_button(
                f"LOCATE {conflict.get('entity')}", width="stretch"
            )
        if submitted:
            st.session_state["pending_entity"] = conflict["entity"]
            st.rerun()


@st.dialog("COVERAGE INTERROGATION", width="large")
def _gaps_dialog(client: ApiClient, threshold: float, selected: str | None) -> None:
    try:
        gaps = client.gaps(threshold_s=threshold, entity=selected, limit=120)
    except ApiError as exc:
        st.error(str(exc))
        return
    st.markdown(
        render.gaps_body_html(
            gaps, threshold=threshold, selected=selected, top_k=8
        ),
        unsafe_allow_html=True,
    )
    subjects = sorted({str(gap.get("entity")) for gap in gaps.get("gaps") or []})
    if subjects:
        with st.form("dlg-gap-locate-form", border=False):
            target = st.selectbox("LOCATE SUBJECT", subjects)
            submitted = st.form_submit_button("LOCATE SUBJECT", width="stretch")
        if submitted:
            st.session_state["pending_entity"] = target
            st.rerun()


@st.dialog("EXPORT LEDGER", width="medium")
def _export_dialog(client: ApiClient, case_id: str) -> None:
    st.markdown(
        '<p class="dialog-lead">The ledger contains every ranked conflict with detector '
        "provenance, source corroboration and exact evidence ids. JSON is intended for "
        "downstream tooling; CSV is a flat auditor table.</p>",
        unsafe_allow_html=True,
    )
    try:
        json_bytes = client.export_bytes("json")
        csv_bytes = client.export_bytes("csv")
    except ApiError as exc:
        st.error(str(exc))
        return
    safe_case = "".join(ch for ch in case_id if ch.isalnum() or ch in "-_") or "case"
    st.download_button(
        "DOWNLOAD JSON",
        data=json_bytes,
        file_name=f"chronoclash_{safe_case}.json",
        mime="application/json",
        width="stretch",
    )
    st.download_button(
        "DOWNLOAD CSV",
        data=csv_bytes,
        file_name=f"chronoclash_{safe_case}.csv",
        mime="text/csv",
        width="stretch",
    )


# --------------------------------------------------------------------------
# Boot
# --------------------------------------------------------------------------

_inject_css()
_apply_pending()
_defaults()
client = ApiClient.from_env()

try:
    state = client.state()
except ApiError as exc:
    st.markdown(render.boot_screen_html(str(exc)), unsafe_allow_html=True)
    if st.button("RETRY UPLINK", key="retry_uplink"):
        st.rerun()
    st.stop()


# --------------------------------------------------------------------------
# Resolve active filters before any data fetch
# --------------------------------------------------------------------------

entity_names = [str(item.get("name")) for item in state.get("entities") or []]
filter_options = [ALL_SUBJECTS, *entity_names]
if st.session_state.get("entity_filter") not in filter_options:
    st.session_state["entity_filter"] = ALL_SUBJECTS
entity_choice = st.session_state.get("entity_filter", ALL_SUBJECTS)
selected = None if entity_choice == ALL_SUBJECTS else str(entity_choice)

try:
    top_k = int(st.session_state.get("top_k_ctl") or 8)
except (TypeError, ValueError):
    top_k = 8
if top_k not in TOP_K_OPTIONS:
    top_k = 8
    st.session_state["top_k_ctl"] = 8

try:
    threshold = int(st.session_state.get("gap_threshold") or 900)
except (TypeError, ValueError):
    threshold = 900
if threshold not in GAP_THRESHOLDS:
    threshold = 900
    st.session_state["gap_threshold"] = 900

zoom = float(st.session_state.get("timeline_zoom") or 1.0)

try:
    conflict_payload = client.conflicts(top_k)
except ApiError:
    conflict_payload = {"conflicts": [], "total": state.get("conflicts_found", 0)}
conflicts = conflict_payload.get("conflicts") or []
conflict_ids = [str(item.get("id")) for item in conflicts]
if st.session_state.get("focused_conflict") not in conflict_ids:
    if conflict_ids:
        st.session_state["focused_conflict"] = conflict_ids[0]
    else:
        st.session_state.pop("focused_conflict", None)
focused_id = st.session_state.get("focused_conflict")
focused = next((item for item in conflicts if item.get("id") == focused_id), None)

try:
    timeline = client.timeline(entity=selected, limit=4000)
except ApiError:
    timeline = {"events": [], "total": 0, "truncated": False, "window": {}}
events = timeline.get("events") or []
flags = sum(len(event.get("conflicts") or []) for event in events)

history = st.session_state.setdefault("history", [])
analysis_ms = float(state.get("analysis_ms") or 0.0)
if not history or history[-1] != analysis_ms:
    history.append(analysis_ms)
    st.session_state["history"] = history[-24:]
history = st.session_state["history"]

bench = _bench(client)
bench_probe = bool(st.session_state.get("bench_probe"))


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------

st.markdown(
    render.topbar_html(
        state,
        online=True,
        selected_entity=selected,
        top_k=top_k,
    ),
    unsafe_allow_html=True,
)

left, centre, right = st.columns([0.72, 2.12, 1.0], gap="medium")


# --------------------------------------------------------------------------
# Left rail: subject filter, identity lattice, evidence posture
# --------------------------------------------------------------------------

with left:
    st.markdown('<div class="rail-control-label">SUBJECT FILTER</div>', unsafe_allow_html=True)
    st.selectbox(
        "SUBJECT FILTER",
        filter_options,
        key="entity_filter",
        label_visibility="collapsed",
    )
    st.markdown(render.entity_panel_html(state, selected), unsafe_allow_html=True)
    st.markdown(render.case_panel_html(state, history), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Centre: temporal field + operator console
# --------------------------------------------------------------------------

with centre:
    with st.container(key="hud-timeline-panel"):
        st.markdown(
            render.timeline_head_html(
                selected=selected,
                event_count=len(events),
                total=int(timeline.get("total") or 0),
                truncated=bool(timeline.get("truncated")),
                flags=flags,
                zoom=zoom,
                top_k=top_k,
            ),
            unsafe_allow_html=True,
        )
        zoom_cols = st.columns([0.55, 0.55, 0.95, 9], gap="small", wrap=False)
        with zoom_cols[0]:
            if st.button("+", key="zoom_in", width="content"):
                st.session_state["timeline_zoom"] = max(0.015, zoom / 1.35)
        with zoom_cols[1]:
            if st.button("-", key="zoom_out", width="content"):
                st.session_state["timeline_zoom"] = min(1.0, zoom * 1.35)
        with zoom_cols[2]:
            if st.button("FIT", key="zoom_fit", width="content"):
                st.session_state["timeline_zoom"] = 1.0
        st.plotly_chart(
            render.timeline_figure(
                events,
                state.get("entities") or [],
                selected,
                focused,
                st.session_state.get("timeline_zoom", 1.0),
            ),
            width="stretch",
            config={
                "displayModeBar": False,
                "displaylogo": False,
                "scrollZoom": True,
                "doubleClick": "reset",
                "responsive": True,
            },
            key="timeline-chart",
        )
        st.markdown(
            render.timeline_foot_html(timeline, events), unsafe_allow_html=True
        )

    with st.container(key="hud-actions"):
        st.markdown(render.action_header_html(state), unsafe_allow_html=True)
        act1 = st.columns(3, gap="small")
        with act1[0]:
            if st.button(
                "FULL RESCAN", key="act_scan", width="stretch", type="primary"
            ):
                _run_scan(client, "full")
        with act1[1]:
            if st.button("INCREMENTAL", key="act_incremental", width="stretch"):
                _run_scan(client, "incremental")
        with act1[2]:
            if st.button("GAP AUDIT", key="act_gaps", width="stretch"):
                _gaps_dialog(client, float(threshold), selected)

        act2 = st.columns(3, gap="small")
        with act2[0]:
            if st.button("APPEND RECORD", key="act_add", width="stretch"):
                _add_dialog(client, state, selected)
        with act2[1]:
            if st.button("INGEST FILE", key="act_upload", width="stretch"):
                _upload_dialog(client)
        with act2[2]:
            if st.button("BENCHMARK", key="act_bench", width="stretch"):
                _bench_dialog(client)

        st.markdown(render.action_telemetry_html(state), unsafe_allow_html=True)

        gap_col, export_col = st.columns([2.2, 1], gap="small")
        with gap_col:
            st.markdown(
                '<div class="rail-control-label">SILENCE THRESHOLD</div>',
                unsafe_allow_html=True,
            )
            st.segmented_control(
                "SILENCE THRESHOLD",
                options=list(GAP_THRESHOLDS),
                key="gap_threshold",
                format_func=lambda value: f"{value}s",
                label_visibility="collapsed",
            )
        with export_col:
            st.markdown('<div class="rail-control-label">&nbsp;</div>', unsafe_allow_html=True)
            if st.button("EXPORT LEDGER", key="act_export", width="stretch"):
                _export_dialog(client, str(state.get("case_id") or "case"))


# --------------------------------------------------------------------------
# Right rail: queue controls, anomaly queue, protocol
# --------------------------------------------------------------------------

with right:
    st.markdown('<div class="rail-control-label">TRACE CAPACITY</div>', unsafe_allow_html=True)
    st.segmented_control(
        "TRACE CAPACITY",
        options=list(TOP_K_OPTIONS),
        key="top_k_ctl",
        format_func=lambda value: f"{value}",
        label_visibility="collapsed",
    )
    st.markdown(
        render.alert_panel_html(
            conflicts,
            int(conflict_payload.get("total") or state.get("conflicts_found") or 0),
            top_k,
            focused_id,
            selected,
        ),
        unsafe_allow_html=True,
    )
    if conflicts:
        labels = {
            str(item.get("id")): (
                f'{index:02d} // {render.KIND_SHORT.get(str(item.get("kind")), "CFL")} // '
                f'{item.get("entity") or item.get("device_id") or "MULTI"}'
            )
            for index, item in enumerate(conflicts, start=1)
        }
        st.markdown('<div class="rail-control-label">TRACE TARGET</div>', unsafe_allow_html=True)
        st.selectbox(
            "TRACE TARGET",
            conflict_ids,
            key="focused_conflict",
            format_func=lambda value: labels.get(value, value),
            label_visibility="collapsed",
        )
        if st.button("OPEN TRACE", key="act_trace", width="stretch"):
            if focused_id:
                _explain_dialog(client, focused_id, selected, top_k)
    st.markdown(
        render.protocol_panel_html(
            state,
            conflicts[0] if conflicts else None,
            selected=selected,
            top_k=top_k,
        ),
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Benchmark deck
# --------------------------------------------------------------------------

with st.container(key="hud-benchmark-panel"):
    st.markdown(
        render.bench_header_and_summary(
            bench, probe=bench_probe, selected=selected, top_k=top_k
        ),
        unsafe_allow_html=True,
    )
    probe_cols = st.columns([6, 1.1, 1.1], gap="small")
    with probe_cols[1]:
        if st.button("LIVE PROBE", key="bench_live_btn", width="stretch"):
            _bench_dialog(client)
    with probe_cols[2]:
        if st.button("RESTORE", key="bench_restore_btn", width="stretch"):
            st.session_state["bench_live"] = None
            st.session_state["bench_probe"] = False
            st.rerun()
    chart_col, table_col = st.columns([1.35, 1.0], gap="medium")
    with chart_col:
        st.markdown(
            '<div class="bench-chart-head"><span>PIPELINE LATENCY / LOG SCALE</span>'
            "<span>MILLISECONDS</span></div>",
            unsafe_allow_html=True,
        )
        if bench and bench.get("results"):
            st.plotly_chart(
                render.bench_figure(bench),
                width="stretch",
                config={"displayModeBar": False, "displaylogo": False, "responsive": True},
                key="bench-chart",
            )
        else:
            st.markdown(
                '<div class="bench-empty"><span>&#8779;</span>'
                "<strong>NO BENCHMARK TELEMETRY</strong>"
                "<p>Run the CLI harness or launch a live probe from the operator console.</p></div>",
                unsafe_allow_html=True,
            )
    with table_col:
        st.markdown(render.bench_table_html(bench), unsafe_allow_html=True)
    st.markdown(render.bench_foot_html(bench), unsafe_allow_html=True)


st.markdown(render.footer_html(state, online=True), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Transient flash toast
# --------------------------------------------------------------------------

flash = st.session_state.pop("flash", None)
if flash:
    st.markdown(
        render.flash_html(
            flash.get("message", ""), flash.get("tone", "success"), flash.get("detail", "")
        ),
        unsafe_allow_html=True,
    )
