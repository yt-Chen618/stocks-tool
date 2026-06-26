from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TEST_WATCHLIST_NAMES = {"string", "test", "demo", "sample"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only local data hygiene audit for watchlists and generated evidence artifacts."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP timeout.")
    parser.add_argument("--require-api", action="store_true", help="Fail if the local API cannot be queried.")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=14,
        help="Mark generated local evidence files older than this many days as retention candidates.",
    )
    parser.add_argument(
        "--archive-stale-generated",
        action="store_true",
        help="Move stale generated evidence into a local archive folder. Requires --confirm-generated-cleanup.",
    )
    parser.add_argument(
        "--archive-root",
        default=str(ROOT.parent / "stocks-tool-local-archives"),
        help="Archive root used with --archive-stale-generated.",
    )
    parser.add_argument(
        "--cleanup-project-caches",
        action="store_true",
        help="Remove project __pycache__ and .pytest_cache directories. Requires --confirm-generated-cleanup.",
    )
    parser.add_argument(
        "--confirm-generated-cleanup",
        action="store_true",
        help="Required confirmation for moving generated evidence or removing project caches.",
    )
    parser.add_argument("--json-output", help="Optional file path for the JSON audit report.")
    return parser.parse_args()


def directory_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "file_count": 0, "total_bytes": 0, "largest_files": []}
    files = [item for item in path.rglob("*") if item.is_file()]
    largest = sorted(files, key=lambda item: item.stat().st_size, reverse=True)[:10]
    return {
        "path": str(path),
        "exists": True,
        "file_count": len(files),
        "total_bytes": sum(item.stat().st_size for item in files),
        "largest_files": [
            {
                "path": str(item.relative_to(ROOT)),
                "bytes": item.stat().st_size,
            }
            for item in largest
        ],
    }


def fetch_watchlists(base_url: str, timeout_seconds: float) -> tuple[list[dict[str, Any]], str | None]:
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds) as client:
            response = client.get("/watchlists")
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)], None
            return [], "/watchlists did not return a list."
    except Exception as error:
        return [], str(error)


def watchlist_audit(watchlists: list[dict[str, Any]]) -> dict[str, Any]:
    names = [str(item.get("name") or item.get("slug") or "").strip() for item in watchlists]
    normalized_names = [name.lower() for name in names if name]
    counts = Counter(normalized_names)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    test_residue = sorted(name for name in normalized_names if name in TEST_WATCHLIST_NAMES)
    return {
        "count": len(watchlists),
        "duplicate_names": duplicates,
        "test_residue_names": sorted(set(test_residue)),
        "items": [
            {
                "id": item.get("id"),
                "name": item.get("name") or item.get("slug"),
                "symbol_count": len(item.get("symbols") or []),
            }
            for item in watchlists
        ],
    }


def file_age_days(path: Path, *, now: datetime) -> float:
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return max(0.0, (now - modified_at).total_seconds() / 86400)


def retention_report(
    root: Path,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    categories = {
        "old_artifacts": root / "artifacts",
        "old_playwright_screenshots": root / "output" / "playwright",
        "stale_jsonl_notifications": root / "artifacts",
    }
    report: dict[str, Any] = {
        "retention_days": retention_days,
        "generated_at": now.isoformat(),
        "candidate_count": 0,
        "total_bytes": 0,
        "categories": {},
    }
    for name, directory in categories.items():
        candidates: list[dict[str, Any]] = []
        if directory.exists():
            files = [item for item in directory.rglob("*") if item.is_file()]
            if name == "stale_jsonl_notifications":
                files = [item for item in files if item.suffix.lower() == ".jsonl"]
            elif name == "old_playwright_screenshots":
                files = [item for item in files if item.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
            for item in files:
                age_days = file_age_days(item, now=now)
                if age_days < retention_days:
                    continue
                candidates.append(
                    {
                        "path": str(item.relative_to(root)),
                        "bytes": item.stat().st_size,
                        "age_days": round(age_days, 1),
                    }
                )
        candidates = sorted(candidates, key=lambda entry: (entry["age_days"], entry["bytes"]), reverse=True)
        total_bytes = sum(int(entry["bytes"]) for entry in candidates)
        report["categories"][name] = {
            "path": str(directory),
            "candidate_count": len(candidates),
            "total_bytes": total_bytes,
            "candidates": candidates[:25],
        }
        report["candidate_count"] += len(candidates)
        report["total_bytes"] += total_bytes
    return report


def retention_candidate_paths(
    root: Path,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> list[Path]:
    now = now or datetime.now(timezone.utc)
    paths: dict[str, Path] = {}
    for directory, suffixes in (
        (root / "artifacts", None),
        (root / "output" / "playwright", {".png", ".jpg", ".jpeg", ".webp"}),
        (root / "artifacts", {".jsonl"}),
    ):
        if not directory.exists():
            continue
        for item in directory.rglob("*"):
            if not item.is_file():
                continue
            if suffixes is not None and item.suffix.lower() not in suffixes:
                continue
            if file_age_days(item, now=now) < retention_days:
                continue
            relative = item.relative_to(root).as_posix()
            paths[relative] = item
    return [paths[key] for key in sorted(paths)]


def archive_stale_generated_files(
    root: Path,
    *,
    retention_days: int,
    archive_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    root = root.resolve()
    archive_root = archive_root.resolve()
    archive_dir = archive_root / f"cleanup-{now.strftime('%Y%m%d-%H%M%S')}"
    moved: list[dict[str, Any]] = []
    for source in retention_candidate_paths(root, retention_days=retention_days, now=now):
        source = source.resolve()
        if not source.is_relative_to(root):
            raise ValueError(f"Refusing to archive path outside repo: {source}")
        relative = source.relative_to(root)
        target = archive_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        bytes_count = source.stat().st_size
        source.replace(target)
        moved.append(
            {
                "source": relative.as_posix(),
                "target": str(target.relative_to(archive_dir)),
                "bytes": bytes_count,
            }
        )
    archive_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "repo": str(root),
        "archive": str(archive_dir),
        "generated_at": now.isoformat(),
        "retention_days": retention_days,
        "moved_count": len(moved),
        "moved_bytes": sum(int(item["bytes"]) for item in moved),
        "moved": moved,
    }
    (archive_dir / "cleanup-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def cleanup_project_caches(root: Path) -> dict[str, Any]:
    root = root.resolve()
    candidates = [root / ".pytest_cache"]
    candidates.extend(path for path in root.rglob("__pycache__") if ".venv" not in path.parts)
    removed: list[dict[str, Any]] = []
    for candidate in sorted(set(candidates)):
        if not candidate.exists():
            continue
        candidate = candidate.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"Refusing to remove cache outside repo: {candidate}")
        if ".venv" in candidate.parts:
            raise ValueError(f"Refusing to remove venv cache: {candidate}")
        bytes_count = sum(item.stat().st_size for item in candidate.rglob("*") if item.is_file())
        shutil.rmtree(candidate, onexc=_chmod_and_retry_remove)
        removed.append({"path": candidate.relative_to(root).as_posix(), "bytes": bytes_count})
    return {
        "removed_count": len(removed),
        "removed_bytes": sum(int(item["bytes"]) for item in removed),
        "removed": removed,
    }


def _chmod_and_retry_remove(function: Any, path: str, exc_info: BaseException) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except Exception:
        raise exc_info


def cleanup_notes(
    *,
    watchlists: dict[str, Any],
    artifacts: dict[str, Any],
    playwright: dict[str, Any],
    retention: dict[str, Any] | None = None,
) -> list[str]:
    notes: list[str] = []
    if watchlists["duplicate_names"]:
        notes.append("Review duplicate watchlists by name before deleting any row.")
    if watchlists["test_residue_names"]:
        notes.append("Review test-residue watchlists before deleting them.")
    if artifacts["file_count"]:
        notes.append("Generated JSON/log evidence under artifacts/ can be archived or pruned after preserving latest passes.")
    if playwright["file_count"]:
        notes.append("Generated browser screenshots under output/playwright/ can be pruned after preserving latest passes.")
    if retention and retention.get("candidate_count"):
        notes.append("Retention candidates are read-only suggestions; archive or prune only after preserving release evidence.")
    if not notes:
        notes.append("No obvious local hygiene candidates were found.")
    return notes


def cleanup_plan(
    *,
    watchlists: dict[str, Any],
    artifacts: dict[str, Any],
    playwright: dict[str, Any],
    retention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    duplicate_names = watchlists["duplicate_names"]
    test_residue_names = watchlists["test_residue_names"]
    if duplicate_names:
        actions.append(
            {
                "action": "review_duplicate_watchlists",
                "target": duplicate_names,
                "destructive": True,
                "requires_manual_confirmation": True,
                "guidance": (
                    "Compare duplicate watchlists by id/name/symbols and keep the intentional row before deleting any duplicate."
                ),
            }
        )
    if test_residue_names:
        actions.append(
            {
                "action": "review_test_residue_watchlists",
                "target": test_residue_names,
                "destructive": True,
                "requires_manual_confirmation": True,
                "guidance": "Delete only rows confirmed to be manual/API test residue, such as an empty `string` watchlist.",
            }
        )
    if artifacts["file_count"]:
        actions.append(
            {
                "action": "archive_or_prune_generated_artifacts",
                "target": "artifacts/",
                "destructive": True,
                "requires_manual_confirmation": True,
                "guidance": "Preserve latest pass/fail evidence before archiving or pruning old generated JSON/log files.",
                "file_count": artifacts["file_count"],
                "total_bytes": artifacts["total_bytes"],
            }
        )
    if playwright["file_count"]:
        actions.append(
            {
                "action": "archive_or_prune_playwright_output",
                "target": "output/playwright/",
                "destructive": True,
                "requires_manual_confirmation": True,
                "guidance": "Preserve latest screenshots needed for UI evidence before pruning old generated browser output.",
                "file_count": playwright["file_count"],
                "total_bytes": playwright["total_bytes"],
            }
        )
    if retention and retention.get("candidate_count"):
        actions.append(
            {
                "action": "review_retention_candidates",
                "target": "generated local evidence files",
                "destructive": True,
                "requires_manual_confirmation": True,
                "guidance": (
                    "Use the retention_report candidates to archive or prune stale generated evidence only; "
                    "do not delete order, execution, journal, strategy audit, advisor, scheduler, or strategy ledger rows."
                ),
                "candidate_count": retention["candidate_count"],
                "total_bytes": retention["total_bytes"],
                "suggested_commands": [
                    "Review candidate paths in payload.retention_report before running any cleanup command.",
                    "Prefer Move-Item into a dated archive folder before permanent deletion.",
                ],
            }
        )
    return {
        "actions": actions,
        "safe_by_default": True,
        "destructive_actions_executed": False,
        "never_delete_without_backup": [
            "orders",
            "executions",
            "journals",
            "strategy_audit_events",
            "strategy_advisor_runs",
            "scheduler_job_runs",
            "scheduler_task_states",
            "strategy_proposals",
            "strategy_runs",
            "strategy_signals",
            "strategy_reviews",
        ],
    }


def main() -> None:
    args = parse_args()
    cleanup_requested = bool(args.archive_stale_generated or args.cleanup_project_caches)
    if cleanup_requested and not args.confirm_generated_cleanup:
        emit_report(
            build_report(
                script="run_data_hygiene_audit.py",
                workflow="data-hygiene-audit",
                status="failed",
                mode="local",
                target=args.base_url.rstrip("/"),
                summary="Generated cleanup was requested without explicit confirmation.",
                error="Pass --confirm-generated-cleanup with cleanup flags.",
                payload={"destructive_actions_executed": False},
            ),
            json_output=args.json_output,
        )
        raise SystemExit(2)

    base_url = args.base_url.rstrip("/")
    watchlists, api_error = fetch_watchlists(base_url, args.timeout_seconds)
    if api_error and args.require_api:
        emit_report(
            build_report(
                script="run_data_hygiene_audit.py",
                workflow="data-hygiene-audit",
                status="failed",
                mode="local",
                target=base_url,
                summary="Data hygiene audit failed because the local API was unavailable.",
                error=api_error,
            ),
            json_output=args.json_output,
        )
        raise SystemExit(1)

    watchlists_report = watchlist_audit(watchlists)
    artifacts_report = directory_summary(ROOT / "artifacts")
    playwright_report = directory_summary(ROOT / "output" / "playwright")
    retention = retention_report(ROOT, retention_days=args.retention_days)
    cleanup_result: dict[str, Any] = {
        "archive": None,
        "project_caches": None,
    }
    if args.archive_stale_generated:
        cleanup_result["archive"] = archive_stale_generated_files(
            ROOT,
            retention_days=args.retention_days,
            archive_root=Path(args.archive_root),
        )
        artifacts_report = directory_summary(ROOT / "artifacts")
        playwright_report = directory_summary(ROOT / "output" / "playwright")
        retention = retention_report(ROOT, retention_days=args.retention_days)
    if args.cleanup_project_caches:
        cleanup_result["project_caches"] = cleanup_project_caches(ROOT)
    notes = cleanup_notes(
        watchlists=watchlists_report,
        artifacts=artifacts_report,
        playwright=playwright_report,
        retention=retention,
    )
    plan = cleanup_plan(
        watchlists=watchlists_report,
        artifacts=artifacts_report,
        playwright=playwright_report,
        retention=retention,
    )
    plan["destructive_actions_executed"] = cleanup_requested
    status = "warning" if api_error or watchlists_report["duplicate_names"] or watchlists_report["test_residue_names"] else "passed"
    emit_report(
        build_report(
            script="run_data_hygiene_audit.py",
            workflow="data-hygiene-audit",
            status=status,
            mode="local",
            target=base_url,
            summary=(
                "Data hygiene audit completed. "
                f"watchlists={watchlists_report['count']}, "
                f"duplicates={len(watchlists_report['duplicate_names'])}, "
                f"test_residue={len(watchlists_report['test_residue_names'])}."
            ),
            payload={
                "api_error": api_error,
                "watchlists": watchlists_report,
                "artifacts": artifacts_report,
                "playwright_output": playwright_report,
                "retention_report": retention,
                "cleanup_notes": notes,
                "cleanup_plan": plan,
                "cleanup_result": cleanup_result,
                "destructive_actions_executed": cleanup_requested,
            },
        ),
        json_output=args.json_output,
    )


if __name__ == "__main__":
    main()
