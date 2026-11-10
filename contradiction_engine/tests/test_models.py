"""Tests for the place graph, scoring, and case index."""

from __future__ import annotations

from datetime import datetime, timezone

from contradiction_engine.models import (
    CaseIndex,
    Conflict,
    Evidence,
    GroundTruth,
    build_evidence_graph,
    build_place_graph,
    is_connected,
    score_conflicts,
    travel_minutes,
)


def test_default_graph_is_sparse_and_connected() -> None:
    """The map has 10 places, 16 roads, and no isolated node."""
    graph = build_place_graph()
    assert len(graph.nodes()) == 10
    edge_count = sum(len(graph.neighbors(node)) for node in graph.nodes()) // 2
    assert edge_count == 16
    assert is_connected(graph)


def test_direct_edge_is_slower_than_a_two_hop_route() -> None:
    """Clinic-Park costs 20 directly but only 12 through Library."""
    graph = build_place_graph()
    distances, previous = graph.dijkstra("Clinic")
    assert graph.edge_weight("Clinic", "Park") == 20
    assert distances["Park"] == 12
    assert graph.shortest_path(previous, "Clinic", "Park") == [
        "Clinic",
        "Library",
        "Park",
    ]


def test_haversine_fallback_is_positive() -> None:
    """An edge without explicit minutes still gets a usable weight."""
    minutes = travel_minutes(
        {"A": (51.50, -0.12), "B": (51.51, -0.11)}, "A", "B"
    )
    assert minutes >= 2


def make_record(record_id: str, hour: int, person: str = "P1") -> Evidence:
    """Build a small sighting record for index tests."""
    return Evidence(
        id=record_id,
        timestamp=datetime(2026, 3, 2, hour, tzinfo=timezone.utc),
        record_type="sighting",
        person=person,
        place="Harbour",
        text="walked by the harbour",
    )


def test_score_matches_subset_ids() -> None:
    """A detected conflict may include extra IDs around the planted pair."""
    found = [
        Conflict(
            "location",
            ("A", "B", "extra"),
            "rule",
            {},
            "explanation",
            0.8,
        )
    ]
    truth = [GroundTruth("location", ("A", "B"))]
    score = score_conflicts(found, truth)
    assert score.available is True
    assert score.matched == 1
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.f1 == 1.0


def test_score_without_truth_is_unavailable() -> None:
    """An uploaded case without truth reports no score, not zero."""
    score = score_conflicts([], [])
    assert score.available is False
    assert score.detected == 0
    assert score.planted == 0


def test_score_counts_false_positives_and_misses() -> None:
    """Wrong kinds and missing detections reduce precision and recall."""
    found = [
        Conflict("location", ("A", "B"), "rule", {}, "found", 0.8),
        Conflict("claim", ("X", "Y"), "rule", {}, "extra", 0.5),
    ]
    truth = [
        GroundTruth("location", ("A", "B")),
        GroundTruth("device_state", ("C", "D")),
    ]
    score = score_conflicts(found, truth)
    assert score.matched == 1
    assert score.precision == 0.5
    assert score.recall == 0.5


def test_case_index_filters_and_range() -> None:
    """Hash indexes and binary-search range queries return the right rows."""
    records = [
        make_record("R1", 8, "P1"),
        make_record("R2", 9, "P2"),
        make_record("R3", 10, "P1"),
    ]
    index = CaseIndex(records)
    assert index.people() == ["P1", "P2"]
    assert [row.id for row in index.for_person("P1")] == ["R1", "R3"]
    start = datetime(2026, 3, 2, 8, 30, tzinfo=timezone.utc)
    end = datetime(2026, 3, 2, 9, 30, tzinfo=timezone.utc)
    assert [row.id for row in index.in_range(start, end)] == ["R2"]
    assert [row.id for row in index.keyword("harbour")] == ["R1", "R2", "R3"]
    assert index.keyword("nothing") == []


def test_evidence_graph_links_people_devices_accounts_and_places() -> None:
    """Co-occurring entities become neighbours in the BFS graph."""
    records = [
        make_record("R1", 8, "P1"),
        Evidence(
            id="R2",
            timestamp=datetime(2026, 3, 2, 9, tzinfo=timezone.utc),
            record_type="login",
            person="P1",
            account="A1",
            device="D1",
        ),
    ]
    graph = build_evidence_graph(records)
    assert set(graph.neighbors("person:P1")) == {
        "place:Harbour",
        "account:A1",
        "device:D1",
    }
    assert graph.related("person:P1", 1)["place:Harbour"] == 1
    assert graph.related("person:P1", 2)["device:D1"] == 1


def test_case_index_exposes_the_entity_graph() -> None:
    """The explorer reuses one graph built at index time."""
    index = CaseIndex([make_record("R1", 8, "P1")])
    assert index.evidence_graph.related("person:P1", 1) == {"place:Harbour": 1}
