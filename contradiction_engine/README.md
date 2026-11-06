# Contradiction Engine

**An explainable temporal contradiction detector for fictional investigations.**

You generate or upload an investigation. You press **ANALYZE**. Hand-written
data structures and graph algorithms find records that cannot all be true, and
the UI shows the conflicting records, the broken rule, the numbers, and a
plain-English explanation.

> **Responsible use.** This is an investigative-support prototype built for a
> Data Structures & Algorithms course. A conflict means the records disagree
> under the stated rules. It does **not** mean a person is guilty, lying, or
> even wrong. Real evidence is noisy, incomplete, and open to interpretation.

---

## Quick start

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open <http://127.0.0.1:8501>. There is no backend service and no Node.js step.

### Two-minute demo

1. Generate / Upload: press **Load demo case**.
2. Analyze & Conflicts: press **ANALYZE**; read the KPIs, the STATUS tiles and
   the conflict tabs (open one card to show records, rule, numbers, route).
3. Evidence Explorer: filter by person, then open Relationships and Diagnostics.
4. Download `case.csv` (formula-like cells are neutralised with a leading quote).

Run the tests from the repository root:

```bash
.venv/bin/python -m pytest -q
```

---

## The three pages

1. **Generate / Upload** — pick a seed, number of people, and how many
   contradictions of each kind to plant. Or upload a CSV/JSON case, an optional
   ground-truth JSON, and an optional `places.json`. Generated cases can be
   downloaded as `case.csv`, `ground_truth.json`, and `places.json`.
2. **Analyze & Conflicts** — press **ANALYZE**. See counts per conflict kind,
   precision/recall when truth is available, a conflicts table, and a detail
   view with the two records side by side, the rule, the numbers, and the
   explanation.
3. **Evidence Explorer** — filter by person, device, or account (hash indexes),
   by time range (binary search), and by keyword (prefix trie). A simple bar
   chart shows records per day, and two relationship views render the road map
   and the entity graph as Graphviz diagrams. A hash diagnostics panel shows
   each index's load factor and longest chain.

Each page has a **How this works** expander naming the algorithm and its
complexity.

---

## The five detectors

| Detector | Question | Algorithm | Conflict kind |
| --- | --- | --- | --- |
| Device state | Did a device record local activity or a login while OFF or SLEEP? | HashTable grouping, merge-sorted state intervals, binary search | `device_state` |
| Location | Did a person move faster than the shortest road route? | HashTable grouping, merge sort, Dijkstra with a min-heap, cached per source | `location` |
| Message chronology | Is a reply timestamped before its parent, or do dependencies form a cycle? | Directed dependency graph, colouring DFS, topological order | `message_order`, `message_cycle` |
| Interview claims | Did a denied-access claim overlap a login **by that person**? | HashTable grouping by `(account, person)`, merge sort, lower/upper binary-search bounds | `claim` |
| Claimed location | Was the person seen somewhere they could not reach and still be at the claimed place at both edges of the window? | HashTable grouping by person, merge sort, binary-search window bounds, cached Dijkstra from the claimed place | `claim_location` |

An `OFF` conflict has severity `0.90`: a powered-off device cannot log a local
activity or a login that names it. A `SLEEP` conflict has severity `0.55` and
says explicitly that sleep may still permit background wake events, so it is
suspicious rather than impossible.

### Person-scoped denied-access claims

A login contradicts `did_not_access` only when it belongs to the **same
person** on the **same account**. Logins by colleagues who share an account are
not evidence against the claimant. The detector keys its hash table on
`account + "\x1f" + person` and binary-searches the closed claim window.

### Claimed-location interpretation

`claimed_at` is read as "I was at this place at **both the start and the end**
of the window `[timestamp, end_timestamp]`". It is a travel-aware
both-edges check, **not** a claim of continuous presence. A sighting elsewhere
inside the window is a conflict when the travel time from the claimed place does
not fit before the nearer edge of the window:

```text
margin = min(sighting - window_start, window_end - sighting)
conflict when margin < shortest_travel_time(claimed_place, seen_place)
```

The nearest-edge test is deliberately conservative. If the person could have
travelled between the claimed place and the sighting at that edge, the records
are compatible. One consequence is explicit: a sighting at a neighbouring place
in the middle of a long window passes, because the person could have been at the
claimed place at both edges. Under a strict "throughout the window" reading that
sighting would conflict instead. We chose the both-edges reading to avoid false
positives. Sightings outside the window, at the same place, or at an unknown
place are ignored, as is a claim at a place missing from the road map.

### Why checking only consecutive sightings is sound

The location detector compares each sighting with the next one. This is enough
because shortest-path travel times satisfy the **triangle inequality**:
`d(A, C) <= d(A, B) + d(B, C)`. If a longer jump fits inside its time budget,
each consecutive leg also fits. Any leg that does not fit is caught, so there is
no need to compare every pair of sightings.

### Zero-duration sightings

Elapsed time is computed from timestamps, not from a record duration. Two
sightings at the same instant in different places give `elapsed = 0` and
`required > 0`, so they are flagged. There is deliberately no `duration > 0`
guard that could skip them.

---

## Upload schema

Accepted files: `.csv` and `.json` (a list of records, or an object with
`name`, `records`, and optionally `ground_truth`). Timestamps are ISO-8601;
naive values are treated as UTC. Any invalid row rejects the whole upload and
the UI lists the first five reasons. The current case is never replaced.

| `record_type` | Required fields | Meaning |
| --- | --- | --- |
| `state` | `device`, `state` in `ON`/`OFF`/`SLEEP` | The state begins at `timestamp` |
| `activity` | `device`, `action` | A local device action |
| `sighting` | `person`, `place` | A person seen at a place |
| `message` | `person` | Optional `depends_on` names the parent message |
| `login` | `person`, `account` | An account login; a non-empty `device` makes it local activity |
| `claim` (`did_not_access`) | `person`, `account`, `claim`, `end_timestamp` | Denies accessing the account during the window |
| `claim` (`claimed_at`) | `person`, `place`, `claim`, `end_timestamp` | Claims the place at both edges of the window |

CSV header:

```text
id,timestamp,record_type,person,device,place,state,action,account,depends_on,claim,end_timestamp,text
```

Example rows:

```csv
ST-1,2026-03-02T08:00:00Z,state,,D1,,ON,,,,,,
ACT-1,2026-03-02T08:10:00Z,activity,,D1,,,local login,,,,,
ST-2,2026-03-02T08:20:00Z,state,,D1,,OFF,,,,,,
SGT-1,2026-03-02T09:00:00Z,sighting,P1,,Harbour,,,,,,,
MSG-1,2026-03-02T10:00:00Z,message,P1,,,,,,,,,
MSG-2,2026-03-02T10:05:00Z,message,P1,,,,,,,MSG-1,,
LOG-1,2026-03-02T11:00:00Z,login,P1,,,,,A1,,,,,
CLM-1,2026-03-02T12:00:00Z,claim,P1,,,,,A1,,did_not_access,2026-03-02T12:30:00Z,
CLM-2,2026-03-02T13:00:00Z,claim,P1,,Harbour,,,,,,claimed_at,2026-03-02T13:10:00Z,
```

Missing IDs receive a deterministic `UPL-<sha1-prefix>` value based on the row
content and row number, so two identical rows still get unique IDs. Duplicate
IDs are rejected.

### Ground truth

```json
{
  "ground_truth": [
    {"kind": "location", "record_ids": ["SGT-1", "SGT-2"], "note": "one-minute hop"}
  ]
}
```

Truth is used **only after** detection, by `score_conflicts`. Detectors receive
`case.records` and, for the two location-aware detectors, a place graph; they
never receive truth.

### Custom place map

```json
{
  "places": {"X": [51.50, -0.12], "Y": [51.51, -0.11]},
  "edges": [["X", "Y", 4], ["Y", "Z"]]
}
```

Edges with three values set travel minutes explicitly. Edges with two values
derive minutes from the coordinates with haversine. The loader rejects unknown
endpoints, self-loops, negative or non-finite weights, and disconnected
networks.

---

## The place map

The default map has **10 places and 16 undirected roads** around a fictional
city: Harbour, Station, Market, Clinic, Library, Dock, Park, Museum, Cafe, and
Warehouse.

The graph is deliberately sparse. `Clinic -> Park` has a direct road of **20
minutes**, but `Clinic -> Library -> Park` takes only **12**. Dijkstra therefore
returns a route that is not the direct edge, which makes the shortest-path step
visible and testable. Haversine is used for any edge without explicit minutes.

Evidence records carry a place **name**, never latitude/longitude. This removes
an entire class of invalid-coordinate bugs; the trusted coordinates live only
in the place table.

---

## Project layout

```text
app.py                          Streamlit UI only
contradiction_engine/
  models.py                     Evidence, Conflict, Case, scoring, CaseIndex
  generator.py                  clean case + planted truth
  loader.py                     CSV/JSON validation
  algorithms/
    hash_table.py               separate chaining, FNV-1a, resize at 0.75
    sorting.py                  stable merge sort, lower/upper bound
    min_heap.py                 binary min-heap
    graph.py                    weighted graph + Dijkstra + DOT export
    topo.py                     DFS cycle detection + topological order
    trie.py                     optional keyword prefix tree
    evidence_graph.py           BFS entity graph + DOT export
  detectors/
    device_state.py
    location.py
    chronology.py
    claims.py
    location_claims.py
  tests/
  README.md
  CHANGELOG.md
```

No algorithm code imports pandas or Streamlit. No algorithm uses `heapq`,
`bisect`, `networkx`, `sortedcontainers`, `intervaltree`, or `scipy`, and no
algorithm calls `sorted()` or `.sort()`. A test scans the source with `ast` to
enforce this.

---

## Complexity

| Operation | Time | Space |
| --- | --- | --- |
| HashTable put/get/remove | O(1) average, O(n) worst | O(n) |
| Merge sort | O(n log n) | O(n) |
| Binary search bounds | O(log n) | O(1) |
| Min-heap push/pop | O(log n) | O(n) |
| Dijkstra | O((V + E) log V) | O(V + E) |
| DFS cycle detection / topological order | O(V + E) | O(V + E) |
| BFS entity graph (`related`) | O(V + E) | O(V) |
| Device detector | O(n log n) | O(n) |
| Location detector | O(n log n + V(V+E) log V) | O(n + V + E) |
| Chronology detector | O(V + E) | O(V + E) |
| Claims detector | O(n log n + c log n + k) | O(n) |
| Claimed-location detector | O(n log n + V(V+E) log V) | O(n + V + E) |
| Case index build (hash indexes + trie + entity graph) | O(n log n + words + E) | O(n + words + E) |

---

## Viva notes

**Why our own HashTable instead of `dict` for grouping?**
The project requirement is to demonstrate hashing. Our table uses FNV-1a,
separate chaining, duplicate-key updates, and a resize at load factor 0.75. The
detectors group by device, person, and account through this class.

**Why merge sort, and why stability?**
Merge sort gives a guaranteed O(n log n) even in the worst case, and it is easy
to trace. Stability matters because records with identical timestamps keep
their input order, so a device's last state at a timestamp is deterministic.

**Why binary search over state intervals?**
States are sorted by time and each lasts until the next state. For an activity
we need the last state at or before its timestamp: `upper_bound(...) - 1`.
That is O(log s) per activity instead of scanning the timeline.

**Why a min-heap and Dijkstra?**
Road weights are non-negative travel minutes, so Dijkstra is correct. The heap
always pops the nearest unfinalized node. We use lazy deletion: push a new
entry when a shorter distance appears and skip stale entries when popped. This
avoids a decrease-key index and is simpler to explain.

**Why is the place graph sparse?**
With 16 edges over 10 places, some trips are cheaper through an intermediate
place. The built-in `Clinic -> Park` road costs 20 minutes directly but 12
through Library, so the test can assert that Dijkstra's path differs from the
direct edge. A complete graph would hide that behaviour.

**Why does one DFS handle both cycles and topological order?**
White/grey/black colouring finds a back edge (cycle) in the same traversal that
produces a finishing order. Reversing that order gives a valid topological
order. Kahn's algorithm would add an indegree table and a second pass for no
extra insight.

**Why are zero-duration sightings flagged?**
We compare timestamps, not durations. Two sightings at the same instant in
different places produce `elapsed = 0`, which is less than any positive travel
time, so the conflict is reported.

**Why is checking consecutive sightings enough?**
Shortest-path travel times obey the triangle inequality. If the total time for a
longer jump is feasible, the sum of the required consecutive legs is also
feasible; any consecutive leg that is too short is detected directly.

**Why is a closed claim window used?**
A login exactly at the claim's start or end still contradicts "did not access
during this period". `lower_bound(start)` and `upper_bound(end)` implement the
closed interval.

**Why does the claim detector key on account and person?**
An account can be shared. A login by someone else does not contradict *this*
person's denial, so grouping by `(account, person)` removes a false-positive
class. The separator `\x1f` cannot occur in CSV text, so two different pairs can
never collide into the same key.

**Why does `claimed_at` use the nearer window edge?**
The claim is read as "I was at the claimed place at both the start and the end
of the window", not "I never left it". At either edge the person must be able to
reach the claimed place from the sighting. If the sighting is near the start,
the budget is `sighting - start`; near the end it is `end - sighting`. Taking
the minimum is the strictest of the two. When the person could make the trip at
that edge, the records are compatible. Be explicit about the gap: under a true
"throughout the window" reading, any sighting elsewhere inside the window would
conflict; this rule intentionally allows a middle sighting when both edges fit.

**Why does a device login count as local activity?**
A login that names a device is processed by that device, so it is evidence the
device was operational. If the login falls inside an `OFF` interval, it is the
same contradiction as a local action. Logins without a device stay account-only
evidence and are not tied to a device state.

**Why build an entity graph instead of filtering records?**
The explorer already answers "which rows mention this entity?". The entity
graph answers the different question "what is connected to this entity, and how
far away is it?". One node per person, device, account, and place, plus links
when they co-occur in a record, is enough. Breadth-first search with a FIFO
`deque` visits each node and edge once, so `related(start, k)` is O(V + E).

**How are the Graphviz diagrams drawn?**
`WeightedGraph.to_dot` and `EvidenceGraph.to_dot` return plain DOT strings.
`st.graphviz_chart` renders DOT in the browser, so the Python `graphviz` package
is not needed. The road map labels every edge with its minutes and colours the
chosen shortest route; the entity graph uses a shape per entity kind and colours
nodes by hop distance from the selected start.

**Why is ground truth never passed to a detector?**
Otherwise the detector could simply read the answer. The generator returns
truth separately; tests and the UI score conflicts after detection.

**Why does SLEEP have lower severity than OFF?**
A powered-off device cannot produce a local action or a device login. A sleeping
device may still wake for background work, so the record is suspicious but not
impossible. The explanation says this explicitly.

---

## Tests

```bash
.venv/bin/python -m pytest -q
```

Coverage includes:

- hash collisions, duplicate keys, resize, removal;
- merge sort against Python's `sorted` on random lists (tests may sort);
- lower/upper bounds with duplicates and missing values;
- heap ordering and empty-heap errors;
- Dijkstra on the sparse map, including the slower direct road;
- DAG, cycle, and self-loop topological cases;
- every loader validation failure and first-five error ordering;
- generator determinism and planted counts;
- clean and planted cases for each detector, including a login inside an OFF
  interval;
- person-scoped claims: a colleague's login on a shared account stays clean;
- claimed-location windows: enough time, exactly enough time, too little time,
  sightings outside the window, and unknown places;
- the BFS entity graph on empty, linked, cyclic, depth-limited, and unknown-start
  inputs, including DOT highlighting;
- DOT escaping for names containing quotes and backslashes;
- hash-table load factor and longest-chain diagnostics;
- case-variant warnings for names that differ only by case;
- an uploaded `claimed_at` row reaching the detector through the loader;
- end-to-end recall **1.00**, precision **1.00**, and zero conflicts on a clean
  generated case;
- an `ast` guard against forbidden imports and built-in sorting.

---

## Acknowledgements

The person-scoped claim matching, the `claimed_at` idea, the BFS entity graph,
and the hash load-factor/longest-chain diagnostics were inspired by an external
`forensics_engine.py` file shared during the project. They were reimplemented
from scratch to fit this project's hand-written-only constraints and test
suite. The original file is not part of this repository.

---

## Limitations

- The place map and all cases are **fictional**.
- Evaluation uses synthetic data. Precision and recall of **1.00 hold for
  generated data by construction**, because plants are isolated; they are not a
  claim about arbitrary real evidence.
- State, movement, and claims are simplified models, not a forensic standard.
- Entity names are matched case-sensitively. The UI warns about uploads that
  use spellings differing only by case; normalize them before relying on matches.
- Everything is in memory; there is no database or authentication.
- The tool supports an investigator. It does not determine guilt or deceit.
