# PLAN.md — ChronoClash → Contradiction Engine

## 1. Goal

Rebuild this repository as **Contradiction Engine**, a small, fully explainable
15-mark DSA project. The user generates or uploads a fictional investigation,
presses ANALYZE, and hand-written algorithms discover contradictions. Each result
shows the conflicting records, the broken rule, the numbers, and a plain-English
explanation. Ground truth is only used afterwards for scoring. The UI states this
is an investigative-support prototype, not a guilt or lie detector.

## 2. Layout and imports

`app.py` sits at the repository root, and all code lives in the
`contradiction_engine/` package. No `sys.path` manipulation is used anywhere.

```text
app.py                   # repo root; Streamlit UI only, target < 300 lines
requirements.txt
pyproject.toml
contradiction_engine/
  __init__.py
  models.py              # Evidence, Conflict, Case, GroundTruth, CaseIndex, scoring
  generator.py           # seeded clean case + planted truth
  loader.py              # CSV/JSON parsing + validation
  algorithms/
    __init__.py
    hash_table.py        # own chaining hash table, FNV-1a, resize at 0.75
    sorting.py           # stable merge sort + lower/upper bound
    min_heap.py          # binary min-heap
    graph.py             # weighted undirected graph + Dijkstra
    topo.py              # DFS colours: cycle detection + DFS postorder topo sort
    trie.py              # optional, last
  detectors/
    __init__.py          # run_all_detectors + dedupe + merge-sort ordering
    device_state.py
    location.py
    chronology.py
    claims.py
  tests/
    test_hash_table.py test_sorting.py test_min_heap.py test_graph.py
    test_topo.py test_trie.py test_loader.py test_generator.py
    test_device_state.py test_location.py test_chronology.py test_claims.py
    test_end_to_end.py test_no_forbidden_shortcuts.py
  README.md
  CHANGELOG.md
```

Run from the repository root:

```bash
streamlit run app.py
```

Absolute imports (`from contradiction_engine.models import ...`) work because
`app.py` is executed with the repository root on `sys.path`.

Root `requirements.txt`: `streamlit`, `pandas`, `pytest` only.
Root `pyproject.toml`: drop FastAPI/Pydantic/Plotly/requests; pytest points at
`contradiction_engine/tests`.

## 3. Reuse from ChronoClash

| Old | New use |
| --- | --- |
| `core/normalize.py::parse_timestamp` | simplified `loader.py` ISO-8601 → aware UTC |
| `core/detectors.py::haversine_m` | `models.py`, only to weigh existing road edges |
| `core/generator.py` seeded generation + planted truth | `generator.py` |
| `core/schema.py` dataclass style | `models.py` (rules, confidence, ranking removed) |
| `backend/app/io.py` CSV/JSON validation ideas | `loader.py` |
| detector explanation style | all detectors, rewritten with real numbers |
| README complexity/viva structure | new `README.md` |

Not reused: AVL interval trees, event index, difference-constraint graph,
Bellman–Ford, Floyd–Warshall, incremental reachability, clock skew, gap detector,
ranking heap, BFS explanation, benchmark harness, FastAPI, Pydantic, React/HUD
assets, Plotly, HTTP client.

## 4. Delete at the end (only after green tests)

First tag the current state: `git tag chronoclash-v1`.

Then make a **separate commit** that deletes `core/`, `backend/`, `hud/`, old
`tests/`, `docs/`, `.streamlit/`, old root `README.md`, stale caches and benchmark
data. Keep `.git/`, `.venv/`, `.gitignore`. The deletion commit contains no
functional changes, so the tag is a clean restore point.

## 5. Domain model

`Evidence` (frozen dataclass): `id`, `timestamp`, `record_type` in
`state|activity|sighting|message|login|claim`, plus `person`, `device`, `place`,
`state`, `action`, `account`, `depends_on`, `claim`, `end_timestamp`, `text`.

Per-type validation lives in `loader.py`:

| type | required |
| --- | --- |
| state | device, state in ON/OFF/SLEEP |
| activity | device, action |
| sighting | person, place |
| message | person, optional depends_on |
| login | person, account |
| claim | person, account, claim, end_timestamp |

`Conflict` (frozen): `kind`, `record_ids: tuple[str, ...]`, `rule_text`,
`numbers: dict`, `explanation`, `severity`, plus a `signature` property.
Kinds: `device_state`, `location`, `message_order`, `message_cycle`, `claim`.

`Case`: name, records, ground_truth. Detectors receive only `records`.
`score_conflicts()` returns precision/recall/F1; a truth entry matches a detected
conflict of the same kind whose IDs contain all truth IDs. Empty truth reports
"not available".

`CaseIndex`: HashTable indexes by person/device/account, merge-sorted records,
`in_range` via bounds, optional trie keyword search. Keeps algorithms out of app.py.

### 5.1 Place map

The default road network is **sparse**: 10 fictional places, 16 undirected
roads, connected but far from complete. Because it is sparse, the Dijkstra
shortest route between two places can differ from the direct edge, which makes
the algorithm worth demonstrating. At least one pair must have a direct road
that is slower than a two-hop route. Haversine-derived weights obey the triangle
inequality, so that pair is given explicit minutes (a per-edge road factor). A
test asserts that Dijkstra returns the two-hop path instead of the direct edge.

Coordinates are trusted constants used only to compute weights for roads that
actually exist:

```text
weight_minutes = max(2, round(haversine_km / ASSUMED_SPEED_KMH * 60))
```

There are no coordinates on evidence records; uploaded `place` values must name
a known place.

An optional `places.json` upload can replace the default network:

```json
{"places": {"HQ": [51.50, -0.12], "Dock": [51.51, -0.10]},
 "edges": [["HQ", "Dock", 9], ["HQ", "Lab", 14]]}
```

If an edge has minutes, that value is used; otherwise it is derived from the
coordinates. The loader validates that the graph is connected, has no
self-loops, has finite non-negative weights, and that every edge endpoint is a
declared place.

**Documented deviation:** the brief mentions lat/lon validation. The new location
detector uses the named-place graph instead of per-record coordinates, eliminating
invalid-coordinate bugs. Place names and the optional graph are fully validated.
No numerical observation is discarded; gaps are computed from timestamps.

## 6. Algorithms

- **hash_table.py** — separate chaining, deterministic FNV-1a 64-bit hash, put/get/
  contains/remove/items/keys/values, duplicate update, resize at load factor 0.75.
  Average O(1), worst O(n), space O(n).
- **sorting.py** — stable merge sort, O(n log n) time/O(n) space; iterative lower
  and upper bound, O(log n)/O(1). No `sorted()` or `.sort()`.
- **min_heap.py** — binary min-heap, push/pop/peek, sift up/down. Dijkstra uses
  lazy deletion rather than decrease-key (simpler to explain).
- **graph.py** — adjacency list, undirected edges, `dijkstra()` returns distances
  and predecessors, `shortest_path()` for explanations. O((V+E) log V).
- **topo.py** — explicit dependency graph; WHITE/GRAY/BLACK DFS `find_cycle()`;
  `topological_order()` = reversed DFS postorder (one traversal does both jobs;
  choice commented). O(V+E).
- **trie.py** — optional ~60 lines, insert/contains/starts_with/words_with_prefix.

Guard test scans these modules with `ast` for forbidden imports and built-in sorts.

## 7. Detectors

1. **device_state** — HashTable grouping by device; merge sort state records;
   interval `[state_i, state_{i+1})`; `upper_bound - 1` locates the state active at
   each activity.
   - **OFF** during local activity ⇒ conflict, severity 0.9: a powered-off device
     cannot log a local action.
   - **SLEEP** during local activity ⇒ conflict, lower severity 0.55, with the
     explanation "sleep may still permit background or wake-on-LAN activity; treat
     as suspicious, not impossible."
   - Same-instant OFF transition conflicts; same-instant ON does not.
   - No preceding state ⇒ no invented interval.
   O(n log n) time, O(n) space.
2. **location** — HashTable grouping by person; merge sort sightings; cached
   Dijkstra per source place; consecutive A→B with elapsed < required ⇒ conflict.
   Zero-duration distant sightings are flagged (gap 0 < required); equal gap and
   travel time is allowed; same place is skipped.
   Soundness: checking only consecutive sightings is sufficient because
   shortest-path travel times obey the triangle inequality, so any longer jump
   that fits in its time budget implies the intermediate consecutive legs also fit.
   O(n log n + V·(V+E) log V).
3. **chronology** — parent→child dependency graph; DFS cycle ⇒ `message_cycle`;
   otherwise topo order and any child earlier than parent ⇒ `message_order`.
   Equal timestamps allowed. Missing parents rejected by the loader. O(V+E).
4. **claims** — HashTable grouping logins by account; merge sort; bounds give logins
   inside `[start, end]` (closed); any match ⇒ `claim` conflict. O(n log n + c log n).

`run_all_detectors(records)` runs all four, dedupes by kind+IDs, and orders with
our merge sort. It never accepts ground truth.

## 8. Generator

`random.Random(seed)` builds a clean consistent base first on the default sparse
place graph: people, device ON/activity/OFF/SLEEP cycles, graph-following
sighting walks with positive dwell slack, parent-before-child message chains,
logins, and denied-access claims that contain no login. Then it plants N
contradictions per detector by mutating isolated records and records their IDs as
truth:

- device: move an activity into an OFF interval;
- location: move the last sighting to a far place without changing time;
- message: timestamp a child before its parent;
- claim: widen a claim over an existing login.

Mutating dedicated planted entities / final records prevents accidental extra
conflicts, so generated cases reach precision and recall 1.0 by construction.
Returns `GeneratedCase(case, truth)`; writes no files. UI offers `case.csv`,
`ground_truth.json`, and `places.json` downloads. Missing upload IDs become
`UPL-<sha1(canonical row + row number)[:10]>`.

## 9. Loader

Accepts `.csv` and `.json` (list, or object with name/records/ground_truth), plus
optional separate `ground_truth.json` and `places.json` uploads. Validates: record
type, parseable timestamps, claim end after start, known place, valid state,
required fields, existing message parent, supported claim, finite numbers, unique
IDs. Missing IDs are generated; duplicate IDs rejected. Any invalid row rejects the
whole upload; the UI shows the first 5 rows with reasons and no case is replaced.
Returns `(case, errors)` and mutates nothing. A bad `places.json` is rejected for
the same reasons and leaves the default graph in place.

## 10. UI (`app.py`, repo root)

Sidebar radio: **Generate / Upload**, **Analyze & Conflicts**, **Evidence
Explorer**, plus the responsible-use banner.

- Generate form: seed, people, per-detector contradiction counts; stores case and
  truth, clears conflicts; shows type counts and download buttons.
- Upload form: CSV/JSON, optional truth JSON, optional places JSON; errors shown
  without replacing state.
- Analyze: ANALYZE calls `run_all_detectors`; metrics include records, conflicts
  per kind, precision/recall/F1 when truth exists; selectable conflict detail with
  side-by-side records, rule, numbers, explanation; empty state explains that
  consistency is not truth; one "How this works" expander per detector with its
  algorithm and complexity.
- Explorer: person/device/account filters, time range via bounds, optional trie
  keyword search, result table and a simple pandas bar chart of records per day.
  No Plotly.

## 11. Tests

Algorithm tests cover empty, single, duplicates, stability, random lists compared
to Python `sorted` (tests only), bounds, heap order, a known sparse Dijkstra graph
where the shortest route is not the direct edge (asserted explicitly), unreachable
nodes, DAG/cycle/
self-loop topo cases, collisions and resize. Loader tests cover valid CSV/JSON,
deterministic missing IDs, duplicate IDs, every validation failure, first-5
ordering, no partial case, a valid custom `places.json`, and rejection of a
disconnected or malformed graph. Generator tests cover determinism, different
seeds, zero conflicts when clean, requested planted counts, truth IDs existing.
Detector tests cover clean vs planted, boundary cases (zero-duration travel,
equal travel time, ON/OFF transition instants, SLEEP lower severity, closed claim
interval), and duplicate records. End-to-end: seed 42 generate → analyze →
recall 1.0, precision 1.0; clean case → zero conflicts; valid and invalid upload
paths. Guard test enforces no forbidden imports or built-in sorting.

## 12. README

Sections: what it is + responsible use; quick start (`streamlit run app.py`);
the four detectors in plain English; CSV/JSON/places schema; ground-truth format
and scoring; architecture; complexity table; viva notes; limitations.

Viva notes must include:

- why an own HashTable instead of `dict` for grouping;
- why merge sort and why stability matters;
- why binary search over state intervals;
- why min-heap + Dijkstra, and why the graph is deliberately sparse;
- why DFS handles both cycle detection and topological order;
- why zero-duration sightings are still flagged;
- why the consecutive-sighting check is sound: shortest-path times satisfy the
  triangle inequality, so checking adjacent sightings covers longer jumps;
- why ground truth is never passed to detectors.

Limitations must include: fictional map, synthetic evaluation, in-memory app,
investigative support only, and that precision/recall of 1.0 holds **for generated
data by construction**, not for arbitrary real evidence.

## 13. Order of work + checkpoints

1. PLAN.md, CHANGELOG.md, package scaffold, root `app.py` placeholder, trimmed
   requirements/pyproject → commit.
2. algorithms + tests green → commit.
3. models, generator, loader + tests → commit.
4. detectors 1–3 + tests → commit.
5. app.py, py_compile and manual Streamlit smoke test → commit.
6. detector 4, optional trie, README → commit.
7. `git tag chronoclash-v1`; separate commit deleting old code; full pytest.

## 14. Acceptance

- `streamlit run app.py` works from the repo root without a backend.
- Generate → analyze → every planted conflict is shown with records/rule/numbers/
  explanation; clean case yields none.
- Invalid uploads show the first 5 reasons and never leave partial state.
- Optional `places.json` replaces the graph only when valid.
- SLEEP produces a lower-severity, clearly explained conflict.
- All tests pass; no forbidden imports or built-in sorting in algorithm code.
- README documents run steps, schema, ground truth, complexity, viva notes,
  limitations.

## 15. Risks and simplifications

| Risk | Decision |
| --- | --- |
| lat/lon records vs named-place graph | fixed sparse 10-place graph; document deviation |
| sparse graph and Dijkstra | 16 edges; test a route shorter than the direct edge |
| topo sort choice | DFS cycle detection + reversed postorder, one traversal |
| "write ground truth to file" | generator returns it; UI downloads it |
| optional trie | last; omit if it harms clarity |
| 300-line app | query logic moves to `CaseIndex` |
| old + new code coexist | tag `chronoclash-v1`, delete in a separate commit |
