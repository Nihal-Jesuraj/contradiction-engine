"""Contradiction Engine Streamlit UI.

Presentation code only: detection, parsing, and scoring live in the
``contradiction_engine`` package. Run from the repository root::

    streamlit run app.py
"""

from __future__ import annotations

from datetime import datetime, time, timezone

import pandas as pd
import streamlit as st

from contradiction_engine.detectors import run_all_detectors
from contradiction_engine.generator import GeneratorConfig, generate_case
from contradiction_engine.loader import case_variant_warnings, load_case
from contradiction_engine.models import (
    Case,
    CaseIndex,
    Conflict,
    Evidence,
    case_to_csv,
    places_to_json,
    score_conflicts,
    truth_to_json,
)

DETECTOR_HELP = {
    "device state": "HashTable grouping + merge-sorted intervals + binary search. O(n log n).",
    "location": "HashTable + merge sort + Dijkstra with a min-heap, cached per source. O(n log n + V(V+E) log V).",
    "message chronology": "Directed graph + one colouring DFS for cycles and topological order. O(V + E).",
    "interview claims": "HashTable + merge sort + binary-search bounds on the claim window. O(n log n + c log n).",
    "location claims": "HashTable + merge sort + binary-search bounds + Dijkstra from the claimed place. O(n log n + V(V+E) log V).",
}

SCHEMA_HELP = """
**CSV header** `id,timestamp,record_type,person,device,place,state,action,account,depends_on,claim,end_timestamp,text`
- `state`: device, state ON/OFF/SLEEP · `activity`: device, action
- `sighting`: person, place · `message`: person, optional depends_on
- `login`: person, account
- `claim`: `did_not_access` needs person, account, end_timestamp; `claimed_at` needs person, place, end_timestamp
  (`claimed_at` is checked at both window edges, not continuously)
Timestamps are ISO-8601 (naive means UTC). Default places: Harbour, Station, Market, Clinic, Library, Dock, Park, Museum, Cafe, Warehouse.
**places.json** `{"places": {"X": [51.5, -0.12], "Y": [51.51, -0.11]}, "edges": [["X", "Y", 4]]}`
Two-value edges derive minutes with haversine; three-value edges set them.
"""

def main() -> None:
    """Configure the page and route to one of the three pages."""
    st.set_page_config(page_title="Contradiction Engine", page_icon="🔎",
                       layout="wide")
    _init_state()
    st.title("Contradiction Engine")
    page = st.sidebar.radio(
        "Page", ["Generate / Upload", "Analyze & Conflicts", "Evidence Explorer"]
    )
    st.sidebar.divider()
    st.sidebar.caption(
        "Investigative-support prototype. A conflict means records disagree "
        "under the stated rules, not that a person is guilty or lying."
    )
    if page == "Generate / Upload":
        page_generate()
    elif page == "Analyze & Conflicts":
        page_analyze()
    else:
        page_explorer()

def _init_state() -> None:
    """Create the session keys used by all pages."""
    defaults = {"case": None, "index": None, "conflicts": [], "score": None}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def _store_case(case: Case) -> None:
    """Replace the active case and clear any previous analysis."""
    st.session_state.case = case
    st.session_state.index = CaseIndex(case.records)
    st.session_state.conflicts = []
    st.session_state.score = None

def page_generate() -> None:
    """Generate or upload a case, then show a summary and downloads."""
    _generate_form()
    _upload_form()
    with st.expander("Upload schema and example"):
        st.markdown(SCHEMA_HELP)
    if st.session_state.case is not None:
        _case_summary(st.session_state.case)

def _generate_form() -> None:
    """Render the seeded generator form."""
    st.subheader("Generate a fictional case")
    with st.form("generate"):
        seed = st.number_input("Seed", min_value=1, max_value=999999, value=42)
        people = st.slider("People", min_value=1, max_value=8, value=4)
        columns = st.columns(5)
        device_count = columns[0].slider("Device conflicts", 0, 5, 2)
        location_count = columns[1].slider("Location conflicts", 0, 5, 2)
        message_count = columns[2].slider("Message conflicts", 0, 5, 2)
        claim_count = columns[3].slider("Claim conflicts", 0, 5, 2)
        location_claim_count = columns[4].slider("Location claims", 0, 5, 1)
        if st.form_submit_button("Generate case", type="primary"):
            generated = generate_case(GeneratorConfig(
                seed=int(seed), people=int(people),
                device_conflicts=int(device_count), location_conflicts=int(location_count),
                message_conflicts=int(message_count), claim_conflicts=int(claim_count),
                location_claim_conflicts=int(location_claim_count)))
            _store_case(generated.case)
            st.success(f"Generated {len(generated.case.records)} records.")

def _upload_form() -> None:
    """Render the CSV/JSON upload form."""
    st.subheader("Or upload a case")
    with st.form("upload"):
        upload = st.file_uploader("Case CSV or JSON", type=["csv", "json"])
        truth = st.file_uploader("Optional ground truth JSON", type=["json"])
        places = st.file_uploader("Optional places JSON", type=["json"])
        if st.form_submit_button("Load case"):
            if upload is None:
                st.error("Choose a CSV or JSON file first.")
            else:
                case, errors = load_case(
                    upload.name, upload.getvalue(),
                    truth.getvalue() if truth else None,
                    places.getvalue() if places else None,
                )
                if errors:
                    st.error("Upload rejected. The current case was not changed.")
                    for message in errors:
                        st.write(f"- {message}")
                else:
                    _store_case(case)
                    st.success(f"Loaded {len(case.records)} records.")

def _case_summary(case: Case) -> None:
    """Show record counts and download buttons for the active case."""
    st.divider()
    st.subheader(case.name)
    columns = st.columns(4)
    columns[0].metric("Records", len(case.records))
    columns[1].metric("People", len(st.session_state.index.people()))
    columns[2].metric("Devices", len(st.session_state.index.devices()))
    columns[3].metric("Places", len(case.places))
    for message in case_variant_warnings(case.records):
        st.warning(message)
    st.download_button("Download case.csv", case_to_csv(case), "case.csv", "text/csv")
    st.download_button("Download ground_truth.json", truth_to_json(case), "ground_truth.json", "application/json")
    st.download_button("Download places.json", places_to_json(case), "places.json", "application/json")

def page_analyze() -> None:
    """Run the detectors and explain one selected conflict."""
    case = st.session_state.case
    if case is None:
        st.info("Generate or upload a case on the first page.")
        return
    if st.button("ANALYZE", type="primary"):
        conflicts = run_all_detectors(case.records, case.graph())
        st.session_state.conflicts = conflicts
        st.session_state.score = score_conflicts(conflicts, case.ground_truth)
    conflicts = st.session_state.conflicts
    _analysis_metrics(case, conflicts)
    score = st.session_state.score
    if score is not None and score.available:
        st.write(
            f"Precision **{score.precision:.2f}** · Recall "
            f"**{score.recall:.2f}** · F1 **{score.f1:.2f}** · "
            f"{score.matched}/{score.planted} planted conflicts matched"
        )
    if not conflicts:
        st.warning(
            "No conflicts detected. This means the records are consistent "
            "under the stated rules, not that they are true."
        )
    else:
        _conflict_table(case, conflicts)
    _render_help()

def _analysis_metrics(case: Case, conflicts: list[Conflict]) -> None:
    """Show record and per-kind conflict counts."""
    kinds = (
        "device_state", "location", "message_order",
        "message_cycle", "claim", "claim_location",
    )
    columns = st.columns(len(kinds) + 2)
    columns[0].metric("Records", len(case.records))
    columns[1].metric("Conflicts", len(conflicts))
    for column, kind in zip(columns[2:], kinds):
        column.metric(kind, sum(1 for conflict in conflicts if conflict.kind == kind))

def _conflict_table(case: Case, conflicts: list[Conflict]) -> None:
    """Show the conflict table and the selected conflict's detail."""
    table = [
        {
            "kind": conflict.kind,
            "severity": conflict.severity,
            "records": ", ".join(conflict.record_ids),
            "rule": conflict.rule_text,
            "explanation": conflict.explanation,
        }
        for conflict in conflicts
    ]
    st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)
    choice = st.selectbox(
        "Inspect a conflict", range(len(conflicts)),
        format_func=lambda index: (
            f"{conflicts[index].kind}: " + ", ".join(conflicts[index].record_ids)
        ),
    )
    _render_conflict(case, conflicts[choice])

def _render_conflict(case: Case, conflict: Conflict) -> None:
    """Show the conflicting records next to the rule and the numbers."""
    records = {record.id: record for record in case.records}
    left, right = st.columns(2)
    with left:
        st.subheader("Conflicting records")
        for record_id in conflict.record_ids:
            record = records.get(record_id)
            if record is not None:
                st.markdown(f"**{record_id}** · {record.record_type}")
                st.json(record.to_dict())
    with right:
        st.subheader("Broken rule")
        st.write(conflict.rule_text)
        st.write(conflict.explanation)
        numbers = [
            {"number": key, "value": str(value)}
            for key, value in conflict.numbers.items()
        ]
        st.table(pd.DataFrame(numbers))

def _render_help() -> None:
    """Show one 'How this works' panel per detector."""
    for title, text in DETECTOR_HELP.items():
        with st.expander(f"How {title} detection works"):
            st.write(text)

def page_explorer() -> None:
    """Filter the case by entity, time range, and keyword."""
    case = st.session_state.case
    index = st.session_state.index
    if case is None:
        st.info("Generate or upload a case on the first page.")
        return
    if st.button("Reset filters"):
        for key in ("explorer_person", "explorer_device",
                    "explorer_account", "explorer_keyword"):
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
    _render_help()

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


def _render_graph_views(case: Case, index: CaseIndex) -> None:
    """Show the road map and the entity-relationship graph."""
    st.divider()
    st.subheader("Relationship views")
    map_tab, entity_tab = st.tabs(["Place map", "Entity graph"])
    with map_tab:
        _render_place_map(case)
    with entity_tab:
        _render_entity_graph(index)


def _render_place_map(case: Case) -> None:
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
    with st.expander("How the place map works"):
        st.write(
            "Dijkstra expands the nearest unfinalized place using our own "
            "binary min-heap. The red edges are the shortest route, which can "
            "avoid a slower direct road. O((V + E) log V)."
        )


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
        rows = [
            {"entity": node, "hops": hops}
            for node, hops in related.items()
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    with st.expander("How the entity graph works"):
        st.write(
            "People, devices, accounts, and places are linked when they appear "
            "in the same record. Breadth-first search with a deque finds every "
            "entity within k hops. O(V + E)."
        )


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


if __name__ == "__main__":
    main()
