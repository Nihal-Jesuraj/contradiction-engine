"""Evidence Explorer page: records, relationships, and index diagnostics."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pandas as pd
import streamlit as st

from contradiction_engine.models import Case, CaseIndex, Evidence

from .widgets import case_graph, RECORD_TYPE_LABELS, page_header, records_frame

FILTER_KEYS = (
    "explorer_person",
    "explorer_device",
    "explorer_account",
    "explorer_keyword",
    "explorer_dates",
)


def render_explorer_page() -> None:
    """Show the records, relationship, and diagnostics tabs."""
    case = st.session_state.case
    index = st.session_state.index
    page_header(
        "Evidence explorer",
        "Filter records, inspect relationships, and read the index diagnostics.",
    )
    if case is None or not index.records:
        st.info("Generate or upload a case on the first page.")
        return
    records_tab, relations_tab, diagnostics_tab = st.tabs(
        ["Records", "Relationships", "Diagnostics"]
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
    map_tab, entity_tab = st.tabs(["Place map", "Entity graph"])
    with map_tab:
        _render_place_map(case)
    with entity_tab:
        _render_entity_graph(index)


def _render_place_map(case: Case) -> None:
    """Draw the sparse road map and highlight one shortest route."""
    graph = case_graph(case)
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
        st.caption(f"Shortest route: {' -> '.join(path)} · {required:.0f} minutes")
    st.graphviz_chart(graph.to_dot(path), width="stretch")


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
    st.graphviz_chart(graph.to_dot({start: 0, **related}), width="stretch")
    if related:
        rows = [{"entity": node, "hops": hops} for node, hops in related.items()]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_index_diagnostics(index: CaseIndex) -> None:
    """Show load factor and longest chain for each hash index."""
    columns = st.columns(3)
    tables = (("Person", index.person_index), ("Device", index.device_index),
              ("Account", index.account_index))
    for column, (label, table) in zip(columns, tables):
        with column, st.container(border=True):
            st.metric(label, f"{len(table)} keys")
            st.caption(f"load factor {table.load_factor:.2f} · "
                       f"longest chain {table.longest_chain()}")
