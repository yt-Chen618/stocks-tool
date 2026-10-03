"""Create a PostgreSQL custom-format backup with an integrity manifest.

This command is explicit and read-oriented from the operator's point of view:
it never loads ``.env`` and never removes an existing backup.  The manifest
contains only non-secret database identity, full table fingerprints, constraint
fingerprints, and a SHA-256 digest of the dump.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database_artifacts import (  # noqa: E402
    DatabaseArtifactError,
    configured_database_url,
    connect,
    docker_connect,
    database_manifest_snapshot,
    ensure_safe_output_name,
    parse_database_url,
    pg_cli_arguments,
    run_pg_command,
    run_docker_dump,
    sha256_file,
    redact_text,
    utc_now,
    write_json,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a secret-safe PostgreSQL custom-format backup and manifest."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/database-backups"),
        help="Directory for the new dump and manifest.",
    )
    parser.add_argument("--database-url", help="Explicit PostgreSQL URL; .env is never loaded.")
    parser.add_argument("--prefix", default="stocks_tool", help="Safe filename prefix.")
    parser.add_argument("--pg-dump", default="pg_dump", help="pg_dump executable.")
    parser.add_argument(
        "--docker-container",
        help="Run pg_dump inside this existing PostgreSQL container (for example stocks-tool-postgres).",
    )
    parser.add_argument("--docker", default="docker", help="Docker executable for --docker-container.")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    return parser.parse_args(argv)


def create_backup(args: argparse.Namespace) -> dict[str, Any]:
    target = parse_database_url(configured_database_url(args.database_url))
    prefix = ensure_safe_output_name(args.prefix)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace("+00:00", "Z").replace(":", "").replace("-", "")
    dump_path = output_dir / f"{prefix}_{stamp}.dump"
    manifest_path = output_dir / f"{dump_path.stem}.manifest.json"
    if dump_path.exists() or manifest_path.exists():
        raise DatabaseArtifactError("The backup artifact already exists; refusing to overwrite it.")

    # Capture a complete before/after fingerprint.  If a scheduler or manual
    # operation changes rows while pg_dump runs, fail closed rather than
    # presenting a dump with an ambiguous point-in-time manifest.
    connection_factory = (
        lambda: docker_connect(
            target,
            container=args.docker_container,
            docker_executable=args.docker,
            timeout_seconds=args.timeout_seconds,
        )
        if args.docker_container
        else connect(target)
    )
    with connection_factory() as connection:
        before = database_manifest_snapshot(connection, target)

    if args.docker_container:
        run_docker_dump(
            container=args.docker_container,
            target=target,
            output_path=dump_path,
            docker_executable=args.docker,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        result = run_pg_command(
            args.pg_dump,
            [
                *pg_cli_arguments(target),
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(dump_path),
            ],
            target=target,
            timeout_seconds=args.timeout_seconds,
        )
        if result.returncode != 0:
            raise DatabaseArtifactError(
                "pg_dump failed; the partial dump was retained for inspection."
            )

    with connection_factory() as connection:
        after = database_manifest_snapshot(connection, target)
    if before["table_digest"] != after["table_digest"] or before["constraint_digest"] != after["constraint_digest"]:
        raise DatabaseArtifactError(
            "Database rows or constraints changed while pg_dump ran; the dump is not certified."
        )

    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "created_at": utc_now(),
        "artifact_type": "postgresql_custom_dump",
        "dump_file": dump_path.name,
        "dump_size_bytes": dump_path.stat().st_size,
        "dump_sha256": sha256_file(dump_path),
        **after,
    }
    write_json(manifest_path, manifest)
    return {
        "status": "ok",
        "dump": str(dump_path),
        "manifest": str(manifest_path),
        "dump_sha256": manifest["dump_sha256"],
        "tables": len(manifest["tables"]),
        "database": target.identity,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        report = create_backup(parse_args(argv))
    except (DatabaseArtifactError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": "database_backup_failed",
                    "error": redact_text(error),
                },
                ensure_ascii=False,
            )
        )
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": "database_backup_failed",
                    "error": redact_text(error),
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
