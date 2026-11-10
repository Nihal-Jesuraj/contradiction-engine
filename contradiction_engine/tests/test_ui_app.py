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


def test_not_analysed_before_analyze() -> None:
    """The analyze page shows only the prompt until ANALYZE is pressed."""
    app = _app()
    demo = next(button for button in app.button if button.label == "Load demo case")
    demo.click().run()
    app = _go(app, "Analyze & Conflicts")
    assert [info.value for info in app.info] == ["Not analysed yet. Press ANALYZE."]
    assert not app.metric
    assert not app.tabs


def test_demo_includes_claimed_place_conflict() -> None:
    """The one-click demo exercises the claimed-place detector too."""
    app = _app()
    demo = next(button for button in app.button if button.label == "Load demo case")
    demo.click().run()
    app = _go(app, "Analyze & Conflicts")
    next(button for button in app.button if button.label == "ANALYZE").click().run()
    labels = [tab.label for tab in app.tabs]
    assert any(label.startswith("Claimed place vs sighting") for label in labels)
    assert not app.exception


def test_new_case_clears_explorer_filters() -> None:
    """Loading another case does not keep stale entity selections."""
    app = _app()
    demo = next(button for button in app.button if button.label == "Load demo case")
    demo.click().run()
    app = _go(app, "Evidence Explorer")
    person = next(box for box in app.selectbox if box.label == "Person")
    person.set_value(person.options[1]).run()
    assert person.value != "All"

    app = _go(app, "Generate / Upload")
    demo = next(button for button in app.button if button.label == "Load demo case")
    demo.click().run()
    app = _go(app, "Evidence Explorer")
    person = next(box for box in app.selectbox if box.label == "Person")
    assert person.value == "All"
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
    labels = {metric.label for metric in app.metric}
    assert {"Records", "Conflicts", "Highest severity", "Runtime"} <= labels
    assert app.tabs

    app = _go(app, "Evidence Explorer")
    assert not app.exception
    assert len(app.dataframe) >= 1


def test_readable_conflict_labels_are_used() -> None:
    """Sliders use readable conflict names instead of snake_case kinds."""
    labels = {slider.label for slider in _app().slider}
    assert "Impossible-travel conflicts" in labels
    assert "Claimed-place conflicts" in labels


def test_explorer_has_three_tabs() -> None:
    """The explorer groups its views into Records, Relationships, Diagnostics."""
    app = _app()
    demo = next(button for button in app.button if button.label == "Load demo case")
    demo.click().run()
    app = _go(app, "Evidence Explorer")
    labels = [tab.label for tab in app.tabs]
    assert {"Records", "Relationships", "Diagnostics"} <= set(labels)
    assert not app.exception


def test_status_tiles_appear_after_analyze() -> None:
    """The STATUS grid shows only once ANALYZE has run."""
    app = _app()
    demo = next(button for button in app.button if button.label == "Load demo case")
    demo.click().run()
    app = _go(app, "Analyze & Conflicts")
    assert "Status" not in [caption.value for caption in app.caption]
    next(button for button in app.button if button.label == "ANALYZE").click().run()
    assert "Status" in [caption.value for caption in app.caption]
    assert not app.exception


def test_road_graph_is_built_once_per_case() -> None:
    """Pages reuse one cached road graph instead of rebuilding it."""
    app = _app()
    demo = next(button for button in app.button if button.label == "Load demo case")
    demo.click().run()
    app = _go(app, "Analyze & Conflicts")
    next(button for button in app.button if button.label == "ANALYZE").click().run()
    first = app.session_state["graph_cache"][1]
    app = _go(app, "Evidence Explorer")
    assert app.session_state["graph_cache"][1] is first
    assert not app.exception

