"""Pydantic request/response contracts for the ChronoClash API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.schema import SOURCES

SourceName = Literal["cctv", "call", "gps", "bank", "device", "witness"]
RuleName = Literal["precedes", "min_gap", "max_gap"]


class EventIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    timestamp: str | datetime
    duration_s: float = Field(default=0.0, ge=0.0)
    entity: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    source: SourceName
    device_id: str = Field(min_length=1, max_length=120)
    action: str = Field(default="UNKNOWN", max_length=160)
    reliability: float = Field(default=0.7, ge=0.0, le=1.0)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp_string(cls, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @field_validator("entity", "device_id")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    type: RuleName
    event_a: str
    event_b: str
    delta_s: float = 0.0
    note: str = ""


class AnalyzeRequest(BaseModel):
    mode: Literal["full", "incremental"] = "full"


class BenchRequest(BaseModel):
    sizes: list[int] = Field(default_factory=lambda: [1000, 10000])
    contradictions: int = Field(default=8, ge=0, le=5000)
    seed: int = 424242
    include_naive: bool = True
    max_naive_events: int = Field(default=10000, ge=0)
    floyd_node_cap: int = Field(default=180, ge=3, le=600)

    @field_validator("sizes")
    @classmethod
    def _sizes(cls, value: list[int]) -> list[int]:
        cleaned = sorted({int(v) for v in value if int(v) > 0})
        if not cleaned:
            raise ValueError("at least one positive dataset size is required")
        if len(cleaned) > 8:
            raise ValueError("at most 8 benchmark sizes per request")
        return cleaned


class ConflictQuery(BaseModel):
    top_k: int = Field(default=8, ge=0, le=1000)


class AddEventResponse(BaseModel):
    event: dict[str, Any]
    new_conflicts: list[dict[str, Any]]
    total_conflicts: int
    analysis_ms: float
    mode: str


class UploadResponse(BaseModel):
    dataset: str
    events: int
    rules: int
    entities: int
    ground_truth: int
    warnings: list[str]
    conflicts: int
    analysis_ms: float


class ApiMessage(BaseModel):
    ok: bool = True
    message: str


__all__ = [
    "EventIn",
    "RuleIn",
    "AnalyzeRequest",
    "BenchRequest",
    "ConflictQuery",
    "AddEventResponse",
    "UploadResponse",
    "ApiMessage",
    "SOURCES",
]
