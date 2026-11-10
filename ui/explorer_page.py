"""Evidence Explorer page: records, relationships, and index diagnostics."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pandas as pd
import streamlit as st

from contradiction_engine.algorithms.graph import WeightedGraph
from contradiction_engine.models import Case, CaseIndex, Evidence

from .dot_theme import style_entity_dot, style_road_dot
from .widgets import case_graph, RECORD_TYPE_LABELS, page_header, records_frame

FILTER_KEYS = (
    "explorer_person",
    "explorer_device",
    "explorer_account",
    "explorer_keyword",
    "explorer_dates",
)

RESIZE_THRESHOLD = 0.75

# Fixed markup: no case data is ever interpolated into it.
RING_LEGEND_HTML = (
    '<div class="hud-legend" aria-label="Ring colour shows hops from the start">'
    '<span><i class="hud-ring hud-ring-0"></i>Start</span>'
    '<span><i class="hud-ring hud-ring-1"></i>1 hop</span>'
    '<span><i class="hud-ring hud-ring-2"></i>2 hops</span>'
    '<span><i class="hud-ring hud-ring-3"></i>3 hops</span>'
    '<span><i class="hud-ring hud-ring-far"></i>Outside the hop limit</span>'
    "</div>"
)


def render_explorer_page() -> None:
    """Show the records, relationships, and hash index health tabs."""
    case = st.session_state.case
    index = st.session_state.index
    page_header(
        "Evidence explorer",
        "Filter records, inspect relationships, and check the hash index health.",
    )
    if case is None or not index.records:
        st.info("Generate or upload a case on the first page.")
        return
    records_tab, relations_tab, diagnostics_tab = st.tabs(
        ["Records", "Relationships", "Hash index health"]
    )
    with records_tab:
        _render_records_tab(index)
    with relations_tab:
        _render_graph_views(case, index)
    with diagnostics_tab:
        _render_index_diagnostics(index)


def _render_records_tab(index: CaseIndex) -> None:
    """Show filters, the record table, and a volume chart."""
    with st.container(border=True):
        if st.button("Reset filters"):
            for key in FILTER_KEYS:
                st.session_state.pop(key, None)
            st.rerun()
        results = _filter_records(index)
    st.caption(f"{len(results)} record(s)")
    if not results:
        st.info("No records match these filters.")
        return
    st.dataframe(records_frame(results), width="stretch", hide_index=True)
    _render_volume_chart(results)


def _filter_records(index: CaseIndex) -> list[Evidence]:
    """Apply the entity, date range, and keyword filters together."""
    columns = st.columns(3)
    picks = {
        "person": columns[0].selectbox("Person", ["All"] + index.people(),
                                       key="explorer_person"),
        "device": columns[1].selectbox("Device", ["All"] + index.devices(),
                                       key="explorer_device"),
        "account": columns[2].selectbox("Account", ["All"] + index.accounts(),
                                        key="explorer_account"),
    }
    results = _by_entity(index, list(index.records), picks)
    results = _by_date(index, results)
    keyword = st.text_input("Keyword", key="explorer_keyword")
    if keyword.strip():
        allowed = {row.id for row in index.keyword(keyword)}
        results = [row for row in results if row.id in allowed]
    return results


def _by_entity(index: CaseIndex, results: list[Evidence],
               picks: dict[str, str]) -> list[Evidence]:
    """Keep records linked to every selected person, device, and account."""
    lookups = (("person", index.for_person), ("device", index.for_device),
               ("account", index.for_account))
    for name, lookup in lookups:
        if picks[name] != "All":
            allowed = {row.id for row in lookup(picks[name])}
            results = [row for row in results if row.id in allowed]
    return results


def _by_date(index: CaseIndex, results: list[Evidence]) -> list[Evidence]:
    """Keep records inside the chosen date range with a binary-search slice."""
    first = index.records[0].timestamp.date()
    last = index.records[-1].timestamp.date()
    chosen = st.date_input("Date range", value=(first, last), min_value=first,
                           max_value=last, key="explorer_dates")
    chosen = tuple(chosen) if isinstance(chosen, (tuple, list)) else (chosen,)
    start, end = chosen[0], chosen[-1]
    start_at = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end, time.max, tzinfo=timezone.utc)
    allowed = {row.id for row in index.in_range(start_at, end_at)}
    return [row for row in results if row.id in allowed]


def _render_volume_chart(results: list[Evidence]) -> None:
    """Chart records per hour, else per type; hide when nothing to compare."""
    hours = pd.Series(
        [row.timestamp.strftime("%m-%d %H:00") for row in results]
    ).value_counts().sort_index()
    if len(hours) > 1:
        st.caption("Records per hour")
        st.bar_chart(hours)
        return
    types = pd.Series(
        [RECORD_TYPE_LABELS.get(row.record_type, row.record_type)
         for row in results]
    ).value_counts()
    if len(types) > 1:
        st.caption("Records per type")
        st.bar_chart(types)


def _render_graph_views(case: Case, index: CaseIndex) -> None:
    """Show the road map and the entity-relationship graph."""
    with st.expander("How these views work"):
        st.markdown(
            "**Road network · Dijkstra** — nodes are places and edges are roads. "
            "Edge labels are travel time in **minutes**. Dijkstra finds the "
            "fastest route, which may pass through other places.\n\n"
            "**Entity links · BFS** — nodes are people, devices, accounts and "
            "places. An edge means the two entities appear in the same record "
            "(or one message depends on another). Shape shows the entity kind; "
            "the coloured ring shows the number of BFS hops from the start.\n\n"
            "**Hash index health** — each index is a hash table. *Load factor* "
            "is keys ÷ buckets; the table resizes above 0.75. *Longest chain* "
            "is the most keys sharing one bucket; above 1 is normal."
        )
    map_tab, entity_tab = st.tabs(
        ["Road network · Dijkstra", "Entity links · BFS"]
    )
    with map_tab:
        _render_place_map(case)
    with entity_tab:
        _render_entity_graph(index)


def _render_place_map(case: Case) -> None:
    """Draw the sparse road map and highlight one shortest route."""
    graph = case_graph(case)
    places = graph.nodes()
    columns = st.columns([1, 1, 0.42], vertical_alignment="bottom")
    source = columns[0].selectbox("From place", places, key="map_from")
    target = columns[1].selectbox(
        "To place", places, index=min(1, len(places) - 1), key="map_to"
    )
    columns[2].button("Swap", key="map_swap", on_click=_swap_map)
    distances, previous = graph.dijkstra(source)
    required = distances.get(target)
    path = graph.shortest_path(previous, source, target)
    if required is None:
        st.warning("No route connects those places.")
    else:
        st.caption(f"Fastest route · {' → '.join(path)} · {required:.0f} min")
        _render_direct_comparison(graph, source, target, path, required)
    st.caption(
        "Place = node · road = edge · label = travel minutes · "
        "sky blue = fastest route."
    )
    st.graphviz_chart(
        style_road_dot(graph.to_dot(path), path), width="stretch"
    )


def _swap_map() -> None:
    """Callback: exchange the From and To place selections."""
    st.session_state.map_from, st.session_state.map_to = (
        st.session_state.map_to, st.session_state.map_from
    )


def _render_direct_comparison(
    graph: WeightedGraph,
    source: str,
    target: str,
    path: list[str],
    required: float,
) -> None:
    """Note when a multi-stop route beats the direct road."""
    direct = graph.edge_weight(source, target)
    if direct is None or len(path) <= 2 or direct <= required:
        return
    stops = len(path) - 2
    st.caption(
        f"Direct road: {direct:.0f} min · {stops} stop(s) save "
        f"{direct - required:.0f} min."
    )


def _render_entity_graph(index: CaseIndex) -> None:
    """Draw the entity graph around one start node using BFS."""
    graph = index.evidence_graph
    nodes = graph.nodes()
    if not nodes:
        st.info("No entities to graph.")
        return
    start = st.selectbox(
        "Entity (person, device, account, or place)",
        nodes,
        key="entity_start",
    )
    depth = st.slider("Hops", min_value=1, max_value=3, value=2,
                      key="entity_depth")
    related = graph.related(start, depth)
    st.caption(f"{len(related)} entities within {depth} hop(s) of {start}.")
    st.caption(
        "Shape shows the kind: ellipse = person · box = device · "
        "diamond = account · house = place."
    )
    st.markdown(RING_LEGEND_HTML, unsafe_allow_html=True)
    st.graphviz_chart(
        style_entity_dot(graph.to_dot({start: 0, **related}), start),
        width="stretch",
    )
    if related:
        rows = [{"entity": node, "hops": hops} for node, hops in related.items()]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_index_diagnostics(index: CaseIndex) -> None:
    """Show load factor and longest chain for each hash index."""
    tables = (("Person", index.person_index), ("Device", index.device_index),
              ("Account", index.account_index))
    rows = [
        {
            "Index": label,
            "Keys": len(table),
            "Buckets": table.capacity,
            "Load factor": round(table.load_factor, 2),
            "Longest chain": table.longest_chain(),
        }
        for label, table in tables
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    columns = st.columns(3)
    for column, (label, table) in zip(columns, tables):
        with column:
            st.markdown(
                load_meter_html(label, len(table), table.capacity,
                                table.load_factor),
                unsafe_allow_html=True,
            )
    st.caption(
        f"Load factor = keys ÷ buckets. The vertical tick marks the "
        f"{RESIZE_THRESHOLD:.2f} resize threshold. A longest chain above 1 is "
        "normal with separate chaining; this panel reports hash-table "
        "density, not evidence quality."
    )
    st.caption(
        "Hash function: FNV-1a 64-bit · average O(1) lookup · "
        "worst O(n) when every key collides."
    )


def load_meter_html(label: str, keys: int, buckets: int, load: float) -> str:
    """Return a load-factor meter with a tick at the resize threshold.

    Inputs: a fixed index label and three numbers from a hash table.
    Outputs: one line of HTML; only numbers and the fixed label appear in it.
    Complexity: O(1).
    """
    fill = max(0.0, min(load, 1.0)) * 100
    tick = RESIZE_THRESHOLD * 100
    return (
        f'<div class="hud-meter" role="meter" aria-label="{label} load factor"'
        f' aria-valuemin="0" aria-valuemax="1" aria-valuenow="{load:.2f}">'
        f'<div class="hud-meter-label"><span>{label}</span>'
        f"<span>load {load:.2f} · {keys} keys / {buckets} buckets</span></div>"
        f'<div class="hud-meter-track">'
        f'<div class="hud-meter-fill" style="width:{fill:.1f}%"></div>'
        f'<div class="hud-meter-mark" style="left:{tick:.0f}%"'
        f' title="Resize threshold {RESIZE_THRESHOLD:.2f}"></div>'
        "</div></div>"
    )
