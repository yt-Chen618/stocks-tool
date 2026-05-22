from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_report(
    *,
    script: str,
    workflow: str,
    status: str,
    mode: str,
    summary: str,
    target: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    report = {
        "script": script,
        "workflow": workflow,
        "status": status,
        "mode": mode,
        "target": target,
        "summary": summary,
        "generated_at": utc_now_iso(),
        "payload": payload or {},
    }
    if error is not None:
        report["error"] = error
    return report


def emit_report(report: dict[str, Any], json_output: str | None = None) -> None:
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if json_output:
        output_path = Path(json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
