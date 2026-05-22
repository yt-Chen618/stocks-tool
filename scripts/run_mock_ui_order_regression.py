from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8765


class RegressionError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a mock dashboard regression against a local in-memory backend. "
            "This validates the rendered dashboard shell plus submit/replace/cancel order flow "
            "without touching the real paper account."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="Mock server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Mock server port.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP timeout and step deadline.")
    parser.add_argument("--poll-seconds", type=float, default=0.5, help="Polling interval for mock state checks.")
    parser.add_argument("--keep-server", action="store_true", help="Leave the mock server running after the script exits.")
    parser.add_argument("--json-output", help="Optional file path for the JSON regression report.")
    return parser.parse_args()


def start_server(host: str, port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "mock_dashboard_server.py"),
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_server(base_url: str, timeout_seconds: float, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            output = ""
            if process.stdout is not None:
                output = process.stdout.read()
            raise RegressionError(f"Mock server exited early.\nServer output:\n{output}")
        try:
            response = httpx.get(base_url, timeout=2.0)
            if response.status_code == 200:
                return
        except Exception as error:  # pragma: no cover - transient bootstrap noise
            last_error = str(error)
        time.sleep(0.25)
    raise RegressionError(f"Mock server did not become ready at {base_url}: {last_error}")


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
    raise RegressionError(detail)


def wait_for(
    client: httpx.Client,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    predicate,
    label: str,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_orders: list[dict[str, Any]] = []
    while time.time() < deadline:
        last_orders = require_ok(client.get("/orders", params={"external_account_id": "LBPT10087357"}))
        for order in last_orders:
            if predicate(order):
                return order
        time.sleep(poll_seconds)
    raise RegressionError(f"Timed out waiting for {label}. Last orders payload: {last_orders}")


def main() -> None:
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"
    server = start_server(args.host, args.port)

    try:
        wait_for_server(f"{base_url}/", args.timeout_seconds, server)
        client = httpx.Client(base_url=base_url, timeout=args.timeout_seconds)
        try:
            dashboard = client.get("/")
            dashboard.raise_for_status()
            assert "Holdings Overview" in dashboard.text
            assert "Current Holdings" in dashboard.text
            assert "Order Ticket" in dashboard.text
            assert "Selected Order" in dashboard.text
            assert "Execution Summary" in dashboard.text
            assert "Orders" in dashboard.text

            app_js = client.get("/static/app.js")
            app_js.raise_for_status()
            for marker in (
                "order-ticket-form",
                "replace-order-form",
                "selected-order-card",
                "selected-order-execution",
                "submitOrder()",
                "replaceSelectedOrder()",
                "renderSelectedExecution()",
            ):
                assert marker in app_js.text

            accounts = require_ok(client.get("/broker-accounts"))
            assert accounts[0]["external_account_id"] == "LBPT10087357"
            assert accounts[0]["auto_reconcile_enabled"] is True

            snapshots = require_ok(client.get("/account-snapshots", params={"external_account_id": "LBPT10087357"}))
            assert snapshots[0]["positions"][0]["symbol"] == "MOCK.US"

            initial_orders = require_ok(client.get("/orders", params={"external_account_id": "LBPT10087357"}))
            assert len(initial_orders) == 2
            initial_executions = require_ok(client.get("/executions", params={"external_account_id": "LBPT10087357"}))
            assert len(initial_executions) == 1
            assert initial_executions[0]["order_id"] == "mock-order-0002"

            created = require_ok(
                client.post(
                    "/orders/submit",
                    json={
                        "external_account_id": "LBPT10087357",
                        "symbol": "MOCK.US",
                        "side": "buy",
                        "quantity": 1,
                        "order_type": "limit",
                        "time_in_force": "day",
                        "mode": "paper",
                        "limit_price": 320.0,
                        "remark": "mock-ui-submit",
                    },
                )
            )
            submitted = wait_for(
                client,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
                predicate=lambda order: (
                    order["id"] == created["id"]
                    and order["status"] == "submitted"
                    and order["quantity"] == 1
                    and order["limit_price"] == "320.0000"
                ),
                label="submitted mock order",
            )

            replaced = require_ok(
                client.post(
                    f"/orders/{created['id']}/replace",
                    json={"quantity": 2, "limit_price": 321.0, "remark": "mock-ui-replace"},
                )
            )
            replaced = wait_for(
                client,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
                predicate=lambda order: (
                    order["id"] == created["id"]
                    and order["status"] == "submitted"
                    and order["quantity"] == 2
                    and order["limit_price"] == "321.0000"
                ),
                label="replaced mock order",
            )

            canceled = require_ok(client.post(f"/orders/{created['id']}/cancel"))
            canceled = wait_for(
                client,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
                predicate=lambda order: order["id"] == created["id"] and order["status"] == "canceled",
                label="canceled mock order",
            )

            emit_report(
                build_report(
                    script="run_mock_ui_order_regression.py",
                    workflow="mock-dashboard-order-regression",
                    status="passed",
                    mode="mock",
                    target=base_url,
                    summary="Mock dashboard shell plus submit/replace/cancel order flow passed.",
                    payload={
                        "checks": {
                            "dashboard_shell": True,
                            "execution_summary_shell": True,
                            "app_js_markers": True,
                            "account_seed": True,
                            "snapshot_seed": True,
                            "execution_seed": True,
                        },
                        "order": {
                            "local_order_id": created["id"],
                            "external_order_id": created["external_order_id"],
                            "submitted_status": submitted["status"],
                            "replaced_limit": replaced["limit_price"],
                            "replaced_quantity": replaced["quantity"],
                            "final_status": canceled["status"],
                        },
                    },
                ),
                json_output=args.json_output,
            )
        finally:
            client.close()
    except Exception as error:
        emit_report(
            build_report(
                script="run_mock_ui_order_regression.py",
                workflow="mock-dashboard-order-regression",
                status="failed",
                mode="mock",
                target=base_url,
                summary="Mock dashboard regression failed.",
                error=str(error),
            ),
            json_output=args.json_output,
        )
        raise
    finally:
        if not args.keep_server:
            stop_server(server)


if __name__ == "__main__":
    main()
