# Changelog

All checkpoints from the ChronoClash refactor are recorded here.

## 0.1.0 — 2026-11-05

### Added

- Step 1 scaffold: `contradiction_engine/` package, `algorithms/` and
  `detectors/` subpackages, root `app.py`, `PLAN.md`, and this changelog.
- Step 2 hand-written algorithms: separate-chaining `HashTable` (FNV-1a,
  resize at 0.75), stable merge sort, lower/upper binary bounds, binary
  min-heap, weighted graph with Dijkstra, DFS cycle detection and topological
  ordering, plus algorithm tests and an `ast` guard against forbidden imports
  and built-in sorting.
- Step 3 domain model and I/O: `Evidence`, `Conflict`, `GroundTruth`, `Case`,
  precision/recall scoring, `CaseIndex`, a sparse 10-place / 16-road map, the
  seeded generator with planted truth, and the validating CSV/JSON loader.
- Step 4 detectors 1–3: device state (OFF at 0.90, SLEEP at 0.55), impossible
  travel with cached Dijkstra, and message chronology with DFS cycle detection.
- Step 5 Streamlit UI with Generate/Upload, Analyze & Conflicts, and Evidence
  Explorer pages, including the responsible-use notice and per-detector
  complexity panels.
- Step 6 detector 4 (denied-access claims), the optional prefix trie used by
  the explorer, end-to-end tests, and this README.

### Changed

- `app.py` lives at the repository root and uses absolute imports, so no
  `sys.path` manipulation is needed. Run it with `streamlit run app.py`.
- Root dependencies are now only Streamlit, pandas, and pytest. FastAPI,
  Pydantic, Plotly, requests, uvicorn, and httpx were removed.
- The default road map is deliberately sparse. The `Clinic -> Park` road costs
  20 minutes directly but 12 through Library, so Dijkstra's shortest path is
  tested against a slower direct edge.
- `places.json` can replace the built-in map. Two-value edges derive minutes
  with haversine; three-value edges set them explicitly.

### Removed

- The old ChronoClash `core/`, `backend/`, `hud/`, old `tests/`, `docs/`,
  `.streamlit/`, and root README were deleted in a separate commit after the
  new suite passed. The previous state is preserved by the `chronoclash-v1` tag.
