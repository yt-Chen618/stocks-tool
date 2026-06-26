from __future__ import annotations

import argparse
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]

SLICE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "generated_cleanup",
        (
            "artifacts/",
            "output/",
            ".playwright-cli/",
            ".pytest_cache/",
            ".vscode/PythonImportHelper-v2-Completion.json",
            ".gitignore",
            "debug.log",
        ),
    ),
    (
        "operator_status_audit_scheduler",
        (
            "alembic/",
            "src/stocks_tool/db/",
            "src/stocks_tool/repositories/",
            "src/stocks_tool/ports/",
            "src/stocks_tool/adapters/brokers/",
            "src/stocks_tool/application/services/broker_gateway.py",
            "src/stocks_tool/api/routes/ops.py",
            "src/stocks_tool/application/services/operator_consistency.py",
            "src/stocks_tool/application/services/operator_status.py",
            "src/stocks_tool/application/services/reconciliation.py",
            "src/stocks_tool/domain/",
            "src/stocks_tool/main.py",
            "src/stocks_tool/api/dependencies.py",
        ),
    ),
    (
        "strategy_workflow_hardening",
        (
            "src/stocks_tool/api/routes/strategy_routes/",
            "src/stocks_tool/api/routes/strategies.py",
            "src/stocks_tool/application/services/bull_put",
            "src/stocks_tool/application/services/covered_call",
            "src/stocks_tool/application/services/bull_put_strategy.py",
            "src/stocks_tool/application/services/covered_call_strategy.py",
            "src/stocks_tool/application/services/strategy_experiments.py",
            "src/stocks_tool/application/services/strategy_advisor_intake.py",
            "src/stocks_tool/application/services/zero_dte_lottery_strategy.py",
            "src/stocks_tool/application/services/orders.py",
            "src/stocks_tool/application/services/longbridge_integration.py",
        ),
    ),
    (
        "dashboard_mock_regression",
        (
            "src/stocks_tool/api/routes/ui.py",
            "src/stocks_tool/ui/",
            "scripts/",
        ),
    ),
    (
        "docs_tests",
        (
            "docs/",
            "README.md",
            "CODEX.md",
            "tests/",
        ),
    ),
)

GENERATED_PREFIXES = (
    "artifacts/",
    "output/",
    ".playwright-cli/",
    ".pytest_cache/",
)

GENERATED_SEGMENTS = {"__pycache__", ".pytest_cache"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify the current dirty worktree into reviewable release slices."
    )
    parser.add_argument("--json-output", help="Optional file path for the JSON inventory report.")
    return parser.parse_args()


def git_status() -> list[dict[str, str]]:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    entries: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        status = line[:2].strip() or line[:2]
        path = line[3:].replace("\\", "/")
        entries.append({"status": status, "path": path})
    return entries


def classify_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    for slice_name, prefixes in SLICE_RULES:
        if any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in prefixes):
            return slice_name
    return "unknown"


def is_generated_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if any(normalized.startswith(prefix) for prefix in GENERATED_PREFIXES):
        return True
    return bool(GENERATED_SEGMENTS.intersection(normalized.split("/")))


def main() -> None:
    args = parse_args()
    entries = git_status()
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    generated_candidates: list[dict[str, str]] = []
    for entry in entries:
        path = entry["path"]
        grouped[classify_path(path)].append(entry)
        if is_generated_path(path) and entry["status"] != "D":
            generated_candidates.append(entry)

    unknown_paths = grouped.get("unknown", [])
    status = "passed" if not unknown_paths and not generated_candidates else "warning"
    summary = (
        f"Worktree inventory classified {len(entries)} path(s) into "
        f"{len([name for name, paths in grouped.items() if paths])} slice(s)."
    )
    if unknown_paths:
        summary += f" unknown={len(unknown_paths)}."
    if generated_candidates:
        summary += f" generated_candidates={len(generated_candidates)}."

    emit_report(
        build_report(
            script="run_worktree_release_inventory.py",
            workflow="worktree-release-inventory",
            status=status,
            mode="local",
            target=str(ROOT),
            summary=summary,
            payload={
                "path_count": len(entries),
                "slice_counts": {name: len(paths) for name, paths in sorted(grouped.items())},
                "slices": {name: paths for name, paths in sorted(grouped.items())},
                "unknown_paths": unknown_paths,
                "generated_candidates": generated_candidates,
                "review_order": [name for name, _prefixes in SLICE_RULES],
            },
        ),
        json_output=args.json_output,
    )


if __name__ == "__main__":
    main()
