from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.core.config import get_settings  # noqa: E402


def compare_heads(script_heads: tuple[str, ...], current_heads: tuple[str, ...]) -> bool:
    return len(script_heads) == 1 and current_heads == script_heads


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail unless the database is at the repository's single Alembic head."
    )
    parser.add_argument("--json-output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = Config(str(ROOT / "alembic.ini"))
    script_heads = tuple(sorted(ScriptDirectory.from_config(config).get_heads()))
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as connection:
            current_heads = tuple(
                sorted(MigrationContext.configure(connection).get_current_heads())
            )
    finally:
        engine.dispose()

    matched = compare_heads(script_heads, current_heads)
    payload = {
        "status": "passed" if matched else "failed",
        "script_heads": list(script_heads),
        "database_current_heads": list(current_heads),
        "single_head_current_match": matched,
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
