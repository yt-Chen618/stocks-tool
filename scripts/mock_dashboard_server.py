from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.api.routes import ui  # noqa: E402


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_price(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.4f}"


class MockDashboardState:
    def __init__(self) -> None:
        self.account_id = "LBPT10087357"
        self.symbol = "MOCK.US"
        self._order_counter = 1000
        self.account = {
            "id": "mock-account-1",
            "broker": "longbridge",
            "external_account_id": self.account_id,
            "display_name": "Longbridge Paper",
            "base_currency": "USD",
            "mode": "paper",
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
        }
        self.watchlists = [
            {
                "id": "mock-watchlist-1",
                "name": "core-us",
                "items": [
                    {"symbol": "MOCK.US", "asset_type": "stock", "notes": "ui regression seed"},
                    {"symbol": "UNH.US", "asset_type": "stock", "notes": "real paper validation symbol"},
                ],
            }
        ]
        self.configuration = {
            "app_key_configured": True,
            "app_secret_configured": True,
            "paper_token_configured": True,
            "live_token_configured": False,
        }
        self.quote = {
            "symbol": self.symbol,
            "last_done": "400.000",
            "prev_close": "398.000",
            "open": "399.500",
            "high": "401.250",
            "low": "397.750",
            "timestamp": "2026-05-21T04:00:00Z",
            "volume": 1250000,
            "turnover": "500000000.000",
            "trade_status": "TradeStatus.Normal",
            "pre_market_quote": None,
            "post_market_quote": None,
            "overnight_quote": None,
        }
        self.snapshot = {
            "id": "mock-snapshot-1",
            "broker_account_id": "mock-account-1",
            "external_account_id": self.account_id,
            "currency": "USD",
            "cash_balance": "1912918.1200",
            "net_liquidation": "1916739.1200",
            "buying_power": "1915590.7800",
            "captured_at": "2026-05-21T02:14:52Z",
            "created_at": "2026-05-21T02:14:52Z",
            "positions": [
                {
                    "symbol": self.symbol,
                    "asset_type": "stock",
                    "quantity": 10,
                    "average_cost": "395.0000",
                    "market_value": "4000.0000",
                    "unrealized_pnl": "50.0000",
                }
            ],
        }
        self.orders = [
            self._build_order(
                local_order_id="mock-order-0001",
                external_order_id="mock-external-0001",
                quantity=1,
                limit_price=301.0,
                status_value="canceled",
                submitted_at="2026-05-20T20:07:13Z",
                updated_at="2026-05-20T20:07:19Z",
                remark="historical canceled seed",
            ),
            self._build_order(
                local_order_id="mock-order-0002",
                external_order_id="mock-external-0002",
                quantity=10,
                limit_price=389.24,
                status_value="filled",
                submitted_at="2026-05-20T19:53:15Z",
                updated_at="2026-05-20T19:53:15Z",
                remark="historical filled seed",
            ),
        ]

    def _build_order(
        self,
        *,
        local_order_id: str,
        external_order_id: str,
        quantity: int,
        limit_price: float | None,
        status_value: str,
        submitted_at: str,
        updated_at: str,
        remark: str,
        stop_price: float | None = None,
    ) -> dict[str, Any]:
        return {
            "id": local_order_id,
            "broker": "longbridge",
            "external_account_id": self.account_id,
            "trade_plan_id": None,
            "external_order_id": external_order_id,
            "client_order_id": f"client-{local_order_id}",
            "symbol": self.symbol,
            "asset_type": "stock",
            "side": "buy",
            "quantity": quantity,
            "order_type": "limit" if limit_price is not None else "market",
            "time_in_force": "day",
            "mode": "paper",
            "status": status_value,
            "limit_price": format_price(limit_price),
            "stop_price": format_price(stop_price),
            "option_contract": None,
            "raw_payload": {
                "remote_order": {
                    "order_id": external_order_id,
                    "symbol": self.symbol,
                    "status": status_value.upper(),
                    "quantity": str(quantity),
                    "price": f"{limit_price:.2f}" if limit_price is not None else None,
                },
                "submission_request": {
                    "external_account_id": self.account_id,
                    "symbol": self.symbol,
                    "side": "buy",
                    "quantity": quantity,
                    "order_type": "limit" if limit_price is not None else "market",
                    "time_in_force": "day",
                    "mode": "paper",
                    "limit_price": f"{limit_price:.2f}" if limit_price is not None else None,
                    "remark": remark,
                },
            },
            "submitted_at": submitted_at,
            "created_at": submitted_at,
            "updated_at": updated_at,
        }

    def list_orders(self, external_account_id: str | None) -> list[dict[str, Any]]:
        if external_account_id and external_account_id != self.account_id:
            return []
        return deepcopy(sorted(self.orders, key=lambda item: item["updated_at"], reverse=True))

    def get_order(self, order_id: str) -> dict[str, Any]:
        for order in self.orders:
            if order["id"] == order_id:
                return order
        raise KeyError(order_id)

    def submit_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._order_counter += 1
        now = iso_now()
        order = self._build_order(
            local_order_id=f"mock-order-{self._order_counter}",
            external_order_id=f"mock-external-{self._order_counter}",
            quantity=int(payload["quantity"]),
            limit_price=float(payload["limit_price"]) if payload.get("limit_price") is not None else None,
            stop_price=float(payload["stop_price"]) if payload.get("stop_price") is not None else None,
            status_value="submitted",
            submitted_at=now,
            updated_at=now,
            remark=str(payload.get("remark") or "mock submit"),
        )
        order["symbol"] = str(payload.get("symbol") or self.symbol).upper()
        order["side"] = str(payload.get("side") or "buy")
        order["order_type"] = str(payload.get("order_type") or "limit")
        order["time_in_force"] = str(payload.get("time_in_force") or "day")
        order["raw_payload"]["remote_order"]["symbol"] = order["symbol"]
        order["raw_payload"]["remote_order"]["side"] = order["side"].upper()
        order["raw_payload"]["remote_order"]["order_type"] = order["order_type"].upper()
        order["raw_payload"]["submission_request"].update(
            {
                "symbol": order["symbol"],
                "side": order["side"],
                "quantity": order["quantity"],
                "order_type": order["order_type"],
                "time_in_force": order["time_in_force"],
                "limit_price": f"{float(payload['limit_price']):.2f}" if payload.get("limit_price") is not None else None,
                "stop_price": f"{float(payload['stop_price']):.2f}" if payload.get("stop_price") is not None else None,
            }
        )
        self.orders.insert(0, order)
        return deepcopy(order)

    def replace_order(self, order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        order = self.get_order(order_id)
        if order["status"] not in {"created", "submitted", "partially_filled"}:
            raise ValueError("Only working orders can be replaced.")
        order["quantity"] = int(payload["quantity"])
        order["limit_price"] = format_price(float(payload["limit_price"])) if payload.get("limit_price") is not None else None
        order["stop_price"] = format_price(float(payload["stop_price"])) if payload.get("stop_price") is not None else None
        order["updated_at"] = iso_now()
        order["raw_payload"]["remote_order"]["status"] = "REPLACEDNOTREPORTED"
        order["raw_payload"]["remote_order"]["quantity"] = str(order["quantity"])
        order["raw_payload"]["remote_order"]["price"] = (
            f"{float(payload['limit_price']):.2f}" if payload.get("limit_price") is not None else None
        )
        if payload.get("remark") is not None:
            order["raw_payload"]["replace_request"] = {"remark": payload["remark"]}
        return deepcopy(order)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        if order["status"] not in {"created", "submitted", "partially_filled"}:
            raise ValueError("Only working orders can be canceled.")
        order["status"] = "canceled"
        order["updated_at"] = iso_now()
        order["raw_payload"]["remote_order"]["status"] = "CANCELED"
        order["raw_payload"]["remote_order"]["last_done"] = (
            f"{float(order['limit_price']):.2f}" if order["limit_price"] is not None else None
        )
        return deepcopy(order)


def create_app() -> FastAPI:
    state = MockDashboardState()
    app = FastAPI(title="Mock Stocks Tool Dashboard", docs_url="/docs", redoc_url=None)
    static_dir = ROOT / "src" / "stocks_tool" / "ui" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(ui.router)

    @app.get("/broker-accounts")
    def broker_accounts() -> list[dict[str, Any]]:
        return [deepcopy(state.account)]

    @app.get("/watchlists")
    def watchlists() -> list[dict[str, Any]]:
        return deepcopy(state.watchlists)

    @app.get("/brokers/longbridge/configuration")
    def longbridge_configuration() -> dict[str, Any]:
        return deepcopy(state.configuration)

    @app.get("/brokers/longbridge/quote")
    def quote(symbol: str = Query(...), mode: str = Query("paper")) -> dict[str, Any]:
        data = deepcopy(state.quote)
        data["symbol"] = symbol.upper()
        data["mode"] = mode
        return data

    @app.get("/account-snapshots")
    def account_snapshots(external_account_id: str = Query(...)) -> list[dict[str, Any]]:
        if external_account_id != state.account_id:
            return []
        return [deepcopy(state.snapshot)]

    @app.get("/orders")
    def orders(external_account_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
        return state.list_orders(external_account_id)

    @app.get("/orders/{order_id}")
    def get_order(order_id: str) -> dict[str, Any]:
        try:
            return deepcopy(state.get_order(order_id))
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' was not found.") from error

    @app.post("/orders/submit", status_code=status.HTTP_201_CREATED)
    def submit_order(payload: dict[str, Any]) -> dict[str, Any]:
        return state.submit_order(payload)

    @app.post("/orders/{order_id}/refresh")
    def refresh_order(order_id: str) -> dict[str, Any]:
        try:
            return deepcopy(state.get_order(order_id))
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' was not found.") from error

    @app.post("/orders/{order_id}/replace")
    def replace_order(order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return state.replace_order(order_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' was not found.") from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    @app.post("/orders/{order_id}/cancel")
    def cancel_order(order_id: str) -> dict[str, Any]:
        try:
            return state.cancel_order(order_id)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' was not found.") from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    @app.post("/brokers/longbridge/account-sync/{external_account_id}")
    def sync_account(external_account_id: str, mode: str = Query("paper")) -> dict[str, Any]:
        return {
            "external_account_id": external_account_id,
            "mode": mode,
            "snapshot_id": state.snapshot["id"],
            "positions_synced": len(state.snapshot["positions"]),
            "captured_at": state.snapshot["captured_at"],
        }

    @app.post("/orders/sync/longbridge/{external_account_id}")
    def sync_orders(external_account_id: str, mode: str = Query("paper")) -> dict[str, Any]:
        return {
            "external_account_id": external_account_id,
            "mode": mode,
            "orders_synced": len(state.orders),
        }

    return app


app = create_app()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve a mock Stocks Tool dashboard backend for UI regression.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
