"""Generate / Upload page."""

from __future__ import annotations

import csv

import streamlit as st

from contradiction_engine.generator import GeneratorConfig, generate_case
from contradiction_engine.loader import case_variant_warnings, load_case
from contradiction_engine.models import (
    Case,
    case_to_csv,
    places_to_json,
    truth_to_json,
)

from .export import safe_csv
from .widgets import hero_strip, page_header, store_case

NEAR_LIMIT_BYTES = 4 * 1024 * 1024
LARGE_CASE_RECORDS = 5000

SCHEMA_HELP = """
**CSV header** `id,timestamp,record_type,person,device,place,state,action,account,depends_on,claim,end_timestamp,text`
- `state`: device, state ON/OFF/SLEEP · `activity`: device, action
- `sighting`: person, place · `message`: person, optional depends_on
- `login`: person, account; a non-empty `device` makes it local activity
- `claim`: `did_not_access` needs person, account, end_timestamp; `claimed_at` needs person, place, end_timestamp
  (`claimed_at` is checked at both window edges, not continuously)
Timestamps are ISO-8601 (naive means UTC). Default places: Harbour, Station, Market, Clinic, Library, Dock, Park, Museum, Cafe, Warehouse.
**places.json** `{"places": {"X": [51.5, -0.12], "Y": [51.51, -0.11]}, "edges": [["X", "Y", 4]]}`
Two-value edges derive minutes with haversine; three-value edges set them.
"""


def render_generate_page() -> None:
    """Render the case generation and upload workflow."""
    page_header(
        "Generate or upload",
        "Start with a seeded fictional case or bring your own evidence files.",
    )
    hero_strip()
    _demo_row()
    with st.container(border=True):
        _generate_form()
    _upload_form()
    with st.expander("Upload schema and example"):
        st.markdown(SCHEMA_HELP)
    _case_summary()


def _demo_row() -> None:
    """Render the one-click demo case action."""
    left, right = st.columns([1, 3])
    with left:
        if st.button("Load demo case", type="secondary"):
            _load_demo()
    with right:
        st.caption("Demo preset, seed 42, including every conflict kind.")


def _load_demo() -> None:
    """Generate and store the demo case with one claimed-place conflict."""
    _load_generated(
        GeneratorConfig(location_claim_conflicts=1),
        source="Demo · seed 42",
    )


def _generate_form() -> None:
    """Render the seeded generator form."""
    with st.form("generate"):
        seed = st.number_input("Seed", min_value=1, max_value=999999, value=42)
        people = st.slider("People", min_value=1, max_value=8, value=4)
        columns = st.columns(5)
        device = columns[0].slider("Device was off", 0, 5, 2)
        travel = columns[1].slider("Impossible-travel conflicts", 0, 5, 2)
        message = columns[2].slider("Message conflicts", 0, 5, 2)
        claim = columns[3].slider("Denied-access conflicts", 0, 5, 2)
        place = columns[4].slider("Claimed-place conflicts", 0, 5, 1)
        if st.form_submit_button("Generate case", type="primary"):
            _load_generated(
                GeneratorConfig(
                    seed=int(seed),
                    people=int(people),
                    device_conflicts=int(device),
                    location_conflicts=int(travel),
                    message_conflicts=int(message),
                    claim_conflicts=int(claim),
                    location_claim_conflicts=int(place),
                )
            )


def _load_generated(
    config: GeneratorConfig,
    source: str | None = None,
) -> None:
    """Generate and store a case with its visible settings as the source."""
    generated = generate_case(config)
    label = source or f"Generated · seed {config.seed}"
    store_case(generated.case, label)
    st.success(f"Generated {len(generated.case.records)} records.")


def _upload_form() -> None:
    """Render the upload form with optional files collapsed by default."""
    with st.expander("Upload a case", expanded=False):
        st.caption(
            "Use only fictional or anonymised data. Uploads are processed in "
            "memory for this session and are not saved by this app."
        )
        with st.form("upload"):
            upload = st.file_uploader("Case CSV or JSON", type=["csv", "json"])
            with st.expander("Optional ground truth and places files"):
                truth = st.file_uploader(
                    "Optional ground truth JSON", type=["json"]
                )
                places = st.file_uploader(
                    "Optional places JSON", type=["json"]
                )
            if st.form_submit_button("Load case"):
                _load_upload(upload, truth, places)


def _load_upload(upload: object, truth: object, places: object) -> None:
    """Validate uploaded bytes and store the case only on success."""
    if upload is None:
        st.error("Choose a CSV or JSON file first.")
        return
    if upload.size > NEAR_LIMIT_BYTES:
        st.caption("This file is close to the 5 MB upload limit.")
    case, errors = safe_load_case(
        upload.name,
        upload.getvalue(),
        truth.getvalue() if truth else None,
        places.getvalue() if places else None,
    )
    if errors:
        st.error("Upload rejected. The current case was not changed.")
        for message in errors:
            st.write(f"- {message}")
        return
    store_case(case, f"Upload · {upload.name}")
    st.success(f"Loaded {len(case.records)} records.")
    if len(case.records) > LARGE_CASE_RECORDS:
        st.warning("Large case: pages with many conflicts may load slowly.")


def safe_load_case(
    name: str, data: bytes, truth: bytes | None = None,
    places: bytes | None = None,
) -> tuple[Case | None, list[str]]:
    """Run the loader, turning unexpected parser errors into messages."""
    try:
        return load_case(name, data, truth, places)
    except (csv.Error, UnicodeError, ValueError, KeyError) as error:
        return None, [f"file: could not be read ({str(error)[:100]})"]


def _case_summary() -> None:
    """Show case counts, warnings, and downloads."""
    case = st.session_state.case
    if case is None:
        return
    index = st.session_state.index
    with st.container(border=True):
        st.caption("Active case")
        st.subheader(case.name)
        columns = st.columns(4)
        columns[0].metric("Records", len(case.records))
        columns[1].metric("People", len(index.people()))
        columns[2].metric("Devices", len(index.devices()))
        columns[3].metric("Places", len(case.places))
        _render_warnings(case)
        _render_downloads(case)


def _render_warnings(case: Case) -> None:
    """Show case-variant warnings when entity spellings differ only by case."""
    for message in case_variant_warnings(case.records):
        st.warning(message)


def _render_downloads(case: Case) -> None:
    """Render the three case download buttons."""
    left, middle, right = st.columns(3)
    left.download_button(
        "Download case.csv", safe_csv(case_to_csv(case)), "case.csv", "text/csv"
    )
    middle.download_button(
        "Download ground_truth.json",
        truth_to_json(case),
        "ground_truth.json",
        "application/json",
    )
    right.download_button(
        "Download places.json",
        places_to_json(case),
        "places.json",
        "application/json",
    )
