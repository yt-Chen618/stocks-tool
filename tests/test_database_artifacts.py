import pytest

from scripts.database_artifacts import (
    CONSTRAINT_COMPARATOR_VERSION,
    DatabaseArtifactError,
    constraints_match,
    parse_database_url,
    pg_cli_arguments,
    pg_cli_environment,
    original_column_projection,
    _canonical_constraint_definition,
    validate_restore_target,
)
import scripts.database_artifacts as database_artifacts


def test_database_manifest_identity_never_contains_password() -> None:
    target = parse_database_url(
        "postgresql+psycopg://operator:super-secret@127.0.0.1:5432/stocks_tool"
    )
    assert target.identity == {
        "driver": "postgresql+psycopg",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "stocks_tool",
        "username": "operator",
    }
    assert "super-secret" not in repr(target.identity)


def test_pg_cli_keeps_password_out_of_arguments_but_scopes_it_to_child_env() -> None:
    target = parse_database_url(
        "postgresql+psycopg://operator:super-secret@127.0.0.1:5432/stocks_tool"
    )
    arguments = pg_cli_arguments(target)
    assert "super-secret" not in arguments
    environment = pg_cli_environment(target)
    assert environment["PGPASSWORD"] == "super-secret"


def test_psycopg_connection_renders_password_only_inside_connection_call(monkeypatch) -> None:
    captured: list[str] = []

    def fake_connect(conninfo: str):
        captured.append(conninfo)
        return object()

    monkeypatch.setattr(database_artifacts.psycopg, "connect", fake_connect)
    target = parse_database_url(
        "postgresql+psycopg://operator:super-secret@127.0.0.1:5432/stocks_tool"
    )
    database_artifacts.connect(target)
    assert captured == [
        "postgresql://operator:super-secret@127.0.0.1:5432/stocks_tool"
    ]


@pytest.mark.parametrize("name", ["stocks_tool", "stocks_tool_paper", "stocks_tool_live"])
def test_restore_rejects_operator_database(name: str) -> None:
    with pytest.raises(DatabaseArtifactError):
        validate_restore_target(name, "old_backup_database")


def test_restore_requires_new_isolated_prefix() -> None:
    with pytest.raises(DatabaseArtifactError, match="isolated"):
        validate_restore_target("stocks_tool_copy", "stocks_tool")
    with pytest.raises(DatabaseArtifactError, match="source"):
        validate_restore_target("stocks_tool_restore_source", "stocks_tool_restore_source")


def test_restore_accepts_new_isolated_database() -> None:
    validate_restore_target("stocks_tool_restore_20261004", "stocks_tool")


def test_original_column_projection_ignores_unrelated_additive_columns() -> None:
    manifest = {
        "tables": [
            {"name": "orders", "columns": ["id", "created_at"]},
            {"name": "empty", "columns": []},
            {"name": 42, "columns": ["ignored"]},
        ]
    }
    assert original_column_projection(manifest) == {
        "orders": ["id", "created_at"],
        "empty": [],
    }


def test_constraint_normalization_is_limited_to_display_only_varchar_array_casts() -> None:
    source = "CHECK (state::text = ANY (ARRAY['open'::character varying]::text[]))"
    restored = "CHECK (state = ANY (ARRAY['open'::character varying::text]))"
    metadata = {("orders", "state"): {"data_type": "character varying"}}
    assert _canonical_constraint_definition(
        source,
        table_name="orders",
        column_metadata=metadata,
    ) == _canonical_constraint_definition(
        restored,
        table_name="orders",
        column_metadata=metadata,
    )
    assert "open" in _canonical_constraint_definition(
        source,
        table_name="orders",
        column_metadata=metadata,
    )


def test_constraint_normalization_rejects_numeric_text_casts() -> None:
    expression = "CHECK (quantity::text = ANY (ARRAY['1'::character varying]::text[]))"
    metadata = {("orders", "quantity"): {"data_type": "integer"}}
    assert _canonical_constraint_definition(
        expression,
        table_name="orders",
        column_metadata=metadata,
    ) is None


def test_constraint_normalization_preserves_literal_spaces_and_rejects_different_values() -> None:
    source = "CHECK (state::text = ANY (ARRAY['open  state'::character varying]::text[]))"
    same_literal = "CHECK (state = ANY (ARRAY['open  state'::character varying::text]))"
    different_literal = "CHECK (state = ANY (ARRAY['open state'::character varying::text]))"
    metadata = {("orders", "state"): {"data_type": "text"}}
    normalized_source = _canonical_constraint_definition(
        source,
        table_name="orders",
        column_metadata=metadata,
    )
    assert normalized_source == "CHECK (state = ANY (ARRAY['open  state'::character varying]))"
    assert normalized_source == _canonical_constraint_definition(
        same_literal,
        table_name="orders",
        column_metadata=metadata,
    )
    assert normalized_source != _canonical_constraint_definition(
        different_literal,
        table_name="orders",
        column_metadata=metadata,
    )


def test_constraint_normalization_supports_only_typed_nullable_enum_checks() -> None:
    source = "CHECK (state IS NULL OR (state::text = ANY (ARRAY['open'::character varying]::text[])))"
    restored = "CHECK (state IS NULL OR (state = ANY (ARRAY['open'::character varying::text])))"
    metadata = {("orders", "state"): {"data_type": "character varying"}}
    expected = "CHECK (state IS NULL OR (state = ANY (ARRAY['open'::character varying])))"
    assert _canonical_constraint_definition(
        source,
        table_name="orders",
        column_metadata=metadata,
    ) == expected
    assert _canonical_constraint_definition(
        restored,
        table_name="orders",
        column_metadata=metadata,
    ) == expected
    assert _canonical_constraint_definition(
        "CHECK (other IS NULL OR (state::text = ANY (ARRAY['open'::character varying]::text[])))",
        table_name="orders",
        column_metadata=metadata,
    ) is None


def test_constraint_normalization_rejects_non_any_arrays_and_other_expressions() -> None:
    metadata = {("orders", "state"): {"data_type": "character varying"}}
    assert _canonical_constraint_definition(
        "CHECK (state::text IN (ARRAY['open'::character varying]))",
        table_name="orders",
        column_metadata=metadata,
    ) is None
    expression = "CHECK (state::text || '-suffix' = 'open-suffix')"
    assert _canonical_constraint_definition(
        expression,
        table_name="orders",
        column_metadata=metadata,
    ) is None


def test_constraint_comparator_requires_identical_typed_column_metadata() -> None:
    expected = [
        {
            "schema": "public",
            "table": "orders",
            "name": "ck_orders_state",
            "type": "c",
            "definition": "CHECK (state::text = ANY (ARRAY['open'::character varying]::text[]))",
            "enum_check_column": "state",
            "normalized_definition": "CHECK (state = ANY (ARRAY['open'::character varying]))",
            "normalization": CONSTRAINT_COMPARATOR_VERSION,
        }
    ]
    actual = [
        {
            **expected[0],
            "definition": "CHECK (state = ANY (ARRAY['open'::character varying::text]))",
        }
    ]
    tables = [
        {
            "name": "orders",
            "column_metadata": [
                {
                    "name": "state",
                    "data_type": "character varying",
                    "udt_schema": "pg_catalog",
                    "udt_name": "varchar",
                    "collation_schema": "pg_catalog",
                    "collation_name": "default",
                }
            ],
        }
    ]
    assert constraints_match(
        expected,
        actual,
        expected_tables=tables,
        actual_tables=tables,
        comparator_version=CONSTRAINT_COMPARATOR_VERSION,
    ) == (True, "enum_check_v1")
    different_values = [{**actual[0], "normalized_definition": "CHECK (state = ANY (ARRAY['closed'::character varying]))"}]
    assert constraints_match(
        expected,
        different_values,
        expected_tables=tables,
        actual_tables=tables,
        comparator_version=CONSTRAINT_COMPARATOR_VERSION,
    )[0] is False
    changed_collation = [
        {
            **tables[0],
            "column_metadata": [
                {
                    **tables[0]["column_metadata"][0],
                    "collation_name": "C",
                }
            ],
        }
    ]
    assert constraints_match(
        expected,
        actual,
        expected_tables=tables,
        actual_tables=changed_collation,
        comparator_version=CONSTRAINT_COMPARATOR_VERSION,
    ) == (False, "enum_check_column_metadata_mismatch")
