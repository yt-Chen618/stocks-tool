"""Small, dependency-free helpers used by backtest operators and tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_run_manifest(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write a canonical manifest without credentials or broker fields."""

    forbidden = {"api_key", "secret", "token", "password", "access_token", "broker_credentials"}
    if any(key.lower() in forbidden for key in payload):
        raise ValueError("backtest manifests may not contain broker credentials")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        encoding="utf-8",
    )
    return destination


def result_semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove non-deterministic fields before comparing two result payloads."""

    stable = dict(payload)
    for key in ("created_at", "started_at", "completed_at", "duration_seconds", "runtime_seconds"):
        stable.pop(key, None)
    return stable
