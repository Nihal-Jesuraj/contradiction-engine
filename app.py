"""Contradiction Engine Streamlit UI.

Presentation code only. Detection, parsing, and scoring live in the
``contradiction_engine`` package, and each page lives in ``ui``. Run from the
repository root::

    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from ui.theme import configure_page
from ui.widgets import ensure_state, render_app_header, render_sidebar
from ui.generate_page import render_generate_page
from ui.analyze_page import render_analyze_page
from ui.explorer_page import render_explorer_page

ROUTES = {
    "Generate / Upload": render_generate_page,
    "Analyze & Conflicts": render_analyze_page,
    "Evidence Explorer": render_explorer_page,
}


def main() -> None:
    """Configure the page and route to the selected page."""
    configure_page()
    ensure_state()
    render_app_header()
    page = render_sidebar()
    ROUTES[page]()


if __name__ == "__main__":
    main()
