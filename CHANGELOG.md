# Changelog

All checkpoints from the Contradiction Engine rebuild are recorded here.

## Unreleased — Refined HUD

### Changed (UI only; no algorithm or detector logic touched)

- **Refined HUD palette.** One sky-blue accent (`#38BDF8`), rose/amber/slate
  severity colours, and a separate emerald for CLEAR. The fastest-route
  highlight uses the accent, so a route no longer looks like a HIGH warning.
- **One source of truth for colour.** `ui/theme.py` `PALETTE` now feeds the CSS,
  the STATUS tile tints, and the Graphviz styling in `ui/dot_theme.py`.
  `.streamlit/config.toml` carries matching native badge and code colours, and
  a test fails if the two drift apart.
- **Graphviz matches the dark app.** `ui/dot_theme.py` restyles the structure-only
  DOT from `WeightedGraph.to_dot` / `EvidenceGraph.to_dot`: transparent canvas,
  dark nodes, sans-serif labels, edge labels read `6 min`, and the route is
  drawn in the accent. Entity nodes keep a dark fill with a hop-coloured ring;
  a legend explains the ring colours and the shape of each entity kind.
- **Relationships and diagnostics.** Tabs are now *Road network · Dijkstra*,
  *Entity links · BFS* and *Hash index health*. Added a "How these views work"
  expander, a Swap button, a direct-road vs fastest-route note, and `→` in route
  captions (including the Numbers table).
- **Hash index health** is one comparison table (Keys, Buckets, Load factor,
  Longest chain) plus a load meter per index with a tick at the 0.75 resize
  threshold, and notes on FNV-1a and O(1) average / O(n) worst lookups.
- **Polish.** STATUS legend, tinted tiles with a left accent bar, bordered KPI
  cards, sentence-case metric labels, monospace record IDs, a visible focus ring
  on every interactive element, a height cap on graphs, and the Generate sliders
  split into two rows.

## 0.3.1 — 2026-11-10

### Fixed (UI and packaging)

- The demo preset now includes a claimed-place conflict, so **Load demo case**
  exercises every detector.
- Loading a new case clears case-scoped explorer, map, and entity-graph widget
  state, preventing stale options after an upload or a different generated case.
- STATUS tiles now key people and devices separately and label the entity kind,
  so a person and a device with the same name no longer merge.
- Unknown conflict kinds are grouped into one tab instead of one tab per
  conflict.
- The Evidence Explorer date filter now uses `CaseIndex.in_range` (binary
  search) rather than a linear scan.
- Formula neutralisation in exported CSV also catches cells with leading
  whitespace before `=`, `+`, `-`, `@`, tab, or CR.
- The entity-graph selector is labelled for every node kind, including places.

### Changed (packaging and docs)

- `README.md` and `CHANGELOG.md` moved to the repository root.
- `pyproject.toml` now pins the tested `streamlit==1.66.1`, matching
  `requirements.txt`.
- README page descriptions, project layout, and test coverage now match the
  current UI.
- Removed a stale `.streamlit/config.toml` comment about a sidebar theme toggle.

## 0.3.0 — 2026-11-06

### Changed (UI only)

- Analyze page: nothing but "Not analysed yet. Press ANALYZE." before a run;
  ANALYZE runs inside `st.status` with a toast; KPI row (records, conflicts,
  highest severity, detector runtime); separate ground-truth panel; conflicts
  grouped into tabs by readable kind; each conflict is a bordered card with
  side-by-side record tables, broken rule, numbers table and explanation;
  road-map route graph for travel/claimed-place conflicts; state timeline for
  "Device was off"; detector docs expander.

### Added (UI only)

- The road graph is built once per case and reused across pages; each
  conflict tab shows 15 cards at a time with a "Show more" button.
- Evidence Explorer tabs (Records / Relationships / Diagnostics), combined
  person, device, account, date-range and keyword filters, a records-per-hour
  (or per-type) chart that hides when there is nothing to compare.
- STATUS tile grid on the Analyze page; tile border colour is the worst
  severity of any conflict involving that person or device.
- Future work: the optional EVIDENCE canvas (Phase 3) is not implemented.

### Fixed (UI only)

- An oversized CSV field no longer crashes the upload; it is reported like any
  other rejected file.
- Downloaded case.csv neutralises cells that start with `=`, `+`, `-`, `@`,
  tab or CR (a leading quote is added) so a spreadsheet cannot run them.
- The toolbar menu (Settings, Deploy) is hidden; the app uses the dark theme
  only.
- Added a privacy note on upload, a near-limit file note, and a large-case
  warning above 5,000 records.

## 0.2.0 — 2026-11-06

### Added

- Person-scoped denied-access claims: `claims.detect` now groups logins by
  `(account, person)`, so a colleague's login on a shared account no longer
  contradicts the claimant.
- Claim type `claimed_at` with fields `person`, `place`, and `end_timestamp`,
  plus the `claim_location` detector. It binary-searches the claimed window and
  compares the sighting's nearer window edge with the cached Dijkstra travel
  time from the claimed place (a both-edges check, not continuous presence).
- Device-state detector now treats a login that names a device as local
  activity, so a login inside an `OFF`/`SLEEP` interval conflicts. The generator
  alternates activity and login plants to cover both forms.
- `algorithms/evidence_graph.py`: an undirected person/device/account/place
  graph with a FIFO-queue BFS `related(start, depth)` and DOT export.
- `WeightedGraph.to_dot` for the road map, with shortest-route highlighting, and
  `HashTable.longest_chain` for collision diagnostics.
- Evidence Explorer relationship views (place map and entity graph) and a hash
  index diagnostics panel showing load factor and longest chain.
- Generator support for `location_claim_conflicts` (default `0`) and an
  isolated planted `claim_location` scenario; the UI slider defaults to `1`
  so the new detector is visible.
- Tests for person-scoped claims, claimed-location boundaries, device logins,
  BFS depth and cycles, DOT escaping, case-variant warnings, hash diagnostics,
  and the uploaded `claimed_at` path.

### Changed

- `claim` rows split their requirements by type: `did_not_access` needs an
  `account`; `claimed_at` needs a `place`. Both need `person` and
  `end_timestamp`.
- `CONFLICT_KINDS` now includes `claim_location`; the Analyze page reports its
  count alongside the other kinds.
- The entity graph is built once by `CaseIndex`, not once per UI rerun.
- README documents the five detectors, the new schema rows, the both-edges
  claimed-location interpretation, project layout updates, complexity rows, and
  viva notes. It also credits the external `forensics_engine.py` that inspired
  several ideas; that file is not included in the repository.

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

- The legacy `core/`, `backend/`, `hud/`, old `tests/`, `docs/`,
  `.streamlit/`, and root README were deleted in a separate commit after the
  new suite passed. The previous state is preserved by the `chronoclash-v1` tag.
