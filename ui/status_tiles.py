"""STATUS tile grid: worst conflict severity per person and device."""

from __future__ import annotations

import streamlit as st

from contradiction_engine.models import Case, Conflict

from .widgets import severity_word

TILE_COLUMNS = 4
MAX_TILES = 24


def entity_severities(case: Case, conflicts: list[Conflict]) -> dict[str, float | None]:
    """Map each person and device to its worst conflict severity (None = clear)."""
    by_id = {record.id: record for record in case.records}
    worst: dict[str, float | None] = {}
    for record in case.records:
        for name in (record.person, record.device):
            if name:
                worst.setdefault(name, None)
    for conflict in conflicts:
        for record_id in conflict.record_ids:
            record = by_id.get(record_id)
            for name in ((record.person, record.device) if record else ()):
                current = worst.get(name)
                if name and (current is None or conflict.severity > current):
                    worst[name] = conflict.severity
    return worst


def render_status_tiles(case: Case, conflicts: list[Conflict]) -> None:
    """Draw one bordered tile per entity, worst severity first."""
    worst = entity_severities(case, conflicts)
    if not worst:
        return
    names = sorted(worst, key=lambda name: (-(worst[name] or -1.0), name))
    st.caption("Status")
    for start in range(0, min(len(names), MAX_TILES), TILE_COLUMNS):
        columns = st.columns(TILE_COLUMNS)
        chunk = names[start:min(start + TILE_COLUMNS, MAX_TILES)]
        for offset, (column, name) in enumerate(zip(columns, chunk)):
            with column:
                _render_tile(start + offset, name, worst[name])
    if len(names) > MAX_TILES:
        st.caption(f"{len(names) - MAX_TILES} more entities not shown.")


def _render_tile(position: int, name: str, severity: float | None) -> None:
    """Render one tile; the border colour comes from a fixed CSS class."""
    if severity is None:
        bucket, word, colour = "clear", "CLEAR", "green"
    else:
        word, colour = severity_word(severity)
        bucket = word.lower()
    with st.container(key=f"tile_{bucket}_{position}"):
        st.text(name)
        st.badge(word if severity is None else f"{word} {severity:.2f}",
                 color=colour)
