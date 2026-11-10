"""Contradiction Engine: explainable temporal contradiction detection.

The package is split into three layers:

- ``algorithms``: hand-written data structures and graph routines.
- ``detectors``: rules that turn evidence records into conflicts.
- ``models``/``generator``/``loader``: shared data contracts and I/O.

Nothing in this package imports Streamlit, so every part can be tested with
plain pytest.
"""

__version__ = "0.1.0"
