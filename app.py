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
from contradiction_engine.loader import load_case
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
}

SCHEMA_HELP = """
**CSV header** `id,timestamp,record_type,person,device,place,state,action,account,depends_on,claim,end_timestamp,text`
- `state`: device, state ON/OFF/SLEEP · `activity`: device, action
- `sighting`: person, place · `message`: person, optional depends_on
- `login`: person, account · `claim`: person, account, claim=did_not_access, end_timestamp
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
        columns = st.columns(4)
        device_count = columns[0].slider("Device conflicts", 0, 5, 2)
        location_count = columns[1].slider("Location conflicts", 0, 5, 2)
        message_count = columns[2].slider("Message conflicts", 0, 5, 2)
        claim_count = columns[3].slider("Claim conflicts", 0, 5, 2)
        if st.form_submit_button("Generate case", type="primary"):
            generated = generate_case(GeneratorConfig(
                seed=int(seed), people=int(people),
                device_conflicts=int(device_count), location_conflicts=int(location_count),
                message_conflicts=int(message_count), claim_conflicts=int(claim_count)))
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
    kinds = ("device_state", "location", "message_order", "claim")
    columns = st.columns(6)
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
    index = st.session_state.index
    if st.session_state.case is None:
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


if __name__ == "__main__":
    main()
