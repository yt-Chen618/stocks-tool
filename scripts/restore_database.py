"""Restore a PostgreSQL backup into a new isolated database only.

The command refuses operator database names, refuses an existing target, and
never drops a target on verification failure.  An operator can inspect or
remove a failed isolated database manually after the report is reviewed.
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
    CONSTRAINT_COMPARATOR_VERSION,
    constraints_match,
    docker_connect,
    docker_create_database,
    database_manifest_snapshot,
    parse_database_url,
    pg_cli_arguments,
    run_pg_command,
    run_docker_restore,
    redact_text,
    sha256_file,
    validate_restore_target,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore a custom PostgreSQL dump into a new isolated database."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-database", required=True)
    parser.add_argument(
        "--database-url",
        help="Source/maintenance PostgreSQL URL; .env is never loaded.",
    )
    parser.add_argument(
        "--target-database-url",
        help="Optional target server URL. The target database name still comes from --target-database.",
    )
    parser.add_argument(
        "--target-prefix",
        default="stocks_tool_restore_",
        help="Required isolated target prefix.",
    )
    parser.add_argument("--pg-restore", default="pg_restore")
    parser.add_argument(
        "--docker-container",
        help="Run psql/pg_restore inside this existing PostgreSQL container.",
    )
    parser.add_argument("--docker", default="docker", help="Docker executable for --docker-container.")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    return parser.parse_args(argv)


def _manifest_dump_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    dump_file = manifest.get("dump_file")
    if not isinstance(dump_file, str) or not dump_file:
        raise DatabaseArtifactError("The manifest does not identify a dump file.")
    path = manifest_path.parent / dump_file
    if not path.is_file():
        raise DatabaseArtifactError("The manifest dump file is missing.")
    expected_digest = manifest.get("dump_sha256")
    if not isinstance(expected_digest, str) or sha256_file(path) != expected_digest:
        raise DatabaseArtifactError("The dump SHA-256 does not match its manifest.")
    return path


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatabaseArtifactError("The backup manifest cannot be read.") from error
    if not isinstance(manifest, dict) or manifest.get("manifest_version") != 1:
        raise DatabaseArtifactError("The backup manifest version is unsupported.")
    if manifest.get("constraint_comparator_version") != CONSTRAINT_COMPARATOR_VERSION:
        raise DatabaseArtifactError(
            "This legacy manifest has no certified constraint comparator; create a fresh backup."
        )
    if not isinstance(manifest.get("tables"), list) or not isinstance(
        manifest.get("constraints"), list
    ):
        raise DatabaseArtifactError("The backup manifest is missing full integrity fingerprints.")
    return manifest


def _database_exists(target, database_name: str, args: argparse.Namespace) -> bool:
    if args.docker_container:
        connection_factory = lambda: docker_connect(
            target,
            container=args.docker_container,
            database="postgres",
            docker_executable=args.docker,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        connection_factory = lambda: connect(target, database="postgres")
    with connection_factory() as connection:
        row = connection.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
    return row is not None


def _create_isolated_database(target, database_name: str, args: argparse.Namespace) -> None:
    if args.docker_container:
        docker_create_database(
            container=args.docker_container,
            target=target,
            database=database_name,
            docker_executable=args.docker,
            timeout_seconds=args.timeout_seconds,
        )
        return
    from psycopg import sql

    with connect(target, database="postgres") as connection:
        connection.autocommit = True
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )


def restore_database(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.resolve()
    manifest = _load_manifest(manifest_path)
    dump_path = _manifest_dump_path(manifest_path, manifest)
    source_identity = manifest.get("database_identity") or {}
    source_database = str(source_identity.get("database") or "")
    validate_restore_target(
        args.target_database,
        source_database,
        required_prefix=args.target_prefix,
    )

    source = parse_database_url(configured_database_url(args.database_url))
    target = parse_database_url(args.target_database_url) if args.target_database_url else source
    target = target.with_database(args.target_database)
    if _database_exists(target, args.target_database, args):
        raise DatabaseArtifactError(
            "The isolated restore target already exists; refusing to overwrite it."
        )
    _create_isolated_database(target, args.target_database, args)

    if args.docker_container:
        run_docker_restore(
            container=args.docker_container,
            target=target,
            dump_path=dump_path,
            docker_executable=args.docker,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        result = run_pg_command(
            args.pg_restore,
            [
                *pg_cli_arguments(target),
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                str(dump_path),
            ],
            target=target,
            timeout_seconds=args.timeout_seconds,
        )
        if result.returncode != 0:
            raise DatabaseArtifactError(
                "pg_restore failed; the new isolated database was retained for inspection."
            )

    if args.docker_container:
        connection_factory = lambda: docker_connect(
            target,
            container=args.docker_container,
            docker_executable=args.docker,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        connection_factory = lambda: connect(target)
    with connection_factory() as connection:
        actual = database_manifest_snapshot(connection, target)
    expected_tables = manifest.get("tables")
    expected_constraints = manifest.get("constraints")
    if actual["tables"] != expected_tables:
        raise DatabaseArtifactError(
            "Restored table row counts, columns, or digests do not match the manifest."
        )
    constraints_verified, constraint_verification = constraints_match(
        expected_constraints,
        actual["constraints"],
        expected_tables=expected_tables,
        actual_tables=actual["tables"],
        comparator_version=manifest.get("constraint_comparator_version"),
    )
    if not constraints_verified:
        raise DatabaseArtifactError(
            f"Restored constraints do not match the manifest ({constraint_verification})."
        )
    if actual["table_digest"] != manifest.get("table_digest"):
        raise DatabaseArtifactError("Restored table digest does not match the manifest.")
    semantic_digest = manifest.get("constraint_semantic_digest")
    if semantic_digest and actual["constraint_semantic_digest"] != semantic_digest:
        raise DatabaseArtifactError("Restored semantic constraint digest does not match the manifest.")

    return {
        "status": "ok",
        "manifest": str(manifest_path),
        "target_database": target.identity,
        "tables_verified": len(actual["tables"]),
        "table_digest": actual["table_digest"],
        "constraint_digest": actual["constraint_digest"],
        "constraint_semantic_digest": actual["constraint_semantic_digest"],
        "constraint_comparator_version": manifest["constraint_comparator_version"],
        "constraint_verification": constraint_verification,
        "source_database": source_database,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        report = restore_database(parse_args(argv))
    except (DatabaseArtifactError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": "database_restore_failed",
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
                    "error_code": "database_restore_failed",
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
