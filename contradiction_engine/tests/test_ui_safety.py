"""Upload, export, theme, and config safety tests for the UI layer."""

from __future__ import annotations

import tomllib
from pathlib import Path

from contradiction_engine.models import case_to_csv
from ui.export import neutralize_cell, safe_csv
from ui.generate_page import safe_load_case
from ui.theme import build_css

HEADER = ("id,timestamp,record_type,person,device,place,state,action,account,"
          "depends_on,claim,end_timestamp,text\n")
ROOT = Path(__file__).resolve().parents[2]


def _row(text: str) -> bytes:
    return (HEADER + f"r1,2026-01-01T10:00:00Z,activity,A,D1,,,open,,,,,{text}\n").encode()


def test_oversized_field_is_rejected_not_raised() -> None:
    """A field beyond the CSV limit becomes an upload error message."""
    case, errors = safe_load_case("big.csv", _row("x" * 200000))
    assert case is None
    assert errors and "could not be read" in errors[0]


def test_formula_cells_are_neutralised_on_export() -> None:
    """Exported CSV never carries a cell that starts with a formula sign."""
    case, errors = safe_load_case("f.csv", _row('"=HYPERLINK(""http://x.test"")"'))
    assert not errors
    assert "=HYPERLINK" in case_to_csv(case)
    assert "'=HYPERLINK" in safe_csv(case_to_csv(case))
    assert neutralize_cell("hello") == "hello"
    assert neutralize_cell("@cmd") == "'@cmd"
    assert neutralize_cell(" =cmd") == "' =cmd"


def test_stylesheet_is_fixed_and_dark() -> None:
    """The stylesheet carries the dark palette and no data-driven parts."""
    css = build_css()
    from ui.theme import PALETTE

    assert f"--hud-bg: {PALETTE['bg']}" in css
    assert f"--hud-accent: {PALETTE['accent']}" in css
    assert "invert(" not in css


def test_config_hides_menu_and_keeps_dark_base() -> None:
    """The toolbar menu is hidden and the native theme is the dark one."""
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    assert config["client"]["toolbarMode"] == "minimal"
    assert config["theme"]["base"] == "dark"


def test_stylesheet_braces_balance_and_tiles_follow_the_palette() -> None:
    """Generated CSS blocks are valid and tile colours come from PALETTE."""
    from ui.theme import PALETTE, rgba

    css = build_css()
    assert "{{" not in css and "}}" not in css
    assert css.count("{") == css.count("}")
    assert f"--tile-tint: {rgba('high', 0.12)}" in css
    assert f"--hud-ring-1: {PALETTE['ring_1']}" in css
    assert "text-transform" not in css


def test_native_badge_colours_match_the_palette() -> None:
    """Streamlit's own badge colours use the same hex values as the CSS."""
    from ui.theme import PALETTE

    theme = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
    assert theme["primaryColor"] == PALETTE["accent"]
    assert theme["backgroundColor"] == PALETTE["bg"]
    assert theme["redColor"] == PALETTE["high"]
    assert theme["orangeColor"] == PALETTE["medium"]
    assert theme["greenColor"] == PALETTE["clear"]
    assert theme["grayColor"] == PALETTE["low"]


def test_clear_status_is_not_the_accent_or_the_route() -> None:
    """CLEAR, HIGH, and the route highlight never share a colour."""
    from ui.theme import PALETTE

    assert PALETTE["clear"] != PALETTE["accent"]
    assert PALETTE["route"] != PALETTE["high"]
    assert len({PALETTE[k] for k in ("high", "medium", "low", "clear")}) == 4


def test_inline_code_does_not_use_the_clear_colour() -> None:
    """Record IDs in code spans must not look like a CLEAR status."""
    from ui.theme import PALETTE

    theme = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
    assert theme["codeTextColor"] != PALETTE["clear"]


def test_numbers_table_shows_route_arrows() -> None:
    """Detector route text is shown with arrows, other values stay as-is."""
    from ui.widgets import numbers_frame

    frame = numbers_frame({"shortest_path": "A -> B -> C", "elapsed_minutes": 1.0})
    assert frame["Value"].tolist() == ["A → B → C", "1.0"]


def test_accent_and_hop_rings_are_all_distinct_from_status_colours() -> None:
    """Gold accent, severity levels, CLEAR, and hop rings never share a colour."""
    from ui.theme import PALETTE

    keys = ("accent", "high", "medium", "low", "clear",
            "ring_1", "ring_2", "ring_3", "ring_far")
    assert len({PALETTE[k] for k in keys}) == len(keys)


def test_sidebar_brand_and_card_glow_are_fixed_and_palette_driven() -> None:
    """The brand block is static markup; the card glow derives from the accent."""
    from ui.theme import PALETTE, TITLE_FONT, rgba
    from ui.widgets import BRAND_HTML

    css = build_css()
    assert "Contradiction Engine" in BRAND_HTML and "{" not in BRAND_HTML
    assert ".hud-brand-title" in css and TITLE_FONT in css
    assert f"0 18px 48px {rgba('accent', 0.06)}" in css
    assert PALETTE["accent"] == "#D9B26F"


def test_stylesheet_hides_the_github_link_and_star_badge() -> None:
    """The toolbar's GitHub link, star count and deploy actions stay hidden."""
    css = build_css()
    assert '[data-testid="stToolbarActions"]' in css
    assert '[data-testid="stToolbar"] a[href*="github.com"]' in css
    assert "display: none !important" in css
