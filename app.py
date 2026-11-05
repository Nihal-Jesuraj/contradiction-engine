"""Contradiction Engine Streamlit entry point.

This file only wires the UI together. All detection logic lives in the
``contradiction_engine`` package so the algorithms stay testable without
Streamlit.

Run from the repository root::

    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st


def main() -> None:
    """Render the scaffold page.

    Inputs: none.
    Outputs: none (writes to the Streamlit page).
    Complexity: O(1), because no case is loaded yet.
    """
    st.set_page_config(
        page_title="Contradiction Engine",
        page_icon="🔎",
        layout="wide",
    )
    st.title("Contradiction Engine")
    st.caption(
        "Investigative-support prototype. Not a guilt or lie detector."
    )
    st.info(
        "Scaffold only. Generate/Upload, Analyze & Conflicts, and Evidence "
        "Explorer arrive in step 5."
    )


if __name__ == "__main__":
    main()
