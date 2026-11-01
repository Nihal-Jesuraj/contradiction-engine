"""ChronoClash FastAPI surface."""

from __future__ import annotations

import csv
import io
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from core.bench import run_benchmark, write_results
from core.schema import Event

from .engine import REPO_ROOT, ChronoEngine
from .io import IngestError, parse_upload
from .schemas import BenchRequest, EventIn

RESULTS_DIR = REPO_ROOT / "backend" / "results"

engine = ChronoEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bootstrap is intentionally synchronous: the small bundled case warms all
    # indexes and makes the first /state request immediate.
    engine.bootstrap()
    yield


app = FastAPI(
    title="ChronoClash // Forensic Temporal Division",
    description=(
        "Temporal contradiction detection for forensic evidence records. "
        "Hand-built interval trees, Bellman-Ford negative-cycle diagnostics, "
        "incremental reachability, ranking heaps, and BFS explanations."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


class ApiPrefixMiddleware:
    """Serve the API under both / and /api.

    Keeping one canonical route table and stripping an optional /api prefix
    means a reverse proxy, the Streamlit HUD, and direct curl calls can all use
    the same service without duplicate route definitions.
    """

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                scope = dict(scope)
                scope["path"] = path[4:] or "/"
                raw_path = scope.get("raw_path")
                if raw_path:
                    scope["raw_path"] = raw_path[4:] or b"/"
        await self.app(scope, receive, send)


app.add_middleware(ApiPrefixMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.exception_handler(IngestError)
async def ingest_error_handler(_request, exc: IngestError):
    return JSONResponse(status_code=400, content={"detail": str(exc), "ok": False})


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "service": "chronoclash", "events": len(engine.normalized)}


@app.get("/state")
def state() -> dict[str, object]:
    return engine.stats()


@app.get("/timeline")
def timeline(
    entity: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=20_000),
) -> dict[str, object]:
    try:
        return engine.timeline(entity=entity, start=start, end=end, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    append: bool = Form(default=False),
    analyze: bool = Form(default=True),
) -> dict[str, object]:
    raw = await file.read()
    if len(raw) > 250 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="upload exceeds 250 MB limit")
    try:
        parsed = await run_in_threadpool(parse_upload, file.filename or "upload.jsonl", raw)
        if append:
            result = await run_in_threadpool(engine.append_dataset, parsed, analyze=analyze)
        else:
            result = await run_in_threadpool(engine.replace_dataset, parsed, analyze=analyze)
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, MemoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stats = engine.stats()
    return {
        **result,
        "dataset": engine.dataset_name,
        "entities": stats["entity_count"],
        "conflicts": stats["conflicts_found"],
        "analysis_ms": stats["analysis_ms"],
        "mode": stats["mode"],
    }


@app.post("/analyze")
async def analyze(
    mode: Literal["full", "incremental"] = Query(default="full"),
) -> dict[str, object]:
    try:
        return await run_in_threadpool(engine.analyze, mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/events")
async def add_event(payload: EventIn) -> dict[str, object]:
    event_id = payload.id or f"EV-INC-{uuid4().hex[:10].upper()}"
    event = Event(
        id=event_id,
        timestamp=str(payload.timestamp),
        duration_s=payload.duration_s,
        entity=payload.entity,
        lat=payload.lat,
        lon=payload.lon,
        source=payload.source,
        device_id=payload.device_id,
        action=payload.action,
        reliability=payload.reliability,
    )
    try:
        return await run_in_threadpool(engine.add_event, event)
    except IngestError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/conflicts")
def conflicts(top_k: int = Query(default=8, ge=0, le=1000)) -> dict[str, object]:
    items = engine.conflicts_payload(top_k)
    return {
        "conflicts": items,
        "returned": len(items),
        "total": len(engine.conflicts),
        "heap_capacity": top_k if top_k > 0 else len(engine.conflicts),
    }


@app.get("/conflicts/{conflict_id}/explain")
def explain(conflict_id: str) -> dict[str, object]:
    result = engine.explain(conflict_id)
    if result is None:
        raise HTTPException(status_code=404, detail="conflict not found")
    return result


@app.get("/entities")
def entities() -> dict[str, object]:
    items = engine.entity_summary()
    return {
        "entities": items,
        "total": len(items),
        "status": {
            "clean": sum(1 for item in items if item["status"] == "clean"),
            "suspect": sum(1 for item in items if item["status"] == "suspect"),
            "conflicted": sum(1 for item in items if item["status"] == "conflicted"),
        },
    }


@app.get("/gaps")
def gaps(
    threshold_s: float = Query(default=900.0, gt=0.0),
    entity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=0, le=2000),
) -> dict[str, object]:
    items = engine.gaps_payload(threshold_s=threshold_s, entity=entity, limit=limit)
    return {
        "gaps": items,
        "returned": len(items),
        "threshold_s": threshold_s,
        "entity": entity,
    }


@app.post("/bench")
def bench(
    request: BenchRequest = Body(default_factory=BenchRequest),
    persist: bool = Query(default=True),
) -> dict[str, object]:
    payload = run_benchmark(
        request.sizes,
        contradictions=request.contradictions,
        seed=request.seed,
        include_naive=request.include_naive,
        max_naive_events=request.max_naive_events,
        floyd_node_cap=request.floyd_node_cap,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = RESULTS_DIR if persist else RESULTS_DIR / "runs" / stamp
    json_path, csv_path = write_results(payload, output_dir)
    payload["files"] = {
        "json": str(json_path.relative_to(REPO_ROOT)),
        "csv": str(csv_path.relative_to(REPO_ROOT)),
        "canonical": persist,
    }
    return payload


@app.get("/bench/latest")
def bench_latest() -> dict[str, object]:
    path = RESULTS_DIR / "chronoclash_bench.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no benchmark has been run yet")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="benchmark JSON is corrupt") from exc


@app.get("/export")
def export(format: Literal["json", "csv"] = Query(default="json")) -> Response:
    if format == "json":
        payload = engine.export_payload()
        body = json.dumps(payload, indent=2)
        media = "application/json"
        extension = "json"
    else:
        rows = engine.export_rows()
        buffer = io.StringIO()
        fieldnames = list(rows[0].keys()) if rows else [
            "id",
            "kind",
            "severity",
            "confidence",
            "entity",
            "device_id",
            "t_delta_s",
            "sources",
            "event_ids",
            "detected_by",
            "detail",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        body = buffer.getvalue()
        media = "text/csv"
        extension = "csv"
    filename = f"{engine.case_id.lower()}_conflicts.{extension}"
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "ChronoClash // Forensic Temporal Division",
        "status": "online",
        "events": len(engine.normalized),
        "docs": "/docs",
        "hud": "Run `streamlit run hud/app.py` and open http://127.0.0.1:8501.",
    }
