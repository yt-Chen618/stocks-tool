from __future__ import annotations

import json
import socket
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_workbench_feature_regression import (  # noqa: E402
    RESERVED_PORTS,
    allocate_free_port,
    parse_browser_payload,
    source_identity,
)


def test_allocate_free_port_excludes_normal_gate_reservations() -> None:
    port = allocate_free_port()
    assert port not in RESERVED_PORTS
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_parse_browser_payload_uses_last_json_record() -> None:
    payload = {"rendered": True, "request_audit": {"broker_mutations": []}}
    stdout = "diagnostic line\n" + json.dumps({"rendered": False}) + "\n" + json.dumps(payload) + "\n"
    assert parse_browser_payload(stdout) == payload


def test_source_identity_covers_owned_flow_and_fixture_sources() -> None:
    identity = source_identity()
    assert len(identity["aggregate_sha256"]) == 64
    assert identity["file_count"] >= 25
    assert identity["files"]["scripts/workbench_feature_browser_flow.js"]
    assert identity["files"]["scripts/mock_dashboard_fixtures.py"]
    assert identity["files"]["scripts/mock_workbench_routes.py"]
    assert identity["files"]["scripts/mock_market_session_routes.py"]
    assert identity["files"]["src/stocks_tool/application/services/market_session_comparison.py"]
    assert identity["files"]["src/stocks_tool/domain/market_session_comparisons.py"]
    assert identity["files"]["src/stocks_tool/ui/static/account-loader.js"]
    assert identity["files"]["src/stocks_tool/ui/static/market-session-comparison-view.js"]
    assert identity["files"]["src/stocks_tool/ui/static/workbench-ui.js"]
    assert identity["files"]["src/stocks_tool/ui/static/workbench-redesign.css"]
    assert identity["files"]["src/stocks_tool/ui/static/workspace.css"]
    assert identity["files"]["src/stocks_tool/ui/static/app.css"]
    assert ".env" not in "\n".join(identity["files"])
