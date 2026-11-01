"""Presentation helpers shared by the Streamlit HUD panels."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, Iterable
from urllib.parse import urlencode


SOURCE_ORDER: tuple[str, ...] = ("cctv", "call", "gps", "bank", "device", "witness")

SOURCE_COLORS: dict[str, str] = {
    "cctv": "#fcee09",
    "call": "#00f0ff",
    "gps": "#ff2bd6",
    "bank": "#ff9f1c",
    "device": "#8a7dff",
    "witness": "#ffffff",
}

SOURCE_LABEL: dict[str, str] = {
    "cctv": "CCTV",
    "call": "CALL",
    "gps": "GPS",
    "bank": "BANK",
    "device": "DEVICE",
    "witness": "WITNESS",
}

KIND_LABEL: dict[str, str] = {
    "impossible_simultaneity": "SIMULTANEITY",
    "impossible_travel": "IMPOSSIBLE TRAVEL",
    "causality": "CAUSALITY",
    "clock_skew": "CLOCK SKEW",
    "constraint_cycle": "NEGATIVE CYCLE",
}

KIND_SHORT: dict[str, str] = {
    "impossible_simultaneity": "SIMUL",
    "impossible_travel": "TRAVEL",
    "causality": "CAUSAL",
    "clock_skew": "SKEW",
    "constraint_cycle": "CYCLE",
}

STATUS_LABEL: dict[str, str] = {
    "clean": "VERIFIED",
    "suspect": "SUSPECT",
    "conflicted": "CONFLICTED",
}

STATUS_SHORT: dict[str, str] = {
    "clean": "CLEAN",
    "suspect": "SUSP",
    "conflicted": "CONF",
}


def esc(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def fmt_int(value: Any) -> str:
    try:
        if value is None:
            return "-"
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "-"


def fmt_compact(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return f"{number:g}"


def fmt_ms(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number < 1:
        return f"{number * 1000:.0f}us"
    if number < 1000:
        return f"{number:.2f}ms" if number < 10 else f"{number:.1f}ms"
    return f"{number / 1000:.2f}s"


def fmt_pct(value: Any, digits: int = 0) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def fmt_duration(seconds: Any) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "-"
    absolute = abs(value)
    if absolute < 60:
        return f"{value:.1f}s" if absolute < 10 else f"{value:.0f}s"
    if absolute < 3600:
        return f"{value / 60:.1f}m"
    if absolute < 86_400:
        return f"{value / 3600:.2f}h"
    return f"{value / 86_400:.2f}d"


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_utc(value: str | None) -> str:
    dt = parse_iso(value)
    if dt is None:
        return "-"
    dt = dt.astimezone(timezone.utc)
    return f"{dt:%m-%d %H:%M}Z"


def fmt_clock(value: str | None, with_seconds: bool = False) -> str:
    dt = parse_iso(value)
    if dt is None:
        return "-"
    dt = dt.astimezone(timezone.utc)
    return f"{dt:%H:%M:%S}" if with_seconds else f"{dt:%H:%M}"


def fmt_datetime(value: str | None) -> str:
    dt = parse_iso(value)
    if dt is None:
        return "-"
    dt = dt.astimezone(timezone.utc)
    return f"{dt:%Y-%m-%d %H:%M:%S}Z"


def fmt_span(start: str | None, end: str | None) -> str:
    left, right = parse_iso(start), parse_iso(end)
    if left is None or right is None:
        return "-"
    return fmt_duration((right - left).total_seconds())


def severity_class(severity: Any) -> str:
    try:
        value = float(severity)
    except (TypeError, ValueError):
        value = 0.0
    if value >= 0.8:
        return "critical"
    if value >= 0.64:
        return "high"
    if value >= 0.45:
        return "moderate"
    return "low"


def url_for(**params: Any) -> str:
    """A relative query-string URL for the current Streamlit page."""
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return "?" + urlencode(clean) if clean else "?"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sparkline_svg(
    values: Iterable[float],
    width: int = 118,
    height: int = 34,
    color: str = "#f5a623",
) -> str:
    """Hand-built SVG sparkline so the HUD has no chart dependency for it."""
    series = [float(value) for value in values if value is not None]
    if len(series) < 2:
        series = series * 2 if series else [0.0, 0.0]
    low, high = min(series), max(series)
    span = high - low or 1.0
    step = width / max(1, len(series) - 1)
    points: list[tuple[float, float]] = []
    for index, value in enumerate(series):
        x = index * step
        y = height - 4 - ((value - low) / span) * (height - 10)
        points.append((x, y))
    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    area = f"0,{height} {line} {width},{height}"
    last_x, last_y = points[-1]
    return (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polygon points="{area}" fill="{color}" opacity="0.10"/>'
        f'<line x1="0" y1="{height - 4}" x2="{width}" y2="{height - 4}" '
        f'stroke="rgba(245,166,35,0.16)" stroke-width="1"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.4" '
        f'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="2" fill="{color}"/>'
        "</svg>"
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
