"""HTTP client for the ChronoClash FastAPI service.

The Streamlit HUD never imports the algorithmic core directly: it speaks to the
same public API a remote analyst would use.  Keeping this layer in one place
also makes the terminal usable against a backend on another host/port.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests


DEFAULT_API_BASE = "http://127.0.0.1:8000/api"


class ApiError(RuntimeError):
    """A transport or HTTP-level fault surfaced to the HUD."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class ApiClient:
    base: str = DEFAULT_API_BASE
    timeout: float = 120.0

    def __post_init__(self) -> None:
        self.base = self.base.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    @classmethod
    def from_env(cls) -> "ApiClient":
        return cls(os.environ.get("CHRONOCLASH_API", DEFAULT_API_BASE))

    # ------------------------------------------------------------- transport
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        data: Any | None = None,
        files: Any | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self.base}{path}"
        try:
            response = self._session.request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                files=files,
                timeout=timeout or self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiError("Temporal link severed - backend unreachable.", 0) from exc
        if not response.ok:
            detail = f"{response.status_code} {response.reason}"
            try:
                payload = response.json()
                detail = payload.get("detail") or payload.get("message") or detail
            except ValueError:
                pass
            raise ApiError(str(detail), response.status_code)
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.content

    # --------------------------------------------------------------- reads
    def state(self) -> dict[str, Any]:
        return self._request("GET", "/state", timeout=30)

    def conflicts(self, top_k: int = 8) -> dict[str, Any]:
        return self._request("GET", "/conflicts", params={"top_k": top_k})

    def timeline(
        self,
        entity: str | None = None,
        limit: int = 4000,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if entity:
            params["entity"] = entity
        return self._request("GET", "/timeline", params=params)

    def explain(self, conflict_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/conflicts/{quote(conflict_id, safe='')}/explain"
        )

    def gaps(
        self,
        threshold_s: float = 900.0,
        entity: str | None = None,
        limit: int = 120,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threshold_s": threshold_s, "limit": limit}
        if entity:
            params["entity"] = entity
        return self._request("GET", "/gaps", params=params)

    def latest_bench(self) -> dict[str, Any]:
        return self._request("GET", "/bench/latest", timeout=30)

    # -------------------------------------------------------------- writes
    def analyze(self, mode: str = "full") -> dict[str, Any]:
        return self._request(
            "POST",
            "/analyze",
            params={"mode": "incremental" if mode == "incremental" else "full"},
            timeout=900,
        )

    def add_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/events", json=payload, timeout=120)

    def upload(
        self,
        filename: str,
        content: bytes,
        append: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/upload",
            data={"append": "true" if append else "false", "analyze": "true"},
            files={"file": (filename, content, "application/octet-stream")},
            timeout=900,
        )

    def bench(
        self,
        sizes: list[int],
        contradictions: int = 8,
        seed: int = 424242,
        include_naive: bool = True,
        max_naive_events: int = 10_000,
        floyd_node_cap: int = 180,
        persist: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/bench",
            params={"persist": "true" if persist else "false"},
            json={
                "sizes": sizes,
                "contradictions": contradictions,
                "seed": seed,
                "include_naive": include_naive,
                "max_naive_events": max_naive_events,
                "floyd_node_cap": floyd_node_cap,
            },
            timeout=60 * 60,
        )

    def export_url(self, fmt: str = "json") -> str:
        return f"{self.base}/export?format={fmt}"


__all__ = ["ApiClient", "ApiError", "DEFAULT_API_BASE"]
