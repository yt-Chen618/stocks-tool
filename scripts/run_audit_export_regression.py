from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"


class AuditExportError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only operator audit evidence from a running local API."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument("--mode", default="paper", help="Execution mode filter.")
    parser.add_argument("--limit", type=int, default=50, help="Audit event export limit.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP timeout.")
    parser.add_argument("--json-output", help="Optional file path for the JSON regression report.")
    return parser.parse_args()


def require_ok(response: httpx.Response) -> Any:
    if response.is_success:
        return response.json()
    detail = f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("detail"):
        detail = str(payload["detail"])
    raise AuditExportError(detail)


def raw_export_path(json_output: str | None) -> Path | None:
    if not json_output:
        return None
    path = Path(json_output)
    return path.with_name(f"{path.stem}.raw-events{path.suffix or '.json'}")


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=args.timeout_seconds) as client:
        try:
            health = require_ok(client.get("/health"))
            events = require_ok(
                client.get(
                    "/ops/audit",
                    params={
                        "external_account_id": args.account_id,
                        "mode": args.mode,
                        "limit": args.limit,
                    },
                )
            )
            summary = require_ok(
                client.get(
                    "/ops/audit/summary",
                    params={
                        "external_account_id": args.account_id,
                        "mode": args.mode,
                        "limit": max(args.limit, 1),
                    },
                )
            )
            if not isinstance(events, list):
                raise AuditExportError("/ops/audit did not return a list.")
            if not isinstance(summary, dict):
                raise AuditExportError("/ops/audit/summary did not return an object.")
            raw_path = raw_export_path(args.json_output)
            if raw_path is not None:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(
                    json.dumps({"events": events, "summary": summary}, indent=2),
                    encoding="utf-8",
                )
            emit_report(
                build_report(
                    script="run_audit_export_regression.py",
                    workflow="audit-export",
                    status="passed",
                    mode=args.mode,
                    target=base_url,
                    summary=(
                        "Operator audit export completed. "
                        f"events={len(events)}, summary_groups={len(summary.get('groups') or [])}."
                    ),
                    payload={
                        "health": health,
                        "account_id": args.account_id,
                        "event_count": len(events),
                        "event_sample": events[:5],
                        "raw_export_path": str(raw_path) if raw_path is not None else None,
                        "summary": summary,
                    },
                ),
                json_output=args.json_output,
            )
        except Exception as error:
            emit_report(
                build_report(
                    script="run_audit_export_regression.py",
                    workflow="audit-export",
                    status="failed",
                    mode=args.mode,
                    target=base_url,
                    summary="Operator audit export failed.",
                    error=str(error),
                    payload={"account_id": args.account_id},
                ),
                json_output=args.json_output,
            )
            raise SystemExit(1)


if __name__ == "__main__":
    main()
