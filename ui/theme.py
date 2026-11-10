"""Fixed HUD theme for the Contradiction Engine Streamlit UI.

The stylesheet is one constant block. It never interpolates case data, uploaded
text, or user input; all dynamic values are rendered with Streamlit widgets.
"""

from __future__ import annotations

import streamlit as st

PALETTE: dict[str, str] = {
    "bg": "#0C0B0A",
    "panel": "#121110",
    "card": "#181614",
    "card_soft": "#141311",
    "text": "#F1EBE0",
    "muted": "#A39A8B",
    "line": "rgba(241, 235, 224, 0.12)",
    "line_strong": "rgba(241, 235, 224, 0.22)",
    "accent": "#D9B26F",
    "accent_hover": "#E9C98A",
    "on_accent": "#1A1408",
    "high": "#FB7185",
    "medium": "#FB923C",
    "low": "#9C9484",
    "clear": "#34D399",
    "route": "#D9B26F",
    "grid": "#6B6254",
    "edge": "#4A4338",
    "node": "#181614",
    "ring_1": "#F2EBDD",
    "ring_2": "#C98B5B",
    "ring_3": "#8C8378",
    "ring_far": "#3F3A33",
    "sidebar_tint": "rgba(12, 11, 10, 0.62)",
}


TITLE_FONT = '"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif'


def rgba(name: str, alpha: float) -> str:
    """Return a palette colour as ``rgba(...)`` so tints follow the palette."""
    value = PALETTE[name].lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha})"


# (tint alpha, border alpha) for the STATUS tiles, keyed by palette colour.
_TILE_LEVELS: dict[str, tuple[float, float]] = {
    "high": (0.12, 0.34),
    "medium": (0.10, 0.32),
    "low": (0.09, 0.30),
    "clear": (0.09, 0.30),
}
TILE_CSS = "\n".join(
    f"""[class*="st-key-tile_{level}"] {{
  --tile: var(--hud-{level});
  --tile-tint: {rgba(level, tint)};
  border-color: {rgba(level, border)};
}}"""
    for level, (tint, border) in _TILE_LEVELS.items()
)
RING_CSS = "\n".join(
    f".hud-ring-{name.removeprefix('ring_')} {{ border-color: var(--hud-{name.replace('_', '-')}); }}"
    for name in ("ring_1", "ring_2", "ring_3", "ring_far")
)

ROOT_CSS = ":root {\n" + "\n".join(
    f"  --hud-{name.replace('_', '-')}: {value};"
    for name, value in PALETTE.items()
) + "\n}"

THEME_CSS = f"""
<style>
{ROOT_CSS}
.stApp {{
  background:
    radial-gradient(1100px 480px at 88% -12%, {rgba('accent', 0.09)},
                    transparent 62%),
    var(--hud-bg);
  color: var(--hud-text);
}}
[data-testid="stSidebar"] {{
  background: var(--hud-panel);
  border-right: 1px solid var(--hud-line);
}}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--hud-sidebar-tint);
  box-shadow: none;
}}
h1, h2, h3 {{
  letter-spacing: 0.005em;
  color: var(--hud-text);
}}
h1 {{
  font-family: {TITLE_FONT};
  font-size: 1.75rem;
  font-weight: 500;
  margin-bottom: 0.15rem;
}}
h2 {{
  font-size: 1.2rem;
  font-weight: 600;
}}
h3 {{
  font-size: 1rem;
  font-weight: 600;
}}
[data-testid="stMarkdownContainer"] h1 {{
  font-family: {TITLE_FONT};
  font-size: 1.75rem;
  font-weight: 500;
  letter-spacing: 0.005em;
}}
[data-testid="stMarkdownContainer"] h2 {{
  font-size: 1.2rem;
  font-weight: 600;
}}
[data-testid="stMarkdownContainer"] h3 {{
  font-size: 1rem;
  font-weight: 600;
}}
p, li, label, .stMarkdown {{
  color: var(--hud-text);
}}
[data-testid="stCaptionContainer"] p {{
  font-size: 0.76rem;
  letter-spacing: 0.015em;
  color: var(--hud-muted);
}}
[data-testid="stVerticalBlockBorderWrapper"] {{
  border: 1px solid var(--hud-line);
  border-radius: 12px;
  background: var(--hud-card);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.03),
              0 12px 28px rgba(0, 0, 0, 0.22);
  padding: 0.9rem 1rem;
}}
[data-testid="stMetric"],
[data-testid="metric-container"] {{
  background: var(--hud-card);
  border: 1px solid var(--hud-line);
  border-radius: 12px;
  padding: 0.7rem 0.85rem;
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.03);
}}
[data-testid="stMetricValue"] {{
  font-size: 1.85rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}}
[data-testid="stMetricLabel"] p {{
  letter-spacing: 0.01em;
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--hud-muted);
}}
[data-testid="stMetricDelta"] {{
  font-variant-numeric: tabular-nums;
}}
[data-testid="stDataFrame"], [data-testid="stTable"] {{
  font-variant-numeric: tabular-nums;
}}
[data-testid="stExpander"] details {{
  border: 1px solid var(--hud-line);
  border-radius: 10px;
  background: var(--hud-card-soft);
}}
[data-testid="stExpander"] summary {{
  letter-spacing: 0.01em;
  font-weight: 600;
}}
[data-testid="stGraphVizChart"] {{
  background: var(--hud-card-soft);
  border: 1px solid var(--hud-line);
  border-radius: 12px;
  padding: 0.45rem;
}}
[data-testid="stGraphVizChart"] svg {{
  display: block;
  margin: 0 auto;
  max-width: 100%;
  max-height: 520px;
}}
.stTabs [data-baseweb="tab-list"] {{
  gap: 0.25rem;
  border-bottom: 1px solid var(--hud-line);
}}
.stTabs [data-baseweb="tab"] {{
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  padding: 0.42rem 0.8rem;
  font-size: 0.84rem;
  letter-spacing: 0.005em;
  color: var(--hud-muted);
}}
.stTabs [data-baseweb="tab"]:hover {{
  color: var(--hud-text);
  background: var(--hud-card-soft);
}}
.stTabs [aria-selected="true"] {{
  border-color: var(--hud-line);
  background: var(--hud-card);
  color: var(--hud-text);
  box-shadow: inset 0 -2px 0 var(--hud-accent);
}}
.stButton > button {{
  border: 1px solid var(--hud-line-strong);
  border-radius: 8px;
  font-size: 0.84rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  background: var(--hud-card);
  color: var(--hud-text);
}}
.stButton > button:hover {{
  border-color: var(--hud-accent);
  color: var(--hud-accent-hover);
}}
.stButton > button[kind="primary"],
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"] {{
  background: var(--hud-accent);
  border: 1px solid var(--hud-accent);
  border-radius: 8px;
  color: var(--hud-on-accent);
  font-weight: 700;
  letter-spacing: 0.04em;
}}
[data-testid="stBaseButton-primary"] p,
[data-testid="stBaseButton-primaryFormSubmit"] p {{
  color: var(--hud-on-accent);
}}
.stButton > button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  background: var(--hud-accent-hover);
  border-color: var(--hud-accent-hover);
  color: var(--hud-on-accent);
}}
.stApp :focus-visible,
.stApp div[data-baseweb="select"]:focus-within,
.stApp div[data-baseweb="input"]:focus-within,
.stApp div[data-baseweb="textarea"]:focus-within {{
  outline: 2px solid var(--hud-accent);
  outline-offset: 2px;
}}
[data-testid="stForm"] {{
  border: 1px solid var(--hud-line);
  border-radius: 12px;
  padding: 0.7rem 0.95rem;
}}
hr {{
  border-color: var(--hud-line);
}}
[data-testid="stAlert"] {{
  border-radius: 10px;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{
  background: {rgba('medium', 0.09)};
  border: 1px solid {rgba('medium', 0.30)};
  border-radius: 10px;
  color: var(--hud-text);
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) p,
[data-testid="stAlertContentWarning"] {{
  color: var(--hud-text);
}}
[data-testid="stToast"] {{
  border: 1px solid var(--hud-line);
}}
[data-testid="stProgress"] > div > div > div > div {{
  background: var(--hud-accent);
}}
.hud-meter {{
  margin: 0.15rem 0 0.9rem;
}}
.hud-meter-label {{
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  color: var(--hud-text);
  margin-bottom: 0.3rem;
}}
.hud-meter-label span:last-child {{
  color: var(--hud-muted);
  font-variant-numeric: tabular-nums;
}}
.hud-meter-track {{
  position: relative;
  height: 8px;
  border-radius: 999px;
  background: var(--hud-card-soft);
  border: 1px solid var(--hud-line);
}}
.hud-meter-fill {{
  height: 100%;
  border-radius: 999px;
  background: var(--hud-accent);
}}
.hud-meter-mark {{
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 2px;
  background: var(--hud-text);
  opacity: 0.8;
}}
.hud-legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1rem;
  font-size: 0.76rem;
  color: var(--hud-muted);
  margin: 0.1rem 0 0.4rem;
}}
.hud-legend span {{
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}}
.hud-ring {{
  display: inline-block;
  width: 0.8rem;
  height: 0.8rem;
  border-radius: 50%;
  border: 2px solid var(--hud-line-strong);
  background: var(--hud-node);
}}
.hud-ring-0 {{ border-color: var(--hud-accent); }}
{RING_CSS}
code, kbd, samp {{
  font-family: "SFMono-Regular", "JetBrains Mono", Menlo, monospace;
  font-size: 0.86em;
}}
.block-container {{
  padding-top: 1.4rem;
  padding-bottom: 2.5rem;
}}
div[data-testid="stVerticalBlock"] {{
  gap: 0.55rem;
}}
[class*="st-key-tile_"] {{
  border: 1px solid var(--hud-line);
  border-left: 3px solid var(--tile, var(--hud-line));
  border-radius: 10px;
  padding: 0.55rem 0.75rem;
  background:
    linear-gradient(180deg, var(--tile-tint, transparent), transparent 72%),
    var(--hud-card);
}}
{TILE_CSS}
</style>
"""

PALETTES = {"dark": ROOT_CSS}


def build_css() -> str:
    """Return the fixed stylesheet with the dark palette inserted."""
    return THEME_CSS


def configure_page() -> None:
    """Set page configuration and inject the fixed HUD stylesheet."""
    st.set_page_config(
        page_title="Contradiction Engine",
        page_icon="🔎",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(build_css(), unsafe_allow_html=True)
