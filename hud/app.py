"""ChronoClash HUD - a Python-only Streamlit command terminal.

Run with:
    streamlit run hud/app.py

The FastAPI service must be running (see README).  Every algorithmic result is
read from that API; this file only renders and orchestrates interactions.
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
from hud.formatting import esc, fmt_ms, fmt_pct, url_for  # noqa: E402


ASSETS = Path(__file__).resolve().parent / "assets"
SOURCES = ("cctv", "call", "gps", "bank", "device", "witness")
BENCH_SIZES = (1_000, 10_000, 100_000, 1_000_000)
TOP_K_OPTIONS = (5, 8, 12, 20)


st.set_page_config(
    page_title="ChronoClash // Temporal Contradiction Terminal",
    page_icon="CC",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------
# Session and query helpers
# --------------------------------------------------------------------------

def _drop_query(*keys: str) -> None:
    for key in keys:
        if key in st.query_params:
            del st.query_params[key]


def _flash(message: str, tone: str = "success", detail: str = "") -> None:
    st.session_state["flash"] = {"message": message, "tone": tone, "detail": detail}


def _query_float(name: str, default: float) -> float:
    try:
        return float(st.query_params.get(name) or default)
    except (TypeError, ValueError):
        return default


def _bench(client: ApiClient) -> dict[str, Any] | None:
    live = st.session_state.get("bench_live")
    if live:
        return live
    try:
        payload = client.latest_bench()
        st.session_state["bench_live"] = None
        return payload
    except ApiError:
        return None


# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------

def _inject_css() -> None:
    css = (ASSETS / "hud.css").read_text(encoding="utf-8")
    fonts = (ASSETS / "fonts.css").read_text(encoding="utf-8")
    streamlit_css = (ASSETS / "streamlit.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{fonts}\n{css}\n{streamlit_css}</style>", unsafe_allow_html=True)


_inject_css()


# --------------------------------------------------------------------------
# Mutating actions arrive as query parameters, keeping the HUD fully linkable.
# --------------------------------------------------------------------------

client = ApiClient.from_env()
action = (st.query_params.get("action") or "").strip().lower()
if action:
    _drop_query("action")
    try:
        if action == "scan":
            with st.spinner("FULL RESCAN // rebuilding index and detector cascade"):
                result = client.analyze("full")
            _flash(
                "FULL SCAN COMPLETE",
                "success",
                f'{result.get("conflicts_found", 0)} conflicts - '
                f'{fmt_ms(result.get("analysis_ms"))} - '
                f'{result.get("events_per_sec", 0):,.0f} ev/s',
            )
        elif action == "incremental":
            with st.spinner("INCREMENTAL SWEEP // relaxing pending neighbourhoods"):
                result = client.analyze("incremental")
            _flash(
                "INCREMENTAL SWEEP COMPLETE",
                "success",
                f'{result.get("conflicts_found", 0)} conflicts - '
                f'{fmt_ms(result.get("analysis_ms"))} - {result.get("mode", "incremental")}',
            )
        elif action == "bench-refresh":
            payload = client.latest_bench()
            st.session_state["bench_live"] = None
            st.session_state["bench_probe"] = False
            _flash(
                "CANONICAL BENCHMARK RESTORED",
                "info",
                f'{len(payload.get("summary", {}).get("sizes", []))} scales loaded.',
            )
        else:
            _flash("UNKNOWN OPERATOR COMMAND", "warn", action)
    except ApiError as exc:
        _flash("ANALYSIS FAILED", "error", str(exc))
    st.rerun()


# Timeline zoom is a session preference, driven by the + / - / FIT links.
zoom = float(st.session_state.get("timeline_zoom", 1.0))
zoom_action = (st.query_params.get("zoom") or "").strip().lower()
if zoom_action:
    _drop_query("zoom")
    if zoom_action == "in":
        zoom = max(0.015, zoom / 1.35)
    elif zoom_action == "out":
        zoom = min(1.0, zoom * 1.35)
    else:
        zoom = 1.0
    st.session_state["timeline_zoom"] = zoom
    st.rerun()


# --------------------------------------------------------------------------
# Read the active case
# --------------------------------------------------------------------------

try:
    state = client.state()
except ApiError as exc:
    st.markdown(render.boot_screen_html(str(exc)), unsafe_allow_html=True)
    st.stop()

selected = (st.query_params.get("entity") or "").strip().upper() or None
try:
    top_k = int(st.query_params.get("top_k") or 8)
except (TypeError, ValueError):
    top_k = 8
if top_k not in TOP_K_OPTIONS:
    top_k = 8

try:
    conflict_payload = client.conflicts(top_k)
except ApiError:
    conflict_payload = {"conflicts": [], "total": state.get("conflicts_found", 0)}

try:
    timeline = client.timeline(entity=selected, limit=4000)
except ApiError:
    timeline = {"events": [], "total": 0, "truncated": False, "window": {}}

conflicts = conflict_payload.get("conflicts") or []
events = timeline.get("events") or []
focused_id = (st.query_params.get("conflict") or "").strip() or None
focused = next((item for item in conflicts if item.get("id") == focused_id), None)
if focused is None and conflicts:
    focused = conflicts[0]

history = st.session_state.setdefault("history", [])
analysis_ms = float(state.get("analysis_ms") or 0.0)
if not history or history[-1] != analysis_ms:
    history.append(analysis_ms)
    st.session_state["history"] = history[-24:]
history = st.session_state["history"]

bench = _bench(client)
bench_probe = bool(st.session_state.get("bench_probe"))

panel = (st.query_params.get("panel") or "").strip().lower()
threshold = _query_float("threshold", 900.0)
flags = sum(len(event.get("conflicts") or []) for event in events)


# --------------------------------------------------------------------------
# Top bar
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

st.markdown('<a id="hud-analysis"></a>', unsafe_allow_html=True)

left, centre, right = st.columns([0.78, 1.92, 1.02], gap="small")

with left:
    st.markdown(render.entity_panel_html(state, selected), unsafe_allow_html=True)
    st.markdown(render.case_panel_html(state, history), unsafe_allow_html=True)

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
        figure = render.timeline_figure(
            events,
            state.get("entities") or [],
            selected,
            focused,
            zoom,
        )
        st.plotly_chart(
            figure,
            use_container_width=True,
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
    st.markdown(
        render.action_panel_html(state, selected=selected, top_k=top_k),
        unsafe_allow_html=True,
    )

with right:
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

st.markdown('<a id="hud-benchmark"></a>', unsafe_allow_html=True)
with st.container(key="hud-benchmark-panel"):
    st.markdown(
        render.bench_header_and_summary(
            bench, probe=bench_probe, selected=selected, top_k=top_k
        ),
        unsafe_allow_html=True,
    )
    chart_col, table_col = st.columns([1.35, 1.0], gap="small")
    with chart_col:
        st.markdown(
            '<div class="bench-chart-head"><span>PIPELINE LATENCY / LOG SCALE</span>'
            "<span>MILLISECONDS</span></div>",
            unsafe_allow_html=True,
        )
        if bench and bench.get("results"):
            st.plotly_chart(
                render.bench_figure(bench),
                use_container_width=True,
                config={"displayModeBar": False, "displaylogo": False, "responsive": True},
                key="bench-chart",
            )
        else:
            st.markdown(
                '<div class="bench-empty"><span>&#8779;</span>'
                "<strong>NO BENCHMARK TELEMETRY</strong>"
                "<p>Run the CLI harness or launch a live probe from the action matrix.</p></div>",
                unsafe_allow_html=True,
            )
    with table_col:
        st.markdown(render.bench_table_html(bench), unsafe_allow_html=True)
    st.markdown(render.bench_foot_html(bench), unsafe_allow_html=True)


st.markdown(render.footer_html(state, online=True), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Explain and gap overlays (pure HTML links, no client-side state)
# --------------------------------------------------------------------------

if focused_id:
    try:
        explanation = client.explain(focused_id)
    except ApiError as exc:
        explanation = {
            "conflict": {"id": focused_id, "kind": "unknown", "detail": str(exc)},
            "chain": [],
            "narrative": str(exc),
            "nodes_visited": 0,
        }
    st.markdown(
        render.explain_overlay_html(explanation, selected=selected, top_k=top_k),
        unsafe_allow_html=True,
    )

if panel == "gaps":
    try:
        gaps = client.gaps(threshold_s=threshold, entity=selected, limit=120)
    except ApiError as exc:
        gaps = {"gaps": [], "returned": 0, "threshold_s": threshold, "entity": selected}
        st.session_state["flash"] = {
            "message": "GAP AUDIT FAILED",
            "tone": "error",
            "detail": str(exc),
        }
    st.markdown(
        render.gaps_overlay_html(
            gaps, threshold=threshold, selected=selected, top_k=top_k
        ),
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Operator form overlays
# --------------------------------------------------------------------------

def _modal_close_href() -> str:
    return url_for(entity=selected, top_k=top_k)


def _form_backdrop() -> None:
    st.markdown('<div class="hud-form-backdrop"></div>', unsafe_allow_html=True)


def _modal_header(index: str, eyebrow: str, title: str, meta: str) -> None:
    st.markdown(
        '<header class="modal-head"><div>'
        f'<span class="panel-eyebrow">{esc(eyebrow)} // {esc(index)}</span>'
        f"<h2>{esc(title)}</h2></div>"
        '<div class="modal-head-right">'
        f'<span class="modal-meta">{meta}</span>'
        f'<a class="modal-close" href="{_modal_close_href()}" aria-label="Close">X</a>'
        "</div></header>",
        unsafe_allow_html=True,
    )


def _render_add_panel() -> None:
    _form_backdrop()
    with st.container(key="hud-modal-add"):
        _modal_header(
            "A1",
            "RECORD INJECTION",
            "APPEND EVIDENCE",
            esc(state.get("case_id") or ""),
        )
        default_ts = (state.get("window") or {}).get("end") or datetime.now(
            timezone.utc
        ).isoformat()
        default_ts = str(default_ts).replace(".000", "")
        with st.form("add-event-form", border=False):
            st.markdown('<div class="form-section-title">EVIDENCE RECORD</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2, gap="small")
            with c1:
                timestamp = st.text_input("TIMESTAMP (ISO-8601)", value=default_ts)
                entity = st.text_input("SUBJECT", value=selected or "SUBJ-INC-01")
                source = st.selectbox("SOURCE", SOURCES, index=0)
            with c2:
                device = st.text_input("DEVICE ID", value="DEV-INC-001")
                action_text = st.text_input("ACTION", value="MANUAL_OBSERVATION")
                duration = st.number_input("DURATION (SECONDS)", min_value=0.0, value=0.0, step=30.0)
            c3, c4, c5 = st.columns(3, gap="small")
            with c3:
                lat = st.number_input("LATITUDE", min_value=-90.0, max_value=90.0, value=51.5074, step=0.0001, format="%.4f")
            with c4:
                lon = st.number_input("LONGITUDE", min_value=-180.0, max_value=180.0, value=-0.1278, step=0.0001, format="%.4f")
            with c5:
                reliability = st.number_input("RELIABILITY", min_value=0.0, max_value=1.0, value=0.7, step=0.01)
            st.markdown(
                '<p class="form-hint">The event is normalized, inserted into the AVL interval forest, '
                "and only its local neighbourhood is rechecked. Existing conflicts remain untouched until "
                "a full rescan.</p>",
                unsafe_allow_html=True,
            )
            submitted = st.form_submit_button("INJECT RECORD", use_container_width=True)
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
                    _drop_query("panel")
                    _flash(
                        "RECORD INJECTED",
                        "success",
                        f'{len(result.get("new_conflicts") or [])} new conflict(s) - '
                        f'{fmt_ms(result.get("analysis_ms"))} - {result.get("mode")}',
                    )
                    new_conflicts = result.get("new_conflicts") or []
                    if new_conflicts:
                        st.query_params["conflict"] = new_conflicts[0]["id"]
                    st.rerun()


def _render_upload_panel() -> None:
    _form_backdrop()
    with st.container(key="hud-modal-upload"):
        _modal_header(
            "A2",
            "ARCHIVE INGESTION",
            "INGEST DATASET",
            "JSONL / CSV / JSON",
        )
        st.markdown(
            '<div class="schema-note"><div><span>ACCEPTED SCHEMA</span>'
            "<p>timestamp, entity, source, lat, lon, device_id, action, reliability</p></div>"
            '<div><span>OPTIONAL RECORDS</span><p>record_type=rule and record_type=ground_truth '
            "rows are parsed alongside events.</p></div></div>",
            unsafe_allow_html=True,
        )
        with st.form("upload-form", border=False):
            upload = st.file_uploader(
                "EVIDENCE ARCHIVE",
                type=["jsonl", "ndjson", "json", "csv"],
                accept_multiple_files=False,
            )
            append = st.checkbox("APPEND TO ACTIVE CASE", value=False)
            st.markdown(
                '<p class="form-hint">Replace mode rebuilds the case and clears the active subject '
                "filter. Append mode merges the uploaded records into the current evidence set.</p>",
                unsafe_allow_html=True,
            )
            submitted = st.form_submit_button("INGEST ARCHIVE", use_container_width=True)
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
                            _drop_query("entity")
                        _drop_query("panel")
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


def _render_bench_panel() -> None:
    _form_backdrop()
    with st.container(key="hud-modal-bench"):
        _modal_header(
            "A3",
            "LIVE PERFORMANCE PROBE",
            "BENCHMARK MATRIX",
            "PERF_COUNTER / TRACEMALLOC",
        )
        with st.form("bench-form", border=False):
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
                '<p class="warn-note">A 1M-event probe can take several minutes and roughly 1.1 GB '
                "of traced memory. Results are written under backend/results/runs/ and never replace "
                "the canonical benchmark.</p>",
                unsafe_allow_html=True,
            )
            submitted = st.form_submit_button("RUN LIVE PROBE", use_container_width=True)
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
                        st.session_state["bench_live"] = payload
                        st.session_state["bench_probe"] = True
                        _drop_query("panel")
                        summary = payload.get("summary") or {}
                        _flash(
                            "BENCHMARK COMPLETE",
                            "success",
                            f'{summary.get("results_ok", 0)} scales - '
                            f'P {fmt_pct(summary.get("avg_precision"), 1)} / '
                            f'R {fmt_pct(summary.get("avg_recall"), 1)}',
                        )
                        st.rerun()


def _render_export_panel() -> None:
    _form_backdrop()
    with st.container(key="hud-modal-export"):
        _modal_header("A4", "CHAIN OF CUSTODY", "EXPORT LEDGER", "CONFLICT PROVENANCE")
        st.markdown(
            '<div class="modal-body"><p class="explain-narrative">The export contains every ranked '
            "conflict with detector provenance, source corroboration, and the exact evidence ids. "
            "Use JSON for downstream tooling and CSV for a spreadsheet review.</p>"
            '<div class="mode-cards">'
            f'<a class="mode-card" href="{client.export_url("json")}" target="_blank">'
            "<strong>EXPORT JSON</strong><span>Structured ledger with stats and metadata.</span></a>"
            f'<a class="mode-card" href="{client.export_url("csv")}" target="_blank">'
            "<strong>EXPORT CSV</strong><span>Flat conflict table for auditors.</span></a>"
            "</div></div>",
            unsafe_allow_html=True,
        )


if panel == "add":
    _render_add_panel()
elif panel == "upload":
    _render_upload_panel()
elif panel == "bench":
    _render_bench_panel()
elif panel == "export":
    _render_export_panel()


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
