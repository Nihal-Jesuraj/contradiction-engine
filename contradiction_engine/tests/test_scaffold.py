"""Scaffold smoke tests for step 1."""

from __future__ import annotations

import contradiction_engine
from contradiction_engine import algorithms, detectors


def test_package_version_is_set() -> None:
    """The package exposes a version string."""
    assert contradiction_engine.__version__ == "0.1.0"


def test_subpackages_import() -> None:
    """Both scaffold subpackages import without Streamlit installed."""
    assert algorithms.__name__ == "contradiction_engine.algorithms"
    assert detectors.__name__ == "contradiction_engine.detectors"
