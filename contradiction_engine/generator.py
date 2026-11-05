"""Seeded synthetic case generator with planted ground truth.

The generator first builds a clean, internally consistent case. It then adds
isolated planted scenarios, each derived from a clean template and altered in
exactly one way. Because every planted scenario uses its own person, device, or
account, one mutation cannot create an accidental second conflict.

Detectors never receive the ground truth; they only see ``case.records``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .algorithms.graph import WeightedGraph
from .models import Case, Evidence, GroundTruth, build_place_graph


@dataclass(frozen=True)
class GeneratorConfig:
    """Controls the size and planted-conflict counts of a generated case."""

    seed: int = 42
    people: int = 4
    device_conflicts: int = 2
    location_conflicts: int = 2
    message_conflicts: int = 2
    claim_conflicts: int = 2


@dataclass
class GeneratedCase:
    """A generated case plus the truth list kept separately for scoring."""

    case: Case
    truth: list[GroundTruth] = field(default_factory=list)


def generate_case(config: GeneratorConfig | None = None) -> GeneratedCase:
    """Generate a fictional case and its planted contradictions.

    Inputs: an optional ``GeneratorConfig``.
    Outputs: a ``GeneratedCase`` containing records and ground truth.
    Complexity: O(n log n) time for n generated records, O(n) space.
    """
    settings = config if config is not None else GeneratorConfig()
    _validate_config(settings)
    rng = random.Random(settings.seed)
    graph = build_place_graph()
    start = datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc)

    records: list[Evidence] = []
    truth: list[GroundTruth] = []
    counter = [0]

    for person_number in range(1, settings.people + 1):
        _add_clean_person(records, counter, person_number, start, rng, graph)

    _plant_device_conflicts(records, truth, counter, settings.device_conflicts, start)
    _plant_location_conflicts(
        records, truth, counter, settings.location_conflicts, start
    )
    _plant_message_conflicts(
        records, truth, counter, settings.message_conflicts, start
    )
    _plant_claim_conflicts(records, truth, counter, settings.claim_conflicts, start)

    case = Case(
        name=f"generated-seed-{settings.seed}",
        records=records,
        ground_truth=truth,
    )
    return GeneratedCase(case=case, truth=truth)


def _validate_config(config: GeneratorConfig) -> None:
    """Reject impossible sizes before generating anything."""
    if config.people < 1:
        raise ValueError("people must be at least 1")
    counts = (
        config.device_conflicts,
        config.location_conflicts,
        config.message_conflicts,
        config.claim_conflicts,
    )
    if any(count < 0 for count in counts):
        raise ValueError("planted conflict counts cannot be negative")


def _make_id(prefix: str, counter: list[int]) -> str:
    """Return the next readable, globally unique record ID."""
    counter[0] += 1
    return f"{prefix}-{counter[0]:04d}"


def _add_record(
    records: list[Evidence],
    counter: list[int],
    prefix: str,
    timestamp: datetime,
    record_type: str,
    **fields: object,
) -> Evidence:
    """Create, append, and return one evidence record."""
    record = Evidence(
        id=_make_id(prefix, counter),
        timestamp=timestamp,
        record_type=record_type,
        **fields,
    )
    records.append(record)
    return record


def _add_clean_person(
    records: list[Evidence],
    counter: list[int],
    number: int,
    start: datetime,
    rng: random.Random,
    graph: WeightedGraph,
) -> None:
    """Add one person's clean devices, sightings, messages, logins, and claim."""
    person = f"P{number:02d}"
    device = f"D{number:02d}"
    account = f"A{number:02d}"
    t0 = start + timedelta(hours=number - 1)

    _add_device_timeline(records, counter, person, device, t0)
    _add_sighting_walk(records, counter, person, t0, rng, graph)
    _add_message_chain(records, counter, person, t0)
    _add_logins(records, counter, person, account, t0)
    _add_clean_claim(records, counter, person, account, t0)


def _add_device_timeline(
    records: list[Evidence],
    counter: list[int],
    person: str,
    device: str,
    t0: datetime,
) -> None:
    """Add a clean ON/activity/OFF/SLEEP device timeline."""
    _add_record(records, counter, "ST", t0, "state", person=person,
                device=device, state="ON")
    _add_record(records, counter, "ACT", t0 + timedelta(minutes=10), "activity",
                person=person, device=device, action="local login")
    _add_record(records, counter, "ACT", t0 + timedelta(minutes=20), "activity",
                person=person, device=device, action="file access")
    _add_record(records, counter, "ST", t0 + timedelta(minutes=40), "state",
                person=person, device=device, state="OFF")
    _add_record(records, counter, "ST", t0 + timedelta(minutes=70), "state",
                person=person, device=device, state="SLEEP")
    _add_record(records, counter, "ST", t0 + timedelta(minutes=130), "state",
                person=person, device=device, state="ON")
    _add_record(records, counter, "ACT", t0 + timedelta(minutes=140), "activity",
                person=person, device=device, action="file access")
    _add_record(records, counter, "ACT", t0 + timedelta(minutes=150), "activity",
                person=person, device=device, action="local login")
    _add_record(records, counter, "ST", t0 + timedelta(minutes=180), "state",
                person=person, device=device, state="OFF")


def _add_sighting_walk(
    records: list[Evidence],
    counter: list[int],
    person: str,
    t0: datetime,
    rng: random.Random,
    graph: WeightedGraph,
) -> None:
    """Add four sightings along real roads, with enough time for each hop."""
    places = graph.nodes()
    current = places[rng.randrange(len(places))]
    moment = t0 + timedelta(minutes=30)
    _add_record(records, counter, "SGT", moment, "sighting",
                person=person, place=current)
    for _ in range(3):
        neighbours = graph.neighbors(current)
        next_place, minutes = neighbours[rng.randrange(len(neighbours))]
        # The dwell slack is positive, so the elapsed time is always at least
        # the road time and the clean case cannot contain a travel conflict.
        moment += timedelta(minutes=minutes + rng.randint(3, 8))
        _add_record(records, counter, "SGT", moment, "sighting",
                    person=person, place=next_place)
        current = next_place


def _add_message_chain(
    records: list[Evidence],
    counter: list[int],
    person: str,
    t0: datetime,
) -> None:
    """Add three messages where every reply is timestamped after its parent."""
    parent_id = ""
    moment = t0 + timedelta(minutes=200)
    for step in range(3):
        message = _add_record(
            records, counter, "MSG", moment, "message",
            person=person, depends_on=parent_id, text=f"message {step}",
        )
        parent_id = message.id
        moment += timedelta(minutes=10)


def _add_logins(
    records: list[Evidence],
    counter: list[int],
    person: str,
    account: str,
    t0: datetime,
) -> None:
    """Add two clean account logins."""
    _add_record(records, counter, "LOG", t0 + timedelta(minutes=300), "login",
                person=person, account=account)
    _add_record(records, counter, "LOG", t0 + timedelta(minutes=400), "login",
                person=person, account=account)


def _add_clean_claim(
    records: list[Evidence],
    counter: list[int],
    person: str,
    account: str,
    t0: datetime,
) -> None:
    """Add a denied-access claim whose window contains no login."""
    start = t0 + timedelta(minutes=500)
    _add_record(
        records, counter, "CLM", start, "claim",
        person=person, account=account, claim="did_not_access",
        end_timestamp=start + timedelta(minutes=60),
    )


def _plant_device_conflicts(
    records: list[Evidence],
    truth: list[GroundTruth],
    counter: list[int],
    count: int,
    start: datetime,
) -> None:
    """Add isolated devices where one activity happens while the device is off."""
    for index in range(count):
        device = f"PX-D{index + 1:02d}"
        t0 = start + timedelta(hours=6, minutes=index * 10)
        _add_record(records, counter, "ST", t0, "state",
                    device=device, state="ON")
        _add_record(records, counter, "ACT", t0 + timedelta(minutes=5),
                    "activity", device=device, action="file access")
        off_state = _add_record(records, counter, "ST", t0 + timedelta(minutes=10),
                                "state", device=device, state="OFF")
        activity = _add_record(records, counter, "ACT", t0 + timedelta(minutes=15),
                               "activity", device=device, action="local login")
        truth.append(
            GroundTruth("device_state", (activity.id, off_state.id),
                        "activity planted inside an OFF interval")
        )


def _plant_location_conflicts(
    records: list[Evidence],
    truth: list[GroundTruth],
    counter: list[int],
    count: int,
    start: datetime,
) -> None:
    """Add people teleported between two places in one minute."""
    for index in range(count):
        person = f"PX-P{index + 1:02d}"
        t0 = start + timedelta(hours=7, minutes=index * 10)
        first = _add_record(records, counter, "SGT", t0, "sighting",
                            person=person, place="Harbour")
        second = _add_record(records, counter, "SGT",
                             t0 + timedelta(minutes=1), "sighting",
                             person=person, place="Library")
        truth.append(
            GroundTruth("location", (first.id, second.id),
                        "one-minute hop between distant places")
        )


def _plant_message_conflicts(
    records: list[Evidence],
    truth: list[GroundTruth],
    counter: list[int],
    count: int,
    start: datetime,
) -> None:
    """Add replies timestamped before the message they answer."""
    for index in range(count):
        person = f"PX-M{index + 1:02d}"
        t0 = start + timedelta(hours=8, minutes=index * 10)
        parent = _add_record(records, counter, "MSG",
                             t0 + timedelta(minutes=10), "message",
                             person=person, text="original message")
        child = _add_record(records, counter, "MSG", t0 + timedelta(minutes=5),
                            "message", person=person, depends_on=parent.id,
                            text="reply planted before its parent")
        truth.append(
            GroundTruth("message_order", (parent.id, child.id),
                        "reply timestamped before its parent")
        )


def _plant_claim_conflicts(
    records: list[Evidence],
    truth: list[GroundTruth],
    counter: list[int],
    count: int,
    start: datetime,
) -> None:
    """Add denied-access claims that overlap a real login."""
    for index in range(count):
        person = f"PX-C{index + 1:02d}"
        account = f"PX-AC{index + 1:02d}"
        t0 = start + timedelta(hours=9, minutes=index * 10)
        login = _add_record(records, counter, "LOG", t0 + timedelta(minutes=10),
                            "login", person=person, account=account)
        claim = _add_record(
            records, counter, "CLM", t0, "claim",
            person=person, account=account, claim="did_not_access",
            end_timestamp=t0 + timedelta(minutes=20),
        )
        truth.append(
            GroundTruth("claim", (claim.id, login.id),
                        "login inside a denied-access window")
        )
