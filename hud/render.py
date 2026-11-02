"""Server-rendered HUD markup and Plotly figures for the Streamlit terminal.

Everything in this module is presentation only.  It consumes the JSON returned
by the FastAPI engine and produces HTML/SVG/Plotly structures; no contradiction
is ever computed in the UI layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, Iterable

import plotly.graph_objects as go

from .formatting import (
    KIND_LABEL,
    KIND_SHORT,
    SOURCE_COLORS,
    SOURCE_LABEL,
    SOURCE_ORDER,
    STATUS_LABEL,
    STATUS_SHORT,
    esc,
    fmt_compact,
    fmt_clock,
    fmt_datetime,
    fmt_duration,
    fmt_int,
    fmt_ms,
    fmt_pct,
    fmt_span,
    fmt_utc,
    severity_class,
    sparkline_svg,
)


# --------------------------------------------------------------------------
# Small HTML primitives
# --------------------------------------------------------------------------

def panel_head(
    index: str,
    eyebrow: str,
    title: str,
    meta: str = "",
    actions: str = "",
) -> str:
    meta_html = f'<span class="panel-meta">{meta}</span>' if meta else ""
    return (
        '<header class="panel-head">'
        '<div class="panel-heading">'
        f'<span class="panel-index">{esc(index)}</span>'
        "<div>"
        f'<span class="panel-eyebrow">{esc(eyebrow)}</span>'
        f"<h2>{esc(title)}</h2>"
        "</div></div>"
        f'<div class="panel-head-right">{meta_html}{actions}</div>'
        "</header>"
    )


def panel_open(index: str, eyebrow: str, title: str, meta: str = "", actions: str = "", cls: str = "") -> str:
    return f'<section class="panel {cls}">{panel_head(index, eyebrow, title, meta, actions)}'



def _source_legend() -> str:
    items = "".join(
        f'<span><i style="background:{SOURCE_COLORS[source]}"></i>{SOURCE_LABEL[source]}</span>'
        for source in SOURCE_ORDER
    )
    return (
        '<div class="source-legend">'
        f"{items}"
        '<span class="legend-conflict"><i></i>CONTRADICTION</span>'
        "</div>"
    )


def _status_dot(status: str) -> str:
    return f'<span class="status-dot {esc(status)}"></span>'


# --------------------------------------------------------------------------
# Top bar and KPI strip
# --------------------------------------------------------------------------

def topbar_html(
    state: dict[str, Any],
    *,
    online: bool,
    selected_entity: str | None,
    top_k: int,
) -> str:
    now = datetime.now(timezone.utc)
    conflicts = int(state.get("conflicts_found") or 0)
    mode = str(state.get("mode") or "standby").upper()
    case_id = state.get("case_id") or "CC-UNKNOWN"
    specimen = selected_entity or "MULTI-ENTITY FIELD"
    return (
        '<div class="cc-scanlines" aria-hidden="true"></div>'
        '<div class="cc-vignette" aria-hidden="true"></div>'
        '<div class="cc-topbar">'
        '<div class="cc-topbar-row">'
        '<div class="cc-brand">'
        '<div class="brand-sigil" aria-hidden="true"><span>C</span><span>C</span><i></i></div>'
        '<div class="brand-copy">'
        '<span class="eyebrow">FORENSIC TEMPORAL DIVISION // UNIT 07</span>'
        '<h1>CHRONO<span>CLASH</span></h1>'
        '<p>TEMPORAL CONTRADICTION ANALYSIS TERMINAL</p>'
        "</div></div>"
        '<div class="cc-object">'
        '<span class="cc-micro">OBJECT IDENTIFICATION // 01</span>'
        f'<strong>{esc(specimen)}</strong>'
        f'<em>{fmt_int(state.get("entity_count"))} SUBJECTS / {fmt_int(state.get("event_count"))} RECORDS</em>'
        "</div>"
        '<div class="cc-facility">'
        f'<span class="cc-micro">CASE {esc(case_id)}</span>'
        f'<span>{now:%Y-%m-%d} // <b>{now:%H:%M:%S} UTC</b></span>'
        f'<span class="facility-state {"alarm" if conflicts else ""}">'
        f'{"CONTAINMENT REQUIRED" if conflicts else "FIELD NOMINAL"}</span>'
        "</div></div>"
        '<div class="cc-telemetry">'
        f'<span class="telemetry-row"><span class="status-dot {"online" if online else "offline"}"></span>'
        f'UPLINK <strong>{"STABLE" if online else "LINK DOWN"}</strong>'
        f'<span class="telemetry-sep">/</span> MODE <strong>{esc(mode)}</strong>'
        f'<span class="telemetry-sep">/</span> ENGINE <strong>{"ONLINE" if online else "RETRY"}</strong></span>'
        f'<span class="telemetry-row small">RANK CAPACITY {top_k} '
        f'<span class="telemetry-sep">/</span> TRACE TARGET '
        f'<strong>{esc(selected_entity or "AUTO")}</strong></span>'
        '<span class="case-line"><span class="case-tag">SIGNAL</span>'
        f'<strong>{"CONFLICT" if conflicts else "CLEAN"}</strong></span>'
        "</div></div>"
        '<div class="cc-kpis">'
        f'<div class="kpi"><span class="kpi-label">RECORDS</span><strong class="kpi-value">{fmt_int(state.get("event_count"))}</strong>'
        f'<span class="kpi-sub">{len(state.get("source_counts") or [])} SOURCES</span></div>'
        f'<div class="kpi"><span class="kpi-label">SUBJECTS</span><strong class="kpi-value">{fmt_int(state.get("entity_count"))}</strong>'
        f'<span class="kpi-sub">{int((state.get("entity_status") or {}).get("conflicted", 0))} CONFLICTED</span></div>'
        f'<div class="kpi {"alert" if conflicts else "nominal"}"><span class="kpi-label">CONFLICTS</span>'
        f'<strong class="kpi-value">{fmt_int(conflicts)}</strong>'
        f'<span class="kpi-sub">{fmt_int(state.get("critical_conflicts"))} CRITICAL</span></div>'
        f'<div class="kpi"><span class="kpi-label">FIDELITY</span>'
        f'<strong class="kpi-value">{fmt_pct((state.get("evaluation") or {}).get("f1"), 1) if state.get("evaluation") else "N/A"}</strong>'
        f'<span class="kpi-sub">{_fidelity_sub(state)}</span></div>'
        f'<div class="kpi"><span class="kpi-label">SCAN LATENCY</span>'
        f'<strong class="kpi-value">{fmt_ms(state.get("analysis_ms"))}</strong>'
        f'<span class="kpi-sub">{fmt_int(state.get("events_per_sec"))} EV/S</span></div>'
        "</div>"
    )


def _fidelity_sub(state: dict[str, Any]) -> str:
    evaluation = state.get("evaluation")
    if not evaluation:
        return "NO GROUND TRUTH"
    return (
        f'P {fmt_pct(evaluation.get("precision"))} / R {fmt_pct(evaluation.get("recall"))}'
    )


# --------------------------------------------------------------------------
# Left column: subject matrix + dossier
# --------------------------------------------------------------------------

def entity_panel_html(state: dict[str, Any], selected: str | None) -> str:
    entities = state.get("entities") or []
    counts = state.get("entity_status") or {}
    keep_top = 0
    tiles: list[str] = []
    for entity in entities:
        name = str(entity.get("name"))
        status = str(entity.get("status") or "clean")
        is_selected = selected == name
        severity = float(entity.get("max_severity") or 0.0)
        title = (
            f'{name} - latest: {entity.get("latest_action")} '
            f'({str(entity.get("latest_source") or "").upper()})'
        )
        tiles.append(
            f'<div class="entity-tile status-{esc(status)} {"selected" if is_selected else ""}" '
            f'title="{esc(title)}" aria-pressed="{"true" if is_selected else "false"}">'
            '<div class="entity-tile-top">'
            f'{_status_dot(status)}<strong>{esc(name)}</strong>'
            f'<span class="entity-status">{esc(STATUS_SHORT.get(status, status))}</span>'
            "</div>"
            '<div class="entity-tile-metrics">'
            f'<span><b>{fmt_int(entity.get("event_count"))}</b> REC</span>'
            f'<span class="{"hot" if entity.get("conflict_count") else ""}">'
            f'<b>{fmt_int(entity.get("conflict_count"))}</b> CFL</span>'
            "</div>"
            '<span class="severity-track slim">'
            f'<span class="severity-fill {severity_class(severity)}" style="width:{max(2, severity * 100):.1f}%"></span>'
            "</span></div>"
        )
    reset = (
        f'<div class="entity-reset {"active" if selected else ""}">'
        f'{"FILTER LOCKED // " + esc(selected) if selected else "SHOWING ALL SUBJECTS"}</div>'
    )
    body = (
        '<div class="status-strip">'
        f'<span class="status-chip clean"><i></i> VERIFIED <b>{fmt_int(counts.get("clean"))}</b></span>'
        f'<span class="status-chip suspect"><i></i> SUSPECT <b>{fmt_int(counts.get("suspect"))}</b></span>'
        f'<span class="status-chip conflicted"><i></i> CONFLICTED <b>{fmt_int(counts.get("conflicted"))}</b></span>'
        "</div>"
        '<div class="entity-scroll"><div class="entity-grid">'
        + ("".join(tiles) if tiles else '<p class="empty-note">NO SUBJECTS IN THE ACTIVE INDEX.</p>')
        + "</div></div>"
        + reset
    )
    head = panel_head(
        "01",
        "IDENTITY LATTICE",
        "SUBJECT MATRIX",
        f"{fmt_int(len(entities))} TRACKED",
    )
    return f'<section class="panel entity-panel">{head}<div class="panel-body entity-panel-body">{body}</div></section>'


def case_panel_html(state: dict[str, Any], history: list[float]) -> str:
    evaluation = state.get("evaluation")
    sources = state.get("source_counts") or []
    dataset = str(state.get("dataset") or "NO DATASET")
    if dataset.upper().startswith("SYNTHETIC-CASE-"):
        dataset = dataset.replace("SYNTHETIC-CASE-", "CASE-", 1)
    rows = [
        ("WINDOW", fmt_span((state.get("window") or {}).get("start"), (state.get("window") or {}).get("end")), False),
        ("RULES", fmt_int(state.get("rule_count")), False),
        ("PLANTED", fmt_int(state.get("ground_truth_count")), False),
        ("SCAN", fmt_ms(state.get("analysis_ms")), True),
        ("THROUGHPUT", f'{fmt_int(state.get("events_per_sec"))} ev/s', False),
        ("RSS", f'{float(state.get("memory_mb") or 0):.1f} MB', False),
    ]
    dossier = "".join(
        f'<div class="dossier-row"><span>{label}</span><strong class="{"accent" if accent else ""}">{value}</strong></div>'
        for label, value, accent in rows
    )
    source_rows = "".join(
        '<div class="source-row">'
        f'<span class="source-swatch" style="background:{SOURCE_COLORS.get(source.get("name"), "#fff")}"></span>'
        f'<span class="source-name">{esc(SOURCE_LABEL.get(source.get("name"), source.get("name")))}</span>'
        '<span class="source-meter">'
        f'<span style="width:{max(1, float(source.get("share") or 0) * 100):.1f}%;'
        f'background:{SOURCE_COLORS.get(source.get("name"), "#fff")}"></span></span>'
        f'<span class="source-count">{fmt_int(source.get("count"))}</span>'
        f'<span class="source-rel">{fmt_pct(source.get("reliability"))}</span>'
        "</div>"
        for source in sources
    )
    if evaluation:
        eval_html = (
            '<div class="eval-values">'
            f'<div><span>PRECISION</span><strong>{fmt_pct(evaluation.get("precision"), 1)}</strong></div>'
            f'<div><span>RECALL</span><strong>{fmt_pct(evaluation.get("recall"), 1)}</strong></div>'
            f'<div><span>F1</span><strong>{fmt_pct(evaluation.get("f1"), 1)}</strong></div>'
            "</div>"
            f'<div class="eval-note">TP {fmt_int(evaluation.get("tp"))} / FP {fmt_int(evaluation.get("fp"))} / '
            f'FN {fmt_int(evaluation.get("fn"))}</div>'
        )
    else:
        eval_html = '<p class="empty-note">UPLOAD WITH GROUND TRUTH TO SCORE PRECISION / RECALL.</p>'
    body = (
        f'<div class="dossier-grid">{dossier}</div>'
        '<div class="source-block"><div class="subhead"><span>SOURCE COMPOSITION</span>'
        "<span>RELIABILITY</span></div>"
        f"{source_rows}</div>"
        '<div class="eval-block"><div class="subhead"><span>DETECTION FIDELITY</span>'
        f'<span>{"GROUND TRUTH" if evaluation else "UNSCORED"}</span></div>{eval_html}</div>'
        '<div class="scan-history"><div><span>SCAN TELEMETRY</span>'
        f"<strong>{len(history)} RUNS</strong></div>"
        f'{sparkline_svg(history or [0, 0], 168, 32)}</div>'
        '<div class="dossier-foot">'
        f'OBSERVATION {fmt_utc((state.get("window") or {}).get("start"))} -> '
        f'{fmt_utc((state.get("window") or {}).get("end"))} // '
        f'{fmt_span((state.get("window") or {}).get("start"), (state.get("window") or {}).get("end"))}'
        "</div>"
    )
    head = panel_head("02", "CASE DOSSIER", "EVIDENCE POSTURE", dataset)
    return f'<section class="panel case-panel">{head}<div class="panel-body">{body}</div></section>'


# --------------------------------------------------------------------------
# Centre column: timeline header/footer + Plotly figure
# --------------------------------------------------------------------------

def timeline_head_html(
    *,
    selected: str | None,
    event_count: int,
    total: int,
    truncated: bool,
    flags: int,
    zoom: float,
    top_k: int,
) -> str:
    title = f"LANE // {selected}" if selected else "MASTER TIMELINE"
    meta = f"{fmt_int(event_count)} / {fmt_int(total)} REC"
    head = panel_head("03", "TEMPORAL FIELD", title, meta)
    specimen = (
        '<div class="specimen-strip">'
        '<div class="specimen-id"><span>SPECIMEN UNDER OBSERVATION</span>'
        f'<strong>{esc(selected or "MULTI-ENTITY FIELD")}</strong>'
        f'<em>{fmt_int(event_count)} RECORDS IN VIEW / {fmt_int(total)} INDEXED</em></div>'
        '<div class="specimen-count"><span>ANOMALY FLAGS</span>'
        f'<strong>+{fmt_int(flags)}</strong>'
        f'<em>{"PARTIAL WINDOW" if truncated else "FULL WINDOW"}</em></div>'
        "</div>"
    )
    badges = (
        ('<span class="warn-badge">TRUNCATED</span>' if truncated else "")
        + f'<span class="warn-badge hot">{fmt_int(flags)} FLAGS</span>'
        + '<span class="utc-badge">UTC</span>'
    )
    toolbar = (
        '<div class="timeline-toolbar">'
        f"{_source_legend()}"
        f'<div class="timeline-badges">{badges}</div>'
        "</div>"
    )
    return f"{head}{specimen}{toolbar}"


def timeline_foot_html(timeline: dict[str, Any], events: list[dict[str, Any]]) -> str:
    window = timeline.get("window") or {}
    start = window.get("start")
    end = window.get("end")
    span = 0.0
    if events:
        span = float(events[-1].get("end_ts") or events[-1].get("ts") or 0) - float(events[0].get("ts") or 0)
    coverage = 0 if not timeline.get("total") else round(len(events) / int(timeline["total"]) * 100)
    short = f"{span / 86400:.1f} DAY" if span >= 86_400 else f"{span / 3600:.1f} HR" if span >= 3600 else f"{span / 60:.0f} MIN"
    return (
        '<div class="timeline-foot">'
        '<div class="window-readout"><span>WINDOW <b>'
        f"{fmt_utc(start)}</b></span><span class=\"window-arrow\">-&gt;</span><span><b>{fmt_utc(end)}</b></span>"
        f'<span class="window-span">{esc(short)}</span></div>'
        '<div class="timeline-hint">SCROLL TO ZOOM - DRAG TO PAN - SELECT ALERT TO TRACE</div>'
        f'<div class="timeline-foot-stat"><span>OBSERVED {esc(short)}</span><span>{coverage}% COVERAGE</span></div>'
        "</div>"
    )


def _hex_rgba(color: str, alpha: float) -> str:
    color = color.lstrip("#")
    if len(color) != 6:
        return f"rgba(255,255,255,{alpha})"
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def build_lanes(
    events: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    selected: str | None,
) -> list[dict[str, Any]]:
    rank = {"conflicted": 0, "suspect": 1, "clean": 2}
    summary = {entity.get("name"): entity for entity in entities}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("entity")), []).append(event)
    rows: list[dict[str, Any]] = []
    for entity, items in grouped.items():
        meta = summary.get(entity, {})
        rows.append(
            {
                "entity": entity,
                "events": sorted(items, key=lambda item: (float(item.get("ts") or 0), str(item.get("id")))),
                "conflict_count": int(meta.get("conflict_count") or sum(bool(item.get("conflicts")) for item in items)),
                "status": str(meta.get("status") or "clean"),
                "aggregate": False,
            }
        )
    rows.sort(
        key=lambda row: (
            rank.get(row["status"], 3),
            -row["conflict_count"],
            -len(row["events"]),
            row["entity"],
        )
    )
    if selected:
        return [row for row in rows if row["entity"] == selected.upper()]
    if len(rows) > 16:
        visible, rest = rows[:15], rows[15:]
        rest_events = [event for row in rest for event in row["events"]]
        rest_events.sort(key=lambda item: (float(item.get("ts") or 0), str(item.get("id"))))
        status = "conflicted" if any(row["status"] == "conflicted" for row in rest) else (
            "suspect" if any(row["status"] == "suspect" for row in rest) else "clean"
        )
        visible.append(
            {
                "entity": f"OTHER SUBJECTS ({len(rest)})",
                "events": rest_events,
                "conflict_count": sum(row["conflict_count"] for row in rest),
                "status": status,
                "aggregate": True,
            }
        )
        rows = visible
    return rows


def timeline_figure(
    events: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    selected: str | None,
    focused: dict[str, Any] | None,
    zoom: float = 1.0,
) -> go.Figure:
    lanes = build_lanes(events, entities, selected)
    lane_index = {row["entity"]: index for index, row in enumerate(lanes)}
    fig = go.Figure()
    if not lanes:
        fig.update_layout(
            height=260,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis={"visible": False},
            yaxis={"visible": False},
            annotations=[
                {
                    "text": "NO EVIDENCE IN THIS WINDOW",
                    "showarrow": False,
                    "font": {"family": "Rajdhani, sans-serif", "size": 12, "color": "#9b8a73"},
                }
            ],
            margin={"l": 10, "r": 10, "t": 10, "b": 10},
        )
        return fig

    # Duration bars first so markers render above them.
    shapes: list[dict[str, Any]] = []
    for row in lanes:
        y = lane_index[row["entity"]]
        for event in row["events"]:
            duration = float(event.get("duration_s") or 0)
            if duration <= 0:
                continue
            shapes.append(
                {
                    "type": "line",
                    "xref": "x",
                    "yref": "y",
                    "x0": float(event.get("ts") or 0) * 1000,
                    "x1": float(event.get("end_ts") or event.get("ts") or 0) * 1000,
                    "y0": y,
                    "y1": y,
                    "line": {
                        "color": _hex_rgba(SOURCE_COLORS.get(str(event.get("source")), "#ffffff"), 0.30),
                        "width": 3,
                    },
                    "layer": "below",
                }
            )

    # One trace per source keeps the native legend and hover semantics cheap.
    for source in SOURCE_ORDER:
        xs, ys, custom, hover = [], [], [], []
        for row in lanes:
            y = lane_index[row["entity"]]
            for event in row["events"]:
                if event.get("source") != source or event.get("conflicts"):
                    continue
                xs.append(float(event.get("ts") or 0) * 1000)
                ys.append(y)
                custom.append(
                    [
                        event.get("id"),
                        row["entity"],
                        event.get("action"),
                        SOURCE_LABEL.get(source, source),
                        event.get("timestamp"),
                        event.get("device_id"),
                    ]
                )
                hover.append(
                    f"<b>{esc(event.get('action'))}</b><br>{esc(row['entity'])} - {SOURCE_LABEL.get(source, source)}"
                    f"<br>{esc(fmt_datetime(event.get('timestamp')))}"
                )
        if not xs:
            continue
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers",
                name=SOURCE_LABEL.get(source, source),
                marker={
                    "color": SOURCE_COLORS[source],
                    "size": 5.5,
                    "symbol": "circle",
                    "opacity": 0.82,
                    "line": {"width": 0},
                },
                customdata=custom,
                hovertemplate=(
                    "<b>%{customdata[0]}</b> - %{customdata[3]}<br>"
                    "%{customdata[1]} - %{customdata[2]}<br>"
                    "%{customdata[4]}<br>%{customdata[5]}<extra></extra>"
                ),
                showlegend=False,
            )
        )

    conflict_x, conflict_y, conflict_custom = [], [], []
    for row in lanes:
        y = lane_index[row["entity"]]
        for event in row["events"]:
            if not event.get("conflicts"):
                continue
            conflict_x.append(float(event.get("ts") or 0) * 1000)
            conflict_y.append(y)
            conflict_custom.append(
                [
                    event.get("id"),
                    row["entity"],
                    event.get("action"),
                    SOURCE_LABEL.get(str(event.get("source")), str(event.get("source"))),
                    event.get("timestamp"),
                    len(event.get("conflicts") or []),
                ]
            )
    if conflict_x:
        fig.add_trace(
            go.Scatter(
                x=conflict_x,
                y=conflict_y,
                mode="markers",
                name="CONTRADICTION",
                marker={
                    "color": "#e0563f",
                    "size": 9,
                    "symbol": "diamond",
                    "opacity": 0.95,
                    "line": {"color": "#f0a08a", "width": 0.7},
                },
                customdata=conflict_custom,
                hovertemplate=(
                    "<b>%{customdata[0]}</b> - CONFLICT LINK<br>"
                    "%{customdata[1]} - %{customdata[2]}<br>"
                    "%{customdata[4]}<br>%{customdata[5]} conflict reference(s)<extra></extra>"
                ),
                showlegend=False,
            )
        )

    event_lookup = {
        str(event.get("id")): (float(event.get("ts") or 0) * 1000, lane_index.get(str(event.get("entity"))))
        for row in lanes
        for event in row["events"]
    }
    if focused:
        points = [
            event_lookup[event_id]
            for event_id in focused.get("event_ids") or []
            if event_id in event_lookup and event_lookup[event_id][1] is not None
        ]
        for left, right in zip(points, points[1:]):
            shapes.append(
                {
                    "type": "line",
                    "xref": "x",
                    "yref": "y",
                    "x0": left[0],
                    "x1": right[0],
                    "y0": left[1],
                    "y1": right[1],
                    "line": {"color": "rgba(224,86,63,0.85)", "width": 1.2, "dash": "dot"},
                    "layer": "above",
                }
            )
        if points:
            fig.add_trace(
                go.Scatter(
                    x=[point[0] for point in points],
                    y=[point[1] for point in points],
                    mode="markers",
                    marker={
                        "color": "rgba(0,0,0,0)",
                        "size": 18,
                        "line": {"color": "rgba(232,220,200,0.9)", "width": 1.3},
                    },
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    # Bounds and zoom window.
    all_ts = [float(event.get("ts") or 0) for row in lanes for event in row["events"]]
    all_end = [float(event.get("end_ts") or event.get("ts") or 0) for row in lanes for event in row["events"]]
    low, high = min(all_ts), max(all_end)
    pad = max(30.0, (high - low) * 0.015)
    low, high = (low - pad) * 1000, (high + pad) * 1000
    span = max(1.0, high - low)
    zoom = max(0.015, min(1.0, float(zoom)))
    center = (low + high) / 2
    x0, x1 = center - span * zoom / 2, center + span * zoom / 2
    axis_format = "%H:%M" if span <= 129_600_000 else "%m-%d %H:%M"

    # Focused callout annotation.
    annotations: list[dict[str, Any]] = []
    if focused and points:
        last_x, last_y = points[-1]
        annotations.append(
            {
                "x": last_x,
                "y": last_y,
                "xref": "x",
                "yref": "y",
                "text": f"<b>{esc(KIND_SHORT.get(str(focused.get('kind')), str(focused.get('kind'))))} "
                f"{fmt_pct(focused.get('severity'))}</b>",
                "showarrow": True,
                "arrowhead": 0,
                "arrowwidth": 1,
                "arrowcolor": "rgba(224,86,63,0.8)",
                "ax": 34,
                "ay": -34,
                "bgcolor": "rgba(24,10,7,0.95)",
                "bordercolor": "rgba(224,86,63,0.65)",
                "borderwidth": 1,
                "borderpad": 4,
                "font": {"family": "JetBrains Mono, monospace", "size": 9, "color": "#f0a08a"},
            }
        )

    height = max(250, 38 + len(lanes) * 31 + 22)
    fig.update_layout(
        height=height,
        margin={"l": 138, "r": 16, "t": 30, "b": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="closest",
        dragmode="pan",
        showlegend=False,
        shapes=shapes,
        annotations=annotations,
        font={"family": "JetBrains Mono, monospace", "color": "#a99a84", "size": 10},
        xaxis={
            "type": "date",
            "range": [x0, x1],
            "tickformat": axis_format,
            "tickfont": {"size": 9, "color": "rgba(232,220,200,0.55)"},
            "gridcolor": "rgba(224,162,104,0.08)",
            "linecolor": "rgba(224,162,104,0.24)",
            "zeroline": False,
            "showspikes": True,
            "spikecolor": "rgba(224,162,104,0.5)",
            "spikethickness": 1,
        },
        yaxis={
            "tickmode": "array",
            "tickvals": list(range(len(lanes))),
            "ticktext": [row["entity"] for row in lanes],
            "autorange": "reversed",
            "tickfont": {"family": "Rajdhani, sans-serif", "size": 11, "color": "rgba(232,220,200,0.78)"},
            "gridcolor": "rgba(224,162,104,0.06)",
            "linecolor": "rgba(224,162,104,0.16)",
            "zeroline": False,
            "showticklabels": True,
        },
        hoverlabel={
            "bgcolor": "#0b0805",
            "bordercolor": "rgba(224,162,104,0.5)",
            "font": {"family": "JetBrains Mono, monospace", "size": 10, "color": "#e8ddc9"},
        },
    )
    return fig


# --------------------------------------------------------------------------
# Right column: alert queue + protocol
# --------------------------------------------------------------------------

def alert_panel_html(
    conflicts: list[dict[str, Any]],
    total: int,
    top_k: int,
    focused_id: str | None,
    selected: str | None,
) -> str:
    head = panel_head(
        "04",
        "CONFLICT LEDGER",
        "ANOMALY QUEUE",
        f"{len(conflicts)}/{fmt_int(total)}",
    )
    peak = max((float(item.get("severity") or 0) for item in conflicts), default=0.0)
    hero = (
        '<div class="alert-hero">'
        '<span class="alert-hero-mark" aria-hidden="true">&#9651;</span>'
        '<div class="alert-hero-label"><span>TEMPORAL CONFLICT INDEX</span>'
        f'<strong>{peak:.3f}</strong></div>'
        '<div class="alert-hero-tags"><span>LEVEL 5</span><span>ACTIVE</span></div>'
        "</div>"
    )
    rows: list[str] = []
    for index, conflict in enumerate(conflicts, start=1):
        severity = float(conflict.get("severity") or 0)
        sev = severity_class(severity)
        label = KIND_LABEL.get(str(conflict.get("kind")), str(conflict.get("kind")))
        short = KIND_SHORT.get(str(conflict.get("kind")), "")
        entity = conflict.get("entity") or conflict.get("device_id") or "MULTI-ENTITY"
        detectors = len(conflict.get("detected_by") or [])
        rows.append(
            f'<div class="alert-row {"focused" if focused_id == conflict.get("id") else ""}">'
            f'<span class="alert-rank sev-{sev}">{index:02d}</span>'
            '<span class="alert-main">'
            f'<span class="alert-kind">{esc(label)}<em>{esc(short)}</em></span>'
            f'<span class="alert-sub">{esc(entity)} - {len(conflict.get("event_ids") or [])} REC - '
            f'{detectors} DETECTOR{"S" if detectors != 1 else ""}</span>'
            '<span class="severity-track">'
            f'<span class="severity-fill {sev}" style="width:{max(3, severity * 100):.1f}%"></span>'
            "</span></span>"
            f'<span class="alert-score"><strong>{fmt_pct(conflict.get("confidence"))}</strong><em>CONF</em></span>'
            "</div>"
        )
    if not rows:
        rows.append(
            '<div class="empty-state"><span class="empty-glyph">&#9672;</span>'
            "<strong>TEMPORAL FIELD CLEAN</strong>"
            "<p>No contradiction survived the detector cascade.</p></div>"
        )
    body = (
        f"{hero}"
        '<div class="alert-legend"><span>RANK / TYPE</span><span>SEVERITY</span></div>'
        f'<div class="alert-queue">{"".join(rows)}</div>'
        '<div class="alert-foot"><span>MIN-HEAP RANKING - O(n log k)</span>'
        f'<span>{f"NEAREST {top_k}" if conflicts else "AWAITING SIGNAL"}</span></div>'
    )
    return (
        f'<section class="panel alert-panel">{head}'
        f'<div class="panel-body alert-panel-body">{body}</div></section>'
    )


def protocol_panel_html(state: dict[str, Any], top_conflict: dict[str, Any] | None, *, selected: str | None, top_k: int) -> str:
    corroborated = int((top_conflict or {}).get("corroboration") or 0)
    body = (
        '<ol class="protocol-list">'
        '<li class="protocol-step active"><span class="step-index">01</span><div>'
        "<strong>TRIAGE</strong>"
        "<p>Open the highest-confidence contradiction and walk the BFS evidence chain.</p>"
        '<span class="protocol-ref">OPEN TRACE VIA ANOMALY QUEUE</span></div></li>'
        '<li class="protocol-step"><span class="step-index">02</span><div>'
        "<strong>CORROBORATE</strong>"
        f"<p>Require independent-source support. Lead has {fmt_int(corroborated)} corroborating source"
        f"{'' if corroborated == 1 else 's'}.</p>"
        f'<span class="protocol-badge {"ok" if corroborated >= 2 else "warn"}">'
        f"{'SOURCE CONSENSUS' if corroborated >= 2 else 'SINGLE-SOURCE'}</span></div></li>"
        '<li class="protocol-step"><span class="step-index">03</span><div>'
        "<strong>RECONCILE</strong>"
        "<p>Audit silences and device offsets. Re-run incremental analysis after any correction.</p>"
        '<span class="protocol-ref">GAP AUDIT VIA OPERATOR CONSOLE</span></div></li>'
        '<li class="protocol-step"><span class="step-index">04</span><div>'
        "<strong>ATTEST</strong>"
        "<p>Export the conflict ledger with detector provenance for chain-of-custody.</p>"
        '<span class="protocol-ref">EXPORT LEDGER VIA OPERATOR CONSOLE</span>'
        "</div></li></ol>"
        '<div class="protocol-foot">'
        f'<span>{esc(KIND_LABEL.get(str((top_conflict or {}).get("kind")), "NO ACTIVE LEAD"))}</span>'
        "<span>PROTOCOL 7-C</span></div>"
    )
    head = panel_head(
        "05",
        "FIELD PROCEDURE",
        "RESOLUTION PROTOCOL",
        f'{fmt_pct(state.get("top_severity"))} PEAK',
    )
    return f'<section class="panel protocol-panel">{head}<div class="panel-body">{body}</div></section>'


# --------------------------------------------------------------------------
# Action matrix
# --------------------------------------------------------------------------

ACTION_ICONS = {
    "scan": '<circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="3 2"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="12" r="2" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    "incremental": '<path d="M4 14a8 8 0 0 1 13.5-5.5L20 11M20 5v6h-6M20 10a8 8 0 0 1-13.5 5.5L4 13M4 19v-6h6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    "record": '<rect x="4" y="4" width="16" height="16" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 9h8M8 13h5M8 17h7M16.5 16.5v3M15 18h3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    "upload": '<path d="M12 16V4M8 8l4-4 4 4M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    "gap": '<path d="M3 12h5M16 12h5M10 8v8M14 8v8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="3" cy="12" r="1.2" fill="currentColor"/><circle cx="21" cy="12" r="1.2" fill="currentColor"/>',
    "bench": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2M3 6l5-3 5 5 6-5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
}


def action_header_html(state: dict[str, Any]) -> str:
    return panel_head("06", "OPERATOR CONSOLE", "ACTION MATRIX", "READY")


def action_telemetry_html(state: dict[str, Any]) -> str:
    return (
        '<div class="action-telemetry">'
        f'<span>LAST SCAN <b>{fmt_ms(state.get("analysis_ms"))}</b></span>'
        f'<span>PENDING EVENTS <b>{fmt_int(state.get("pending_events"))}</b></span>'
        f'<span>PENDING RULES <b>{fmt_int(state.get("pending_rules"))}</b></span>'
        f'<span>RUNS <b>{fmt_int(state.get("analysis_runs"))}</b></span>'
        "</div>"
    )


# --------------------------------------------------------------------------
# Benchmark panel + figure
# --------------------------------------------------------------------------

def bench_header_and_summary(bench: dict[str, Any] | None, *, probe: bool, selected: str | None, top_k: int) -> str:
    summary = (bench or {}).get("summary") or {}
    meta = (
        f'{fmt_compact(summary.get("max_events"))} MAX - {fmt_utc((bench or {}).get("generated_at"))}'
        if bench
        else "NO TELEMETRY"
    )
    keep = {"entity": selected, "top_k": top_k}
    actions = '<span class="probe-badge">LIVE PROBE</span>' if probe else ""
    head = panel_head("07", "EMPIRICAL VALIDATION", "BENCHMARK MATRIX", meta, actions)
    checks = (
        f'{summary.get("results_ok", 0)}/{summary.get("results_ok", 0) + summary.get("results_failed", 0)} OK'
        if summary
        else "-"
    )
    danger = bool(summary.get("results_failed"))
    summary_html = (
        '<div class="bench-summary">'
        f'<div><span>EVENTS TESTED</span><strong>{fmt_int(summary.get("events_tested"))}</strong></div>'
        f'<div><span>AVG PRECISION</span><strong>{fmt_pct(summary.get("avg_precision"), 1)}</strong></div>'
        f'<div><span>AVG RECALL</span><strong>{fmt_pct(summary.get("avg_recall"), 1)}</strong></div>'
        f'<div><span>FASTEST PIPELINE</span><strong>{fmt_ms(summary.get("fastest_analysis_ms"))}</strong></div>'
        f'<div><span>RUN STATUS</span><strong class="{"danger" if danger else "nominal"}">{checks}</strong></div>'
        "</div>"
    )
    return f"{head}{summary_html}"


def bench_table_html(bench: dict[str, Any] | None) -> str:
    rows = (bench or {}).get("results") or []
    body = "".join(
        "<tr>"
        f'<td class="mono strong">{fmt_compact(row.get("events"))}</td>'
        f'<td class="mono">{fmt_ms(row.get("full_analysis_ms"))}</td>'
        f'<td class="mono">{fmt_compact(row.get("events_per_sec"))}</td>'
        f'<td class="mono accent">{_speedup(row.get("tree_speedup_vs_naive"))}</td>'
        f'<td class="mono">{fmt_pct(row.get("precision"))} / {fmt_pct(row.get("recall"))}</td>'
        f'<td class="mono">{float(row.get("peak_traced_mb") or 0):.1f} MB</td>'
        "</tr>"
        for row in rows
    )
    return (
        '<div class="bench-table-wrap">'
        '<div class="bench-chart-head"><span>SCALE RESULTS</span><span>NAIVE BASELINE</span></div>'
        '<table class="bench-table"><thead><tr><th>SIZE</th><th>PIPELINE</th><th>EV/S</th>'
        "<th>SPEEDUP</th><th>P / R</th><th>PEAK</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
        '<p class="bench-note">Naive pairwise baseline capped at 10K by design; above the cap the harness '
        "records a skip rather than fabricating an O(n^2) number.</p></div>"
    )


def _speedup(value: Any) -> str:
    try:
        return f"{float(value):.1f}x"
    except (TypeError, ValueError):
        return "-"


def bench_foot_html(bench: dict[str, Any] | None) -> str:
    config = (bench or {}).get("config") or {}
    sizes = config.get("sizes") or []
    return (
        '<div class="bench-foot">'
        "<span>time.perf_counter - tracemalloc peak</span>"
        f'<span>sizes {" / ".join(fmt_compact(size) for size in sizes) if sizes else "-"}</span>'
        f'<span>seed {config.get("seed", "-")}</span>'
        "</div>"
    )


def _ms_tick(value: float) -> str:
    if value >= 60_000:
        return f"{value / 60_000:g}m" if value % 60_000 == 0 else f"{value / 60_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:g}s" if value % 1_000 == 0 else f"{value / 1_000:.1f}s"
    return f"{value:g}ms"


def _ms_ticks(values: Iterable[Any]) -> tuple[list[float], list[str]]:
    """Decade ticks for a log axis, labelled in ms / s / m."""
    numeric = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            numeric.append(number)
    if not numeric:
        return [], []
    low, high = min(numeric), max(numeric)
    ticks = [
        candidate
        for exponent in range(-2, 7)
        for candidate in (10.0**exponent,)
        if low / 2.2 <= candidate <= high * 2.2
    ]
    return ticks, [_ms_tick(tick) for tick in ticks]


def bench_figure(bench: dict[str, Any] | None) -> go.Figure:
    results = (bench or {}).get("results") or []
    fig = go.Figure()
    sizes = [int(row.get("events") or 0) for row in results]
    series = [
        ("total", "TOTAL PIPELINE", [row.get("full_analysis_ms") for row in results], "#e0a268", 2.2),
        ("index", "INDEX BUILD", [row.get("index_build_ms") for row in results], "#8ba9b8", 1.4),
        ("detectors", "DETECTORS", [row.get("detector_total_ms") for row in results], "#d9775f", 1.4),
        ("graph", "CONSTRAINT GRAPH", [row.get("constraint_graph_ms") for row in results], "#b08a9a", 1.4),
        ("gaps", "GAP SCAN", [row.get("gap_scan_ms") for row in results], "#9fb08a", 1.2),
    ]
    for _, label, values, color, width in series:
        fig.add_trace(
            go.Scatter(
                x=sizes,
                y=values,
                mode="lines+markers",
                name=label,
                line={"color": color, "width": width},
                marker={"size": 5, "color": color},
                hovertemplate="%{x:,} events<br>%{y:.2f} ms<extra>" + label + "</extra>",
            )
        )
    tickvals, ticktext = _ms_ticks(
        value for _, _, values, _, _ in series for value in values
    )
    fig.update_layout(
        height=238,
        margin={"l": 52, "r": 8, "t": 28, "b": 24},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "JetBrains Mono, monospace", "size": 9, "color": "#a99a84"},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
            "font": {"size": 8, "color": "#a99a84"},
            "bgcolor": "rgba(0,0,0,0)",
        },
        xaxis={
            "type": "log",
            "tickvals": sizes,
            "ticktext": [fmt_compact(value) for value in sizes],
            "gridcolor": "rgba(224,162,104,0.08)",
            "linecolor": "rgba(224,162,104,0.24)",
            "tickfont": {"size": 9},
        },
        yaxis={
            "type": "log",
            "tickvals": tickvals,
            "ticktext": ticktext,
            "gridcolor": "rgba(224,162,104,0.08)",
            "linecolor": "rgba(224,162,104,0.24)",
            "tickfont": {"size": 8.5},
        },
        hoverlabel={
            "bgcolor": "#0b0805",
            "bordercolor": "rgba(224,162,104,0.45)",
            "font": {"family": "JetBrains Mono, monospace", "size": 10, "color": "#e8ddc9"},
        },
    )
    return fig


# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------

def footer_html(state: dict[str, Any], *, online: bool) -> str:
    evaluation = state.get("evaluation")
    return (
        '<footer class="hud-footer">'
        '<div class="footer-brand"><span class="footer-mark">CC</span><div>'
        "<strong>CHRONOCLASH // FORENSIC TEMPORAL DIVISION</strong>"
        "<span>ADVANCED DATA STRUCTURES &amp; ALGORITHMS FIELD TERMINAL</span>"
        "</div></div>"
        '<div class="footer-algorithms"><span>AVL INTERVAL FOREST</span><span>BELLMAN-FORD</span>'
        "<span>FLOYD-WARSHALL</span><span>MIN-HEAP TOP-K</span><span>BFS EXPLAIN</span></div>"
        '<div class="footer-status">'
        f'<span><i class="status-dot {"online" if online else "offline"}"></i>'
        f'{"UPLINK STABLE" if online else "UPLINK LOST"}</span>'
        f'<span>CASE {esc(state.get("case_id") or "----")}</span>'
        f'<span>FIDELITY {fmt_pct(evaluation.get("f1"), 1) if evaluation else "N/A"}</span>'
        f'<span>{fmt_int(state.get("event_count"))} RECORDS IN MEMORY</span></div>'
        '<div class="footer-legal"><span>BUILD 1.0.0 // 2026</span>'
        "<span>ALL ALGORITHMS HAND-WRITTEN - NO EXTERNAL INDEX LIBRARIES</span></div>"
        "</footer>"
    )


# --------------------------------------------------------------------------
# Explain and gap overlays
# --------------------------------------------------------------------------

def explain_body_html(payload: dict[str, Any], *, selected: str | None, top_k: int) -> str:
    conflict = payload.get("conflict") or {}
    chain = payload.get("chain") or []
    severity = float(conflict.get("severity") or 0)
    summary = (
        '<div class="explain-summary">'
        f'<div><span>CONFLICT ID</span><strong>{esc(conflict.get("id"))}</strong></div>'
        f'<div><span>TYPE</span><strong>{esc(KIND_LABEL.get(str(conflict.get("kind")), str(conflict.get("kind"))))}</strong></div>'
        f'<div><span>SEVERITY</span><strong class="{severity_class(severity)}">{fmt_pct(severity, 1)}</strong></div>'
        f'<div><span>CONFIDENCE</span><strong>{fmt_pct(conflict.get("confidence"), 1)}</strong></div>'
        f'<div><span>SUBJECT</span><strong>{esc(conflict.get("entity") or conflict.get("device_id") or "MULTI")}</strong></div>'
        f'<div><span>DELTA</span><strong>{fmt_duration(conflict.get("t_delta_s"))}</strong></div>'
        "</div>"
    )
    steps = "".join(
        '<li>'
        f'<span class="chain-step">{int(step.get("step") or 0):02d}</span>'
        '<div class="chain-card">'
        f'<div class="chain-head"><strong>{esc(step.get("record", {}).get("action"))}</strong>'
        f'<span>{esc((step.get("record", {}).get("source") or "").upper())}</span></div>'
        '<div class="chain-meta">'
        f'<span>{esc(step.get("record", {}).get("id"))}</span>'
        f'<span>{esc(step.get("record", {}).get("entity"))}</span>'
        f'<span>{esc(fmt_datetime(step.get("record", {}).get("timestamp")))}</span>'
        "</div>"
        '<div class="chain-sub">'
        f'<span>VIA {esc(step.get("via"))}</span>'
        f'<span>{esc(step.get("record", {}).get("device_id"))}</span>'
        f'<span>{float(step.get("record", {}).get("duration_s") or 0):.1f}s</span>'
        f'<span>REL {fmt_pct(step.get("record", {}).get("reliability"))}</span>'
        "</div></div></li>"
        for step in chain
    )
    if not steps:
        steps = '<li><span class="chain-step">00</span><div class="chain-card">No records remain.</div></li>'
    meta_rows = "".join(
        f"<div><dt>{esc(key)}</dt><dd>{esc(value)}</dd></div>"
        for key, value in (conflict.get("meta") or {}).items()
    )
    sources = "".join(
        f'<span class="data-chip source">{esc(SOURCE_LABEL.get(source, source))}</span>'
        for source in conflict.get("sources") or []
    )
    detectors = "".join(
        f'<span class="data-chip">{esc(detector)}</span>'
        for detector in conflict.get("detected_by") or []
    )
    side = (
        '<div class="explain-side">'
        '<div class="telemetry-grid">'
        f'<div><span>NODES VISITED</span><b>{fmt_int(payload.get("nodes_visited"))}</b></div>'
        f'<div><span>EDGES EXAMINED</span><b>{fmt_int(payload.get("edges_examined"))}</b></div>'
        f'<div><span>EVIDENCE RECORDS</span><b>{fmt_int(len(chain))}</b></div>'
        f'<div><span>CORROBORATION</span><b>{fmt_int(conflict.get("corroboration"))}</b></div>'
        "</div>"
        f'<div class="chip-row">{sources}{detectors}</div>'
        f'<dl class="meta-list">{meta_rows or "<div><dt>provenance</dt><dd>detector cascade</dd></div>"}</dl>'
        "</div>"
    )
    body = (
        '<div class="explain-layout">'
        f"{summary}"
        f'<p class="explain-detail">{esc(conflict.get("detail"))}</p>'
        f'<p class="explain-narrative">{esc(payload.get("narrative"))}</p>'
        '<div class="explain-columns">'
        f'<ol class="evidence-chain">{steps}</ol>'
        f"{side}</div>"
        '<div class="explain-footnote">'
        f'<span>LOCATE SUBJECT VIA THE TRACE CONTROL</span>'
        f'<span>BFS O(V+E) - {fmt_int(payload.get("nodes_visited"))} nodes</span></div>'
        "</div>"
    )
    return body


def gaps_body_html(
    payload: dict[str, Any],
    *,
    threshold: float,
    selected: str | None,
    top_k: int,
) -> str:
    gaps = payload.get("gaps") or []
    rows = "".join(
        "<tr>"
        f'<td class="strong">{esc(gap.get("entity"))}</td>'
        f'<td class="mono dim">{esc(fmt_datetime(gap.get("start")))}</td>'
        f'<td class="mono dim">{esc(fmt_datetime(gap.get("end")))}</td>'
        f'<td class="mono accent">{fmt_duration(gap.get("duration_s"))}</td>'
        f'<td class="mono">{esc(gap.get("after_event") or "-")}</td>'
        f'<td class="mono">{esc(gap.get("before_event") or "-")}</td>'
        "</tr>"
        for gap in gaps
    )
    if not rows:
        rows = (
            '<tr><td colspan="6" class="dim">No silence exceeds the current threshold.</td></tr>'
        )
    return (
        '<div class="gap-controls">'
        f'<span class="control-label">SILENCE THRESHOLD</span><span class="gap-threshold">{int(threshold)}s</span>'
        f'<span class="gap-summary"><b>{fmt_int(len(gaps))}</b> GAPS / {fmt_int(payload.get("returned"))} RETURNED</span>'
        "</div>"
        '<div class="gap-table-wrap"><table class="gap-table"><thead><tr>'
        "<th>SUBJECT</th><th>GAP START</th><th>GAP END</th><th>DURATION</th>"
        "<th>AFTER</th><th>BEFORE</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        '<div class="gap-footnote"><span>SCAN O(n) PER SUBJECT LANE</span>'
        f'<span>FILTER {esc(selected or "ALL SUBJECTS")}</span></div>'
    )


# --------------------------------------------------------------------------
# Utility overlays
# --------------------------------------------------------------------------

def boot_screen_html(error: str | None) -> str:
    error_html = ""
    if error:
        error_html = (
            '<div class="boot-error"><strong>UPLINK SEVERED</strong>'
            f"<p>{esc(error)}</p>"
            '</div>'
        )
    return (
        '<div class="boot-screen">'
        '<div class="boot-grid" aria-hidden="true"></div>'
        '<div class="boot-core">'
        '<span class="boot-sigil">CC</span>'
        '<span class="eyebrow">FORENSIC TEMPORAL DIVISION // UNIT 07</span>'
        "<h1>CHRONO<span>CLASH</span></h1>"
        "<p>ESTABLISHING TEMPORAL UPLINK</p>"
        '<div class="boot-progress"><span></span></div>'
        '<div class="boot-log"><span>NORMALIZING CLOCK DOMAINS</span>'
        "<span>BUILDING AVL INTERVAL FOREST</span>"
        "<span>RELAXING CONSTRAINT GRAPH</span></div>"
        f"{error_html}</div></div>"
    )


def flash_html(message: str, tone: str = "success", detail: str = "") -> str:
    return (
        '<div class="toast-stack"><div class="toast tone-'
        + esc(tone)
        + '"><span class="toast-marker"></span><div>'
        f"<strong>{esc(message)}</strong>"
        + (f"<p>{esc(detail)}</p>" if detail else "")
        + "</div></div></div>"
    )
