"""STATUS tile grid: worst conflict severity per person and device."""

from __future__ import annotations

import streamlit as st

from contradiction_engine.models import Case, Conflict

from .widgets import severity_word

TILE_COLUMNS = 4
MAX_TILES = 24


def entity_severities(
    case: Case,
    conflicts: list[Conflict],
) -> dict[tuple[str, str], float | None]:
    """Map each person and device to its worst conflict severity (None = clear)."""
    by_id = {record.id: record for record in case.records}
    worst: dict[tuple[str, str], float | None] = {}
    for record in case.records:
        for kind, name in (("person", record.person), ("device", record.device)):
            if name:
                worst.setdefault((kind, name), None)
    for conflict in conflicts:
        for record_id in conflict.record_ids:
            record = by_id.get(record_id)
            if record is None:
                continue
            for kind, name in (("person", record.person), ("device", record.device)):
                key = (kind, name)
                if not name:
                    continue
                current = worst.get(key)
                if current is None or conflict.severity > current:
                    worst[key] = conflict.severity
    return worst


def render_status_tiles(case: Case, conflicts: list[Conflict]) -> None:
    """Draw one bordered tile per entity, worst severity first."""
    worst = entity_severities(case, conflicts)
    if not worst:
        return
    entities = sorted(worst, key=lambda key: (-(worst[key] or -1.0), key))
    st.caption("Status")
    for start in range(0, min(len(entities), MAX_TILES), TILE_COLUMNS):
        columns = st.columns(TILE_COLUMNS)
        chunk = entities[start:min(start + TILE_COLUMNS, MAX_TILES)]
        for offset, (column, entity) in enumerate(zip(columns, chunk)):
            with column:
                _render_tile(start + offset, entity, worst[entity])
    if len(entities) > MAX_TILES:
        st.caption(f"{len(entities) - MAX_TILES} more entities not shown.")


def _render_tile(
    position: int,
    entity: tuple[str, str],
    severity: float | None,
) -> None:
    """Render one tile; the border colour comes from a fixed CSS class."""
    if severity is None:
        bucket, word, colour = "clear", "CLEAR", "green"
    else:
        word, colour = severity_word(severity)
        bucket = word.lower()
    kind, name = entity
    with st.container(key=f"tile_{bucket}_{position}"):
        st.text(f"{kind.title()} · {name}")
        st.badge(word if severity is None else f"{word} {severity:.2f}",
                 color=colour)
