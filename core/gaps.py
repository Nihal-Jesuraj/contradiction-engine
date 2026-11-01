"""Evidence gap detection.

Complexity: O(n log n) to sort records per entity, O(n) to scan, plus
O(g log g) to order the g reported gaps.  Output is capped at the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .index import EventIndex
from .schema import iso_utc


@dataclass(slots=True)
class Gap:
    entity: str
    start_ts: float
    end_ts: float
    duration_s: float
    after_event: str | None
    before_event: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "start": iso_utc(self.start_ts),
            "end": iso_utc(self.end_ts),
            "duration_s": round(self.duration_s, 3),
            "after_event": self.after_event,
            "before_event": self.before_event,
        }


def find_gaps(
    index: EventIndex,
    *,
    threshold_s: float = 900.0,
    entity: str | None = None,
    include_edges: bool = True,
    limit: int = 200,
) -> list[Gap]:
    """Find periods with no evidence for each entity.

    A gap is measured from the *end* of one record to the *start* of the next,
    so overlapping durations are handled correctly.  Optional leading/trailing
    gaps use the global evidence window as the boundary.  For clock-skew
    investigations, edge gaps can be misleading; set ``include_edges=False``.

    O(n log n) time, O(g) space for g gaps before limiting.
    """
    bounds = index.bounds
    if bounds is None:
        return []
    window_start, window_end = bounds
    names = [entity] if entity is not None else index.entity_names
    gaps: list[Gap] = []

    for name in names:
        records = index.entity_events(name)
        if not records:
            continue
        if include_edges and records[0].ts - window_start >= threshold_s:
            gaps.append(
                Gap(
                    entity=name,
                    start_ts=window_start,
                    end_ts=records[0].ts,
                    duration_s=records[0].ts - window_start,
                    after_event=None,
                    before_event=records[0].id,
                )
            )
        cursor_end = records[0].end_ts
        cursor_event = records[0].id
        for record in records[1:]:
            gap = record.ts - cursor_end
            if gap >= threshold_s:
                gaps.append(
                    Gap(
                        entity=name,
                        start_ts=cursor_end,
                        end_ts=record.ts,
                        duration_s=gap,
                        after_event=cursor_event,
                        before_event=record.id,
                    )
                )
            if record.end_ts > cursor_end:
                cursor_end = record.end_ts
                cursor_event = record.id
        if include_edges and window_end - cursor_end >= threshold_s:
            gaps.append(
                Gap(
                    entity=name,
                    start_ts=cursor_end,
                    end_ts=window_end,
                    duration_s=window_end - cursor_end,
                    after_event=cursor_event,
                    before_event=None,
                )
            )

    gaps.sort(key=lambda g: (g.duration_s, g.entity, g.start_ts), reverse=True)
    return gaps[:limit] if limit > 0 else gaps
