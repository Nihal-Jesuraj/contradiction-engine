"""Evidence Explorer page."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pandas as pd
import streamlit as st

from contradiction_engine.models import CaseIndex, Evidence

from .widgets import page_header

FILTER_KEYS = (
    "explorer_person",
    "explorer_device",
    "explorer_account",
    "explorer_keyword",
)


def render_explorer_page() -> None:
    """Filter the case by entity, time range, and keyword."""
    case = st.session_state.case
    index = st.session_state.index
    page_header(
        "Evidence explorer",
        "Filter records, inspect relationships, and read the index diagnostics.",
    )
    if case is None:
        st.info("Generate or upload a case on the first page.")
        return
    if st.button("Reset filters"):
        for key in FILTER_KEYS:
            st.session_state.pop(key, None)
        st.rerun()
    results = _filter_records(index)
    st.caption(f"{len(results)} record(s)")
    if results:
        _render_results(results)
    else:
        st.info("No records match these filters.")
    _render_graph_views(case, index)
    _render_index_diagnostics(index)


def _filter_records(index: CaseIndex) -> list[Evidence]:
    """Apply the entity, date, and keyword filters."""
    scope = st.selectbox("Filter by", ["All", "Person", "Device", "Account"])
    results = list(index.records)
    if scope == "Person":
        value = st.selectbox("Person", ["All"] + index.people(),
                             key="explorer_person")
        if value != "All":
            results = index.for_person(value)
    elif scope == "Device":
        value = st.selectbox("Device", ["All"] + index.devices(),
                             key="explorer_device")
        if value != "All":
            results = index.for_device(value)
    elif scope == "Account":
        value = st.selectbox("Account", ["All"] + index.accounts(),
                             key="explorer_account")
        if value != "All":
            results = index.for_account(value)

    columns = st.columns(2)
    start_date = columns[0].date_input("Start date",
                                       value=index.records[0].timestamp.date())
    end_date = columns[1].date_input("End date",
                                     value=index.records[-1].timestamp.date())
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    results = [row for row in results if start <= row.timestamp <= end]

    keyword = st.text_input("Keyword", key="explorer_keyword")
    if keyword.strip():
        allowed = {row.id for row in index.keyword(keyword)}
        results = [row for row in results if row.id in allowed]
    return results


def _render_results(results: list[Evidence]) -> None:
    """Show the matching records and a records-per-day chart."""
    st.dataframe(pd.DataFrame([row.to_dict() for row in results]),
                 width="stretch", hide_index=True)
    days = pd.DataFrame(
        {"day": [row.timestamp.date().isoformat() for row in results]}
    )
    counts = days.groupby("day").size().reset_index(name="records")
    st.bar_chart(counts, x="day", y="records")


def _render_graph_views(case: object, index: CaseIndex) -> None:
    """Show the road map and the entity-relationship graph."""
    st.divider()
    st.subheader("Relationship views")
    map_tab, entity_tab = st.tabs(["Place map", "Entity graph"])
    with map_tab:
        _render_place_map(case)
    with entity_tab:
        _render_entity_graph(index)


def _render_place_map(case: object) -> None:
    """Draw the sparse road map and highlight one shortest route."""
    graph = case.graph()
    places = graph.nodes()
    columns = st.columns(2)
    source = columns[0].selectbox("From place", places, key="map_from")
    target = columns[1].selectbox(
        "To place", places, index=min(1, len(places) - 1), key="map_to"
    )
    distances, previous = graph.dijkstra(source)
    required = distances.get(target)
    path = graph.shortest_path(previous, source, target)
    if required is None:
        st.warning("No route connects those places.")
    else:
        st.caption(
            f"Shortest route: {' -> '.join(path)} · {required:.0f} minutes"
        )
    st.graphviz_chart(graph.to_dot(path), width="stretch")


def _render_entity_graph(index: CaseIndex) -> None:
    """Draw the entity graph around one start node using BFS."""
    graph = index.evidence_graph
    nodes = graph.nodes()
    if not nodes:
        st.info("No entities to graph.")
        return
    start = st.selectbox("Start entity", nodes, key="entity_start")
    depth = st.slider("Hops", min_value=1, max_value=3, value=2,
                      key="entity_depth")
    related = graph.related(start, depth)
    highlight = {start: 0}
    highlight.update(related)
    st.caption(f"{len(related)} entities within {depth} hop(s) of {start}.")
    st.graphviz_chart(graph.to_dot(highlight), width="stretch")
    if related:
        rows = [{"entity": node, "hops": hops}
                for node, hops in related.items()]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_index_diagnostics(index: CaseIndex) -> None:
    """Show load factor and longest chain for each hash index."""
    with st.expander("Hash index diagnostics"):
        columns = st.columns(3)
        tables = (
            ("Person", index.person_index),
            ("Device", index.device_index),
            ("Account", index.account_index),
        )
        for column, (label, table) in zip(columns, tables):
            column.metric(label, f"{len(table)} keys")
            column.caption(
                f"load factor {table.load_factor:.2f} · "
                f"longest chain {table.longest_chain()}"
            )
