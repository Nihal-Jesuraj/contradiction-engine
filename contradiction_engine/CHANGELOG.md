# Changelog

All checkpoints from the ChronoClash refactor are recorded here.

## 0.1.0 — 2026-11-05

### Added

- Step 1 scaffold: `contradiction_engine/` package with `algorithms/` and
  `detectors/` subpackages, root `app.py` placeholder, `PLAN.md`, and this
  changelog.
- Root `requirements.txt` and `pyproject.toml` reduced to Streamlit, pandas, and
  pytest. FastAPI, Pydantic, Plotly, requests, uvicorn, and httpx are no longer
  dependencies of the new project.

### Changed

- `app.py` now lives at the repository root and uses absolute imports, so no
  `sys.path` manipulation is needed.
- The place graph will be a sparse 10-node network with 14–16 edges, including
  at least one direct road that is slower than a two-hop route.

### Removed

- Nothing yet. Old ChronoClash code is deleted in the final step, after the new
  test suite is green and `chronoclash-v1` is tagged.
