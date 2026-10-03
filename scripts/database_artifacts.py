"""Shared, secret-safe helpers for PostgreSQL backup and isolated restore.

The command-line wrappers deliberately do not load ``.env``.  They use an
explicit ``--database-url`` or the process ``DATABASE_URL`` value, and never
write a password or connection URL to a manifest or diagnostic output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Sequence

import psycopg
from sqlalchemy.engine import URL, make_url


DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/stocks_tool"
MANIFEST_VERSION = 1
CONSTRAINT_COMPARATOR_VERSION = "enum-check-v1"
RESTORE_DATABASE_PREFIX = "stocks_tool_restore_"
_SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,62}$")
_SAFE_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,48}$")
_ENUM_CHECK_PATTERN = re.compile(
    r"^CHECK\s*\(\s*(?P<column>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:::text)?\s*=\s*ANY\s*\(\s*ARRAY\[(?P<values>.*?)\]"
    r"(?:::text\[\])?\s*\)\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_NULLABLE_ENUM_CHECK_PATTERN = re.compile(
    r"^CHECK\s*\(\s*(?P<outer>[A-Za-z_][A-Za-z0-9_]*)\s+IS\s+NULL\s+OR\s*\(\s*"
    r"(?P<column>[A-Za-z_][A-Za-z0-9_]*)(?:::text)?\s*=\s*ANY\s*\(\s*ARRAY\["
    r"(?P<values>.*?)\](?:::text\[\])?\s*\)\s*\)\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ENUM_VALUE_PATTERN = re.compile(
    r"\s*'(?P<literal>(?:''|[^'])*)'\s*::character varying"
    r"(?:\s*::text)?\s*(?P<separator>,|$)",
    re.IGNORECASE | re.DOTALL,
)


def redact_text(value: object, *, max_length: int = 512) -> str:
    """Keep command diagnostics useful without echoing connection secrets."""

    text = str(value)
    text = re.sub(
        r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?token)\s*[:=]\s*[^\s,;&]+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)(?<=://)[^\s/@:]+:[^\s/@]+@", "[REDACTED]@", text)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text[:max_length] + ("..." if len(text) > max_length else "")


class DatabaseArtifactError(RuntimeError):
    """A backup or isolated-restore precondition failed."""


@dataclass(frozen=True)
class DatabaseTarget:
    drivername: str
    username: str | None
    password: str | None
    host: str | None
    port: int | None
    database: str

    @property
    def identity(self) -> dict[str, object]:
        """Non-secret identity safe for a manifest or report."""

        return {
            "driver": self.drivername,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
        }

    def with_database(self, database: str) -> "DatabaseTarget":
        return DatabaseTarget(
            drivername=self.drivername,
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=database,
        )

    def sqlalchemy_url(self) -> URL:
        return URL.create(
            drivername=self.drivername,
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        )


def parse_database_url(value: str) -> DatabaseTarget:
    if not value:
        raise DatabaseArtifactError("A database URL is required.")
    try:
        parsed = make_url(value)
    except Exception as error:
        raise DatabaseArtifactError("The database URL is invalid.") from error
    if not parsed.drivername.startswith("postgresql"):
        raise DatabaseArtifactError("The database URL must use PostgreSQL.")
    if not parsed.database:
        raise DatabaseArtifactError("The database URL must include a database name.")
    return DatabaseTarget(
        drivername="postgresql+psycopg",
        username=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )


def configured_database_url(explicit: str | None) -> str:
    """Resolve only explicit/process configuration; never read ``.env``."""

    return explicit or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def connect(target: DatabaseTarget, *, database: str | None = None):
    selected = target.with_database(database) if database else target
    # psycopg accepts ``postgresql://`` conninfo, while SQLAlchemy's URL keeps
    # the ``+psycopg`` driver suffix.  Build the equivalent driver-neutral
    # conninfo without changing the non-secret identity recorded in manifests.
    conninfo = URL.create(
        drivername="postgresql",
        username=selected.username,
        password=selected.password,
        host=selected.host,
        port=selected.port,
        database=selected.database,
    )
    # ``str(URL)`` masks passwords as ``***``.  Render the conninfo only for
    # the in-process psycopg call; it never leaves this function or appears in
    # a command, manifest, exception, or report.
    return psycopg.connect(conninfo.render_as_string(hide_password=False))


class _QueryResult:
    def __init__(self, rows: list[tuple[str, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[str, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[str, ...] | None:
        return self._rows[0] if self._rows else None


def _render_psql_query(query: object, params: Sequence[object] | None) -> str:
    if not isinstance(query, str):
        raise DatabaseArtifactError("Docker PostgreSQL queries must be plain SQL text.")
    rendered = query
    for value in params or ():
        if isinstance(value, bool):
            literal = "TRUE" if value else "FALSE"
        elif value is None:
            literal = "NULL"
        else:
            literal = "'" + str(value).replace("'", "''") + "'"
        if "%s" not in rendered:
            raise DatabaseArtifactError("The Docker PostgreSQL query has too few placeholders.")
        rendered = rendered.replace("%s", literal, 1)
    if "%s" in rendered:
        raise DatabaseArtifactError("The Docker PostgreSQL query has too many placeholders.")
    return rendered


class DockerDatabaseConnection:
    """Tiny connection-shaped adapter for read-only psql checks in a container."""

    def __init__(
        self,
        *,
        container: str,
        target: DatabaseTarget,
        database: str,
        docker_executable: str = "docker",
        timeout_seconds: float = 120.0,
    ) -> None:
        self.container = container
        self.target = target
        self.database = database
        self.docker_executable = docker_executable
        self.timeout_seconds = timeout_seconds

    def __enter__(self) -> "DockerDatabaseConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: object, params: Sequence[object] | None = None) -> _QueryResult:
        rendered_query = _render_psql_query(query, params)
        command = [
            self.docker_executable,
            "exec",
            self.container,
            "psql",
            "-X",
            "-q",
            "-t",
            "-A",
            "-v",
            "ON_ERROR_STOP=1",
            "--field-separator=\x1f",
            "--record-separator=\x1e",
            "--username",
            self.target.username or "postgres",
            "--dbname",
            self.database,
            "--command",
            rendered_query,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=max(1.0, self.timeout_seconds),
            )
        except subprocess.TimeoutExpired as error:
            raise DatabaseArtifactError("Docker psql timed out.") from error
        except OSError as error:
            raise DatabaseArtifactError("Docker could not be started for psql.") from error
        if result.returncode != 0:
            raise DatabaseArtifactError("Docker psql failed while checking database integrity.")
        raw = result.stdout.strip("\x1e\r\n")
        if not raw:
            return _QueryResult([])
        rows = [
            tuple(field for field in row.split("\x1f"))
            for row in raw.split("\x1e")
            if row
        ]
        return _QueryResult(rows)


def docker_connect(
    target: DatabaseTarget,
    *,
    container: str,
    database: str | None = None,
    docker_executable: str = "docker",
    timeout_seconds: float = 120.0,
) -> DockerDatabaseConnection:
    if not _SAFE_DATABASE_NAME.fullmatch(container):
        raise DatabaseArtifactError("The Docker container name is invalid.")
    return DockerDatabaseConnection(
        container=container,
        target=target,
        database=database or target.database,
        docker_executable=docker_executable,
        timeout_seconds=timeout_seconds,
    )


def run_docker_dump(
    *,
    container: str,
    target: DatabaseTarget,
    output_path: Path,
    docker_executable: str,
    timeout_seconds: float,
) -> None:
    """Stream pg_dump's binary stdout directly to the local dump file."""

    command = [
        docker_executable,
        "exec",
        container,
        "pg_dump",
        "--username",
        target.username or "postgres",
        "--dbname",
        target.database,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output:
        try:
            process = subprocess.Popen(
                command,
                stdout=output,
                stderr=subprocess.PIPE,
            )
            _stdout, stderr = process.communicate(timeout=max(1.0, timeout_seconds))
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait(timeout=5)
            raise DatabaseArtifactError("Docker pg_dump timed out; the partial dump was retained.") from error
        except OSError as error:
            raise DatabaseArtifactError("Docker could not be started for pg_dump.") from error
    if process.returncode != 0:
        raise DatabaseArtifactError("Docker pg_dump failed; the partial dump was retained.")
    if output_path.stat().st_size == 0:
        raise DatabaseArtifactError("Docker pg_dump produced an empty dump.")


def run_docker_restore(
    *,
    container: str,
    target: DatabaseTarget,
    dump_path: Path,
    docker_executable: str,
    timeout_seconds: float,
) -> None:
    """Stream a custom dump through pg_restore stdin without shell quoting."""

    command = [
        docker_executable,
        "exec",
        "-i",
        container,
        "pg_restore",
        "--username",
        target.username or "postgres",
        "--dbname",
        target.database,
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        with dump_path.open("rb") as dump:
            shutil.copyfileobj(dump, process.stdin)
        process.stdin.close()
        # communicate() otherwise attempts to flush the already closed pipe.
        process.stdin = None
        _stdout, _stderr = process.communicate(timeout=max(1.0, timeout_seconds))
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait(timeout=5)
        raise DatabaseArtifactError(
            "Docker pg_restore timed out; the new isolated database was retained."
        ) from error
    except OSError as error:
        raise DatabaseArtifactError("Docker could not be started for pg_restore.") from error
    if process.returncode != 0:
        raise DatabaseArtifactError(
            "Docker pg_restore failed; the new isolated database was retained."
        )


def docker_create_database(
    *,
    container: str,
    target: DatabaseTarget,
    database: str,
    docker_executable: str,
    timeout_seconds: float,
) -> None:
    command = [
        docker_executable,
        "exec",
        container,
        "createdb",
        "--username",
        target.username or "postgres",
        database,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=max(1.0, timeout_seconds),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DatabaseArtifactError("Docker createdb could not complete.") from error
    if result.returncode != 0:
        raise DatabaseArtifactError("Docker createdb failed; no existing database was removed.")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quoted_table(connection, table_name: str) -> str:
    return f"{_quote_identifier('public')}.{_quote_identifier(table_name)}"


def public_table_names(connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def table_fingerprints(connection) -> list[dict[str, object]]:
    fingerprints: list[dict[str, object]] = []
    for table_name in public_table_names(connection):
        column_rows = connection.execute(
            """
            SELECT ordinal_position, column_name, data_type, udt_schema, udt_name,
                   collation_schema, collation_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        ).fetchall()
        columns = [str(row[1]) for row in column_rows]
        column_metadata = [
            {
                "ordinal_position": int(row[0]),
                "name": str(row[1]),
                "data_type": str(row[2]),
                "udt_schema": str(row[3]),
                "udt_name": str(row[4]),
                "collation_schema": str(row[5]) if row[5] else None,
                "collation_name": str(row[6]) if row[6] else None,
            }
            for row in column_rows
        ]
        table = _quoted_table(connection, table_name)
        query = (
            "SELECT count(*)::bigint, "
            "md5(COALESCE(string_agg(md5(row_to_json(t)::text), '' "
            "ORDER BY md5(row_to_json(t)::text)), '')) "
            f"FROM {table} AS t"
        )
        row = connection.execute(query).fetchone()
        fingerprints.append(
            {
                "name": table_name,
                "columns": columns,
                "column_metadata": column_metadata,
                "row_count": int(row[0] or 0),
                "row_digest": str(row[1]),
            }
        )
    return fingerprints


def original_column_projection(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """Extract the pre-migration column set recorded in a backup manifest."""

    projection: dict[str, list[str]] = {}
    for table in manifest.get("tables", []):
        if not isinstance(table, dict):
            continue
        name = table.get("name")
        columns = table.get("columns")
        if isinstance(name, str) and isinstance(columns, list) and all(
            isinstance(column, str) for column in columns
        ):
            projection[name] = list(columns)
    return projection


def table_fingerprints_for_columns(
    connection,
    projection: dict[str, list[str]],
) -> list[dict[str, object]]:
    """Hash only recorded original columns, ignoring additive migration fields."""

    fingerprints: list[dict[str, object]] = []
    for table_name in sorted(projection):
        columns = projection[table_name]
        if not columns:
            raise DatabaseArtifactError(
                f"The original column projection for {table_name!r} is empty."
            )
        selected_columns = ", ".join(_quote_identifier(column) for column in columns)
        table = _quoted_table(connection, table_name)
        query = (
            "SELECT count(*)::bigint, "
            "md5(COALESCE(string_agg(md5(row_to_json(t)::text), '' "
            "ORDER BY md5(row_to_json(t)::text)), '')) "
            f"FROM (SELECT {selected_columns} FROM {table}) AS t"
        )
        row = connection.execute(query).fetchone()
        fingerprints.append(
            {
                "name": table_name,
                "columns": columns,
                "row_count": int(row[0] or 0),
                "row_digest": str(row[1]),
            }
        )
    return fingerprints


def _parse_enum_check(value: str) -> tuple[str, list[str], bool] | None:
    match = _ENUM_CHECK_PATTERN.fullmatch(value)
    nullable = False
    if match is None:
        nullable_match = _NULLABLE_ENUM_CHECK_PATTERN.fullmatch(value)
        if nullable_match is None or nullable_match.group("outer") != nullable_match.group("column"):
            return None
        match = nullable_match
        nullable = True
    values_text = match.group("values")
    values: list[str] = []
    position = 0
    while position < len(values_text):
        value_match = _ENUM_VALUE_PATTERN.match(values_text, position)
        if value_match is None:
            return None
        values.append(value_match.group("literal"))
        position = value_match.end()
        if value_match.group("separator") == "":
            break
    if not values or position != len(values_text):
        return None
    return match.group("column"), values, nullable


def _column_metadata_map(
    tables: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    metadata: dict[tuple[str, str], dict[str, object]] = {}
    for table in tables:
        table_name = table.get("name")
        for column in table.get("column_metadata", []) or []:
            if isinstance(table_name, str) and isinstance(column, dict):
                column_name = column.get("name")
                if isinstance(column_name, str):
                    metadata[(table_name, column_name)] = column
    return metadata


def _canonical_constraint_definition(
    value: str,
    *,
    table_name: str | None = None,
    column_metadata: dict[tuple[str, str], dict[str, object]] | None = None,
) -> str | None:
    """Canonicalize only the supported varchar/text enum-check shape.

    PostgreSQL can add/remove a display-only ``::text`` cast around the column,
    array, or varchar literals after a dump/restore.  No other expression is
    normalized.  In particular, whitespace in literals and casts in numeric or
    expression checks remain untouched.
    """

    parsed = _parse_enum_check(value)
    if parsed is None or table_name is None or column_metadata is None:
        return None
    column_name, values, nullable = parsed
    metadata = column_metadata.get((table_name, column_name))
    if metadata is None or metadata.get("data_type") not in {"character varying", "text"}:
        return None
    rendered_values = ", ".join(
        f"'{literal}'::character varying" for literal in values
    )
    if nullable:
        return f"CHECK ({column_name} IS NULL OR ({column_name} = ANY (ARRAY[{rendered_values}])))"
    return f"CHECK ({column_name} = ANY (ARRAY[{rendered_values}]))"


def constraint_fingerprints(
    connection,
    *,
    tables: list[dict[str, object]],
) -> list[dict[str, object]]:
    column_metadata = _column_metadata_map(tables)
    rows = connection.execute(
        """
        SELECT n.nspname, c.relname, con.conname, con.contype,
               pg_get_constraintdef(con.oid, true)
        FROM pg_catalog.pg_constraint AS con
        JOIN pg_catalog.pg_class AS c ON c.oid = con.conrelid
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
        ORDER BY n.nspname, c.relname, con.conname, con.contype
        """
    ).fetchall()
    fingerprints: list[dict[str, object]] = []
    for row in rows:
        table_name = str(row[1])
        raw_definition = str(row[4])
        normalized_definition = _canonical_constraint_definition(
            raw_definition,
            table_name=table_name,
            column_metadata=column_metadata,
        )
        parsed = _parse_enum_check(raw_definition)
        fingerprints.append(
            {
                "schema": str(row[0]),
                "table": table_name,
                "name": str(row[2]),
                "type": str(row[3]),
                "definition": raw_definition,
                "enum_check_column": parsed[0] if parsed else None,
                "normalized_definition": normalized_definition,
                "normalization": CONSTRAINT_COMPARATOR_VERSION
                if normalized_definition is not None
                else None,
            }
        )
    return fingerprints


def _digest_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def constraint_semantic_records(constraints: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return the identity plus safe normalized/raw definition used for comparison."""

    return [
        {
            "schema": item.get("schema"),
            "table": item.get("table"),
            "name": item.get("name"),
            "type": item.get("type"),
            "definition": item.get("normalized_definition")
            or item.get("definition"),
        }
        for item in constraints
    ]


def database_manifest_snapshot(connection, target: DatabaseTarget) -> dict[str, Any]:
    tables = table_fingerprints(connection)
    constraints = constraint_fingerprints(connection, tables=tables)
    semantic_constraints = constraint_semantic_records(constraints)
    revision_row = connection.execute(
        "SELECT version_num FROM alembic_version LIMIT 1"
    ).fetchone()
    return {
        "database_identity": target.identity,
        "alembic_revision": str(revision_row[0]) if revision_row else None,
        "tables": tables,
        "table_digest": _digest_json(tables),
        "constraints": constraints,
        "constraint_digest": _digest_json(constraints),
        "constraint_semantic_digest": _digest_json(semantic_constraints),
        "constraint_comparator_version": CONSTRAINT_COMPARATOR_VERSION,
    }


def constraints_match(
    expected: list[dict[str, object]],
    actual: list[dict[str, object]],
    *,
    expected_tables: list[dict[str, object]],
    actual_tables: list[dict[str, object]],
    comparator_version: str | None,
) -> tuple[bool, str]:
    """Compare constraints exactly, with one typed enum-check fallback."""

    if len(expected) != len(actual):
        return False, "constraint_count_mismatch"
    expected_by_identity = {
        (item.get("schema"), item.get("table"), item.get("name"), item.get("type")): item
        for item in expected
    }
    actual_by_identity = {
        (item.get("schema"), item.get("table"), item.get("name"), item.get("type")): item
        for item in actual
    }
    if set(expected_by_identity) != set(actual_by_identity):
        return False, "constraint_identity_mismatch"
    expected_columns = _column_metadata_map(expected_tables)
    actual_columns = _column_metadata_map(actual_tables)
    used_fallback = False
    for identity, expected_item in expected_by_identity.items():
        actual_item = actual_by_identity[identity]
        if expected_item.get("definition") == actual_item.get("definition"):
            continue
        if comparator_version != CONSTRAINT_COMPARATOR_VERSION:
            return False, "constraint_raw_definition_mismatch"
        table_name = expected_item.get("table")
        expected_normalized = expected_item.get("normalized_definition")
        actual_normalized = actual_item.get("normalized_definition")
        if isinstance(table_name, str):
            if not isinstance(expected_normalized, str):
                expected_normalized = _canonical_constraint_definition(
                    str(expected_item.get("definition") or ""),
                    table_name=table_name,
                    column_metadata=expected_columns,
                )
            if not isinstance(actual_normalized, str):
                actual_normalized = _canonical_constraint_definition(
                    str(actual_item.get("definition") or ""),
                    table_name=table_name,
                    column_metadata=actual_columns,
                )
        column_name = expected_item.get("enum_check_column")
        if not isinstance(column_name, str) and isinstance(expected_normalized, str):
            parsed = _parse_enum_check(str(expected_item.get("definition") or ""))
            column_name = parsed[0] if parsed else None
        if not (
            isinstance(expected_normalized, str)
            and expected_normalized == actual_normalized
            and isinstance(column_name, str)
            and isinstance(table_name, str)
        ):
            return False, "constraint_definition_mismatch"
        expected_column = expected_columns.get((table_name, column_name))
        actual_column = actual_columns.get((table_name, column_name))
        if expected_column is None or expected_column != actual_column:
            return False, "enum_check_column_metadata_mismatch"
        if expected_column.get("data_type") not in {"character varying", "text"}:
            return False, "enum_check_column_type_unsupported"
        used_fallback = True
    return True, "enum_check_v1" if used_fallback else "exact"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pg_cli_arguments(target: DatabaseTarget, *, database: str | None = None) -> list[str]:
    selected_database = database or target.database
    arguments: list[str] = []
    if target.host:
        arguments.extend(["--host", target.host])
    if target.port:
        arguments.extend(["--port", str(target.port)])
    if target.username:
        arguments.extend(["--username", target.username])
    arguments.extend(["--dbname", selected_database])
    return arguments


def pg_cli_environment(target: DatabaseTarget) -> dict[str, str]:
    environment = dict(os.environ)
    if target.password is not None:
        # The password is scoped to the child process and is never rendered in
        # a command, manifest, exception, or JSON report.
        environment["PGPASSWORD"] = target.password
    return environment


def run_pg_command(
    executable: str,
    arguments: Sequence[str],
    *,
    target: DatabaseTarget,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [executable, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=pg_cli_environment(target),
            timeout=max(1.0, timeout_seconds),
        )
    except subprocess.TimeoutExpired as error:
        raise DatabaseArtifactError(f"{executable} timed out.") from error
    except OSError as error:
        raise DatabaseArtifactError(f"{executable} could not be started.") from error


def ensure_safe_output_name(value: str) -> str:
    if not _SAFE_PREFIX.fullmatch(value):
        raise DatabaseArtifactError("The backup prefix contains unsupported characters.")
    return value


def validate_restore_target(
    target_database: str,
    source_database: str,
    *,
    required_prefix: str = RESTORE_DATABASE_PREFIX,
) -> None:
    if not _SAFE_DATABASE_NAME.fullmatch(target_database):
        raise DatabaseArtifactError("The restore target database name is invalid.")
    if not _SAFE_PREFIX.fullmatch(required_prefix):
        raise DatabaseArtifactError("The restore target prefix is invalid.")
    if target_database == source_database:
        raise DatabaseArtifactError("Refusing to restore over the source database.")
    if target_database in {"stocks_tool", "stocks_tool_paper", "stocks_tool_live"}:
        raise DatabaseArtifactError("Refusing to restore over an operator database.")
    if not target_database.startswith(required_prefix):
        raise DatabaseArtifactError(
            f"The restore target must be a new isolated database beginning with {required_prefix!r}."
        )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
