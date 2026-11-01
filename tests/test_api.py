"""API contract tests using a fresh bootstrapped engine per test."""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app, engine


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_state_and_entities(client: TestClient):
    state = client.get("/state")
    assert state.status_code == 200
    payload = state.json()
    assert payload["event_count"] > 100
    assert payload["entity_count"] > 5
    assert payload["conflicts_found"] >= 1
    assert len(payload["source_counts"]) == 6
    assert payload["window"]["start"] < payload["window"]["end"]

    entities = client.get("/entities").json()
    assert entities["total"] == payload["entity_count"]
    assert entities["status"]["conflicted"] >= 1
    assert all("status" in item for item in entities["entities"])


def test_conflicts_heap_and_explain(client: TestClient):
    response = client.get("/conflicts?top_k=5")
    assert response.status_code == 200
    payload = response.json()
    assert 0 < payload["returned"] <= 5
    assert payload["heap_capacity"] == 5
    scores = [item["confidence"] for item in payload["conflicts"]]
    assert scores == sorted(scores, reverse=True)
    conflict_id = payload["conflicts"][0]["id"]
    explanation = client.get(f"/conflicts/{conflict_id}/explain")
    assert explanation.status_code == 200
    body = explanation.json()
    assert body["conflict"]["id"] == conflict_id
    assert body["chain"]
    assert body["narrative"]


def test_timeline_filter_and_tooltip_payload(client: TestClient):
    timeline = client.get("/timeline?limit=50").json()
    assert timeline["events"]
    assert all("conflicts" in event for event in timeline["events"])
    first_entity = timeline["events"][0]["entity"]
    filtered = client.get(f"/timeline?entity={first_entity}&limit=1000").json()
    assert filtered["events"]
    assert all(event["entity"] == first_entity for event in filtered["events"])


def test_gaps_and_export(client: TestClient):
    gaps = client.get("/gaps?threshold_s=600&limit=10")
    assert gaps.status_code == 200
    assert gaps.json()["threshold_s"] == 600
    for gap in gaps.json()["gaps"]:
        assert gap["duration_s"] >= 600

    exported = client.get("/export?format=json")
    assert exported.status_code == 200
    body = json.loads(exported.content)
    assert body["conflicts"]
    assert "attachment" in exported.headers["content-disposition"]

    exported_csv = client.get("/export?format=csv")
    assert exported_csv.status_code == 200
    assert exported_csv.text.splitlines()[0].startswith("id,kind,severity")
    assert len(exported_csv.text.splitlines()) > 1


def test_add_event_triggers_incremental_conflict(client: TestClient):
    timeline = client.get("/timeline?limit=1").json()["events"][0]
    payload = {
        "id": "EV-TEST-INC-1",
        "timestamp": timeline["timestamp"],
        "duration_s": 120,
        "entity": timeline["entity"],
        "lat": timeline["lat"] + 0.35,
        "lon": timeline["lon"],
        "source": "gps",
        "device_id": "GPS-INC-1",
        "action": "POSITION_FIX",
        "reliability": 0.9,
    }
    response = client.post("/events", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "incremental"
    assert body["event"]["id"] == "EV-TEST-INC-1"
    assert body["total_conflicts"] >= 1
    assert any("EV-TEST-INC-1" in c["event_ids"] for c in body["new_conflicts"])

    # No pending work: incremental analyze returns the cached state quickly.
    cached = client.post("/analyze?mode=incremental")
    assert cached.status_code == 200
    assert cached.json()["event_count"] >= 100


def test_upload_csv_replaces_dataset(client: TestClient):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "timestamp",
            "duration_s",
            "entity",
            "lat",
            "lon",
            "source",
            "device_id",
            "action",
            "reliability",
        ]
    )
    for i in range(20):
        writer.writerow(
            [
                f"UP-{i:03d}",
                f"2026-04-01T10:{i:02d}:00Z",
                30,
                "SUBJ-UP",
                51.5 + i * 0.0001,
                -0.1,
                "gps",
                "GPS-UP",
                "FIX",
                0.9,
            ]
        )
    response = client.post(
        "/upload",
        files={"file": ("twenty.csv", buffer.getvalue().encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["events"] == 20
    state = client.get("/state").json()
    assert state["event_count"] == 20
    assert state["dataset"] == "TWENTY"


def test_upload_json_bundle_with_rule_and_truth(client: TestClient):
    bundle = {
        "meta": {"name": "BUNDLE-TEST", "seed": 99},
        "events": [
            {
                "id": "B-A",
                "timestamp": "2026-05-01T10:00:00Z",
                "duration_s": 10,
                "entity": "SUBJ-B",
                "lat": 51.5,
                "lon": -0.1,
                "source": "bank",
                "device_id": "TRM-1",
                "action": "WIRE",
                "reliability": 0.95,
            },
            {
                "id": "B-B",
                "timestamp": "2026-05-01T10:01:00Z",
                "duration_s": 10,
                "entity": "SUBJ-B",
                "lat": 51.5,
                "lon": -0.1,
                "source": "device",
                "device_id": "MOB-1",
                "action": "UNLOCK",
                "reliability": 0.8,
            },
        ],
        "rules": [
            {
                "type": "min_gap",
                "event_a": "B-B",
                "event_b": "B-A",
                "delta_s": 120,
            }
        ],
        "ground_truth": [
            {"type": "causality", "event_ids": ["B-B", "B-A"]}
        ],
    }
    response = client.post(
        "/upload",
        files={
            "file": (
                "bundle.json",
                json.dumps(bundle).encode(),
                "application/json",
            )
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["events"] == 2
    assert body["rules"] == 1
    state = client.get("/state").json()
    assert state["event_count"] == 2
    assert state["conflicts_found"] >= 1
    assert state["evaluation"]["recall"] >= 0.5


def test_bench_endpoint_small(client: TestClient):
    response = client.post(
        "/bench?persist=false",
        json={
            "sizes": [200, 400],
            "contradictions": 2,
            "seed": 5,
            "include_naive": True,
            "max_naive_events": 1000,
            "floyd_node_cap": 160,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["results"]) == 2
    assert payload["results"][0]["events"] >= 190
    assert payload["results"][0]["precision"] >= 0.5
    # UI probes must never overwrite the committed canonical benchmark.
    assert payload["files"]["canonical"] is False
    assert payload["files"]["json"].startswith("backend/results/runs/")
    latest = client.get("/bench/latest")
    assert latest.status_code == 200
    assert latest.json()["config"]["sizes"]


def test_not_found_and_bad_mode(client: TestClient):
    assert client.get("/conflicts/NOPE/explain").status_code == 404
    assert client.post("/analyze?mode=sideways").status_code == 422
