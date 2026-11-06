"""Fixed HUD theme for the Contradiction Engine Streamlit UI.

The stylesheet is one constant block. It never interpolates case data, uploaded
text, or user input; all dynamic values are rendered with Streamlit widgets.
"""

from __future__ import annotations

import streamlit as st

THEME_CSS = """
<style>
.stApp {
  background: var(--hud-bg);
  color: var(--hud-text);
}
[data-testid="stSidebar"] {
  background: var(--hud-panel);
  border-right: 1px solid var(--hud-line);
}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--hud-sidebar-tint);
}
h1, h2, h3 {
  letter-spacing: 0.01em;
}
h1 {
  font-size: 1.55rem;
  font-weight: 600;
  margin-bottom: 0.15rem;
}
h2 {
  font-size: 1.15rem;
}
h3 {
  font-size: 1rem;
}
p, li, label, .stMarkdown {
  color: var(--hud-text);
}
[data-testid="stCaptionContainer"] p {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.68rem;
  color: var(--hud-muted);
}
[data-testid="stVerticalBlockBorderWrapper"] {
  border: 1px solid var(--hud-line);
  border-radius: 8px;
  background: var(--hud-card);
  padding: 0.85rem 0.95rem;
}
[data-testid="stMetricValue"] {
  font-size: 1.9rem;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}
[data-testid="stMetricLabel"] p {
  text-transform: uppercase;
  letter-spacing: 0.09em;
  font-size: 0.65rem;
  color: var(--hud-muted);
}
[data-testid="stMetricDelta"] {
  font-variant-numeric: tabular-nums;
}
[data-testid="stDataFrame"], [data-testid="stTable"] {
  font-variant-numeric: tabular-nums;
}
[data-testid="stExpander"] details {
  border: 1px solid var(--hud-line);
  border-radius: 8px;
  background: var(--hud-card-soft);
}
[data-testid="stExpander"] summary {
  letter-spacing: 0.02em;
}
.stTabs [data-baseweb="tab-list"] {
  gap: 0.3rem;
  border-bottom: 1px solid var(--hud-line);
}
.stTabs [data-baseweb="tab"] {
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 6px 6px 0 0;
  padding: 0.35rem 0.75rem;
  font-size: 0.78rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.stTabs [aria-selected="true"] {
  border-color: var(--hud-line);
  color: var(--hud-accent);
}
.stButton > button {
  border: 1px solid var(--hud-line);
  border-radius: 6px;
  font-size: 0.78rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.stButton > button[kind="primary"] {
  background: var(--hud-accent);
  border-color: var(--hud-accent);
  color: var(--hud-on-accent);
  font-weight: 700;
}
.stButton > button[kind="primary"]:hover {
  background: var(--hud-accent-hover);
  border-color: var(--hud-accent-hover);
  color: var(--hud-on-accent);
}
[data-testid="stForm"] {
  border: 1px solid var(--hud-line);
  border-radius: 8px;
  padding: 0.65rem 0.9rem;
}
hr {
  border-color: var(--hud-line);
}
[data-testid="stAlert"] {
  border-radius: 8px;
}
[data-testid="stToast"] {
  border: 1px solid var(--hud-line);
}
.block-container {
  padding-top: 1.4rem;
  padding-bottom: 2.5rem;
}
div[data-testid="stVerticalBlock"] {
  gap: 0.55rem;
}
[class*="st-key-tile_"] {
  border: 1px solid var(--hud-line);
  border-radius: 8px;
  padding: 0.5rem 0.7rem;
  background: var(--hud-card);
}
[class*="st-key-tile_high"] { border-color: #F87171; }
[class*="st-key-tile_medium"] { border-color: #FBBF24; }
[class*="st-key-tile_low"] { border-color: #8B98A9; }
[class*="st-key-tile_clear"] { border-color: #2DD4BF; }
</style>
"""


PALETTES = {
    "dark": """:root {
  --hud-bg: #0E1117; --hud-panel: #161B26; --hud-text: #E6EDF3;
  --hud-muted: #8B98A9; --hud-line: rgba(230, 237, 243, 0.12);
  --hud-accent: #2DD4BF; --hud-accent-hover: #5EEAD4; --hud-on-accent: #0E1117;
  --hud-sidebar-tint: rgba(14, 17, 23, 0.55);
  --hud-card: rgba(22, 27, 38, 0.55); --hud-card-soft: rgba(22, 27, 38, 0.45);
}""",
}


def build_css() -> str:
    """Return the fixed stylesheet with the dark palette inserted."""
    return THEME_CSS.replace("<style>", "<style>\n" + PALETTES["dark"], 1)


def configure_page() -> None:
    """Set page configuration and inject the fixed HUD stylesheet."""
    st.set_page_config(
        page_title="Contradiction Engine",
        page_icon="🔎",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(build_css(), unsafe_allow_html=True)
