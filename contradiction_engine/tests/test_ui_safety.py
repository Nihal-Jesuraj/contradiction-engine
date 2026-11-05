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


def test_light_and_dark_palettes_differ() -> None:
    """The stylesheet follows the active theme and defaults to dark."""
    assert "--hud-bg: #0E1117" in build_css("dark")
    assert "--hud-bg: #F6F8FA" in build_css("light")
    assert build_css(None) == build_css("dark")


def test_config_keeps_theme_switch_available() -> None:
    """viewer mode keeps Settings; light and dark themes are both defined."""
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    assert config["client"]["toolbarMode"] == "viewer"
    assert {"light", "dark"} <= set(config["theme"])
