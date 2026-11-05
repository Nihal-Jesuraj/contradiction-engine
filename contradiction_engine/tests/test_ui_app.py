"""AppTest coverage for the Streamlit presentation layer."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

PAGES = ("Generate / Upload", "Analyze & Conflicts", "Evidence Explorer")
APP_PATH = Path(__file__).resolve().parents[2] / "app.py"


def _app() -> AppTest:
    """Return a fresh app instance with a generous test timeout."""
    return AppTest.from_file(str(APP_PATH), default_timeout=90).run()


def _go(app: AppTest, page: str) -> AppTest:
    """Select a page in the sidebar and rerun the app."""
    app.radio[0].set_value(page)
    return app.run()


def test_all_pages_render_without_exceptions() -> None:
    """Every page renders with no exceptions and no case loaded."""
    app = _app()
    assert not app.exception
    for page in PAGES:
        app = _go(app, page)
        assert not app.exception


def test_generate_then_analyze_then_explore() -> None:
    """The full generate, analyze, and explore journey stays healthy."""
    app = _app()
    demo = next(button for button in app.button if button.label == "Load demo case")
    demo.click().run()
    assert not app.exception

    app = _go(app, "Analyze & Conflicts")
    analyze = next(button for button in app.button if button.label == "ANALYZE")
    analyze.click().run()
    assert not app.exception

    app = _go(app, "Evidence Explorer")
    assert not app.exception
    assert len(app.dataframe) >= 1


def test_readable_conflict_labels_are_used() -> None:
    """Sliders use readable conflict names instead of snake_case kinds."""
    labels = {slider.label for slider in _app().slider}
    assert "Impossible-travel conflicts" in labels
    assert "Claimed-place conflicts" in labels
