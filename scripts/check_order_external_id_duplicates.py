from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.application.services.order_preflight import (  # noqa: E402
    find_duplicate_external_order_ids,
)
from stocks_tool.core.config import get_settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only duplicate external order id audit.")
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            duplicates = find_duplicate_external_order_ids(connection)
    finally:
        engine.dispose()

    payload = {
        "status": "failed" if duplicates else "passed",
        "check": "order_external_id_uniqueness",
        "duplicate_count": len(duplicates),
        "duplicates": [item.to_dict() for item in duplicates],
        "read_only": True,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 1 if duplicates else 0


if __name__ == "__main__":
    raise SystemExit(main())
