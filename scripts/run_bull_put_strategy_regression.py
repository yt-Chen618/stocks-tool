from __future__ import annotations

import argparse
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from regression_common import build_report, emit_report

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    SpreadStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerAccount,
    BullPutSpread,
    BullPutStrategyRuntimeState,
    CreateJournalEntryRequest,
    ExecuteBullPutSpreadRequest,
    HistoricalPriceBar,
    OptionChainEntry,
    OptionContractRef,
    OptionMarketSnapshot,
    Order,
    SecurityQuoteSnapshot,
)


@dataclass
class InMemoryRuntimeRepository:
    state: BullPutStrategyRuntimeState | None = None

    def get_runtime_state(
        self,
        *,
        external_account_id: str,
        strategy_id: str = "paper_bull_put_v1",
    ) -> BullPutStrategyRuntimeState | None:
        if self.state is None:
            return None
        if self.state.external_account_id != external_account_id or self.state.strategy_id != strategy_id:
            return None
        return self.state

    def upsert_runtime_state(self, state: BullPutStrategyRuntimeState) -> BullPutStrategyRuntimeState:
        self.state = state
        return state


@dataclass
class InMemorySpreadRepository:
    items: dict[str, BullPutSpread]

    def create_spread(self, spread: BullPutSpread) -> BullPutSpread:
        self.items[spread.id] = spread
        return spread

    def get_spread(self, spread_id: str) -> BullPutSpread | None:
        return self.items.get(spread_id)

    def list_spreads(
        self,
        external_account_id: str | None = None,
        status: SpreadStatus | None = None,
    ) -> list[BullPutSpread]:
        rows = list(self.items.values())
        if external_account_id is not None:
            rows = [row for row in rows if row.external_account_id == external_account_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return sorted(rows, key=lambda row: row.updated_at, reverse=True)

    def update_spread(self, spread: BullPutSpread) -> BullPutSpread:
        self.items[spread.id] = spread
        return spread


class InMemoryJournalService:
    def __init__(self) -> None:
        self.entries: list[CreateJournalEntryRequest] = []

    def create_entry(self, request: CreateJournalEntryRequest) -> CreateJournalEntryRequest:
        self.entries.append(request)
        return request


class StaticBrokerAccounts:
    def __init__(self, account: BrokerAccount) -> None:
        self.account = account

    def get_by_external_account_id(self, external_account_id: str) -> BrokerAccount | None:
        if external_account_id == self.account.external_account_id:
            return self.account
        return None


class StaticSnapshots:
    def __init__(self, snapshot: AccountSnapshot) -> None:
        self.snapshot = snapshot

    def list_account_snapshots(self, external_account_id: str | None = None) -> list[AccountSnapshot]:
        if external_account_id is not None and external_account_id != self.snapshot.account_id:
            return []
        return [self.snapshot]


class FakeAdapter:
    def __init__(self) -> None:
        self.exit_phase = False

    def get_quote(self, *, symbol: str, mode: ExecutionMode) -> SecurityQuoteSnapshot:
        if self.exit_phase:
            last_done = Decimal("501.25")
        else:
            last_done = Decimal("500.00")
        return SecurityQuoteSnapshot(
            symbol=symbol,
            last_done=last_done,
            prev_close=Decimal("498.00"),
            open=Decimal("499.00"),
            high=Decimal("502.00"),
            low=Decimal("497.00"),
            timestamp=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
            volume=1_000_000,
            turnover=Decimal("500000000"),
            trade_status="Normal",
        )

    def get_recent_daily_bars(self, *, symbol: str, count: int, mode: ExecutionMode) -> list[HistoricalPriceBar]:
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        bars: list[HistoricalPriceBar] = []
        for offset in range(count):
            close = Decimal("400") + Decimal(offset)
            bars.append(
                HistoricalPriceBar(
                    symbol=symbol,
                    timestamp=start + timedelta(days=offset),
                    open=close - Decimal("1"),
                    high=close + Decimal("2"),
                    low=close - Decimal("2"),
                    close=close,
                    volume=1000 + offset,
                    turnover=close * Decimal("1000"),
                )
            )
        return bars

    def list_option_expiry_dates(self, *, symbol: str, mode: ExecutionMode) -> list[date]:
        return [date(2026, 6, 19)]

    def list_option_chain(self, *, symbol: str, expiry_date: date, mode: ExecutionMode) -> list[OptionChainEntry]:
        return [
            OptionChainEntry(strike=Decimal("470"), call_symbol="QQQ260619C470000.US", put_symbol="QQQ260619P470000.US", standard=True),
            OptionChainEntry(strike=Decimal("467"), call_symbol="QQQ260619C467000.US", put_symbol="QQQ260619P467000.US", standard=True),
            OptionChainEntry(strike=Decimal("464"), call_symbol="QQQ260619C464000.US", put_symbol="QQQ260619P464000.US", standard=True),
        ]

    def get_option_market_snapshots(self, *, symbols: list[str], mode: ExecutionMode) -> list[OptionMarketSnapshot]:
        timestamp = datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc)
        price_map = {
            "QQQ260619P470000.US": Decimal("2.50"),
            "QQQ260619P467000.US": Decimal("1.05"),
            "QQQ260619P464000.US": Decimal("0.70"),
        }
        if self.exit_phase:
            price_map = {
                "QQQ260619P470000.US": Decimal("0.75"),
                "QQQ260619P467000.US": Decimal("0.35"),
                "QQQ260619P464000.US": Decimal("0.25"),
            }
        deltas = {
            "QQQ260619P470000.US": Decimal("-0.22"),
            "QQQ260619P467000.US": Decimal("-0.16"),
            "QQQ260619P464000.US": Decimal("-0.12"),
        }
        strikes = {
            "QQQ260619P470000.US": Decimal("470"),
            "QQQ260619P467000.US": Decimal("467"),
            "QQQ260619P464000.US": Decimal("464"),
        }
        snapshots: list[OptionMarketSnapshot] = []
        for symbol in symbols:
            snapshots.append(
                OptionMarketSnapshot(
                    symbol=symbol,
                    underlying_symbol="QQQ.US",
                    expiration_date=date(2026, 6, 19),
                    strike=strikes[symbol],
                    right=OptionRight.PUT,
                    last_done=price_map[symbol],
                    prev_close=price_map[symbol],
                    open=price_map[symbol],
                    high=price_map[symbol],
                    low=price_map[symbol],
                    timestamp=timestamp,
                    volume=1000,
                    turnover=price_map[symbol] * Decimal("1000"),
                    trade_status="Normal",
                    open_interest=500,
                    implied_volatility=Decimal("0.22"),
                    historical_volatility=Decimal("0.18"),
                    delta=deltas[symbol],
                    gamma=Decimal("0.01"),
                    theta=Decimal("-0.02"),
                    vega=Decimal("0.05"),
                )
            )
        return snapshots

    def get_best_bid_ask(self, *, symbol: str, mode: ExecutionMode) -> tuple[Decimal, Decimal]:
        if self.exit_phase:
            prices = {
                "QQQ260619P470000.US": (Decimal("0.70"), Decimal("0.80")),
                "QQQ260619P467000.US": (Decimal("0.30"), Decimal("0.40")),
                "QQQ260619P464000.US": (Decimal("0.20"), Decimal("0.30")),
            }
        else:
            prices = {
                "QQQ260619P470000.US": (Decimal("2.40"), Decimal("2.60")),
                "QQQ260619P467000.US": (Decimal("1.00"), Decimal("1.10")),
                "QQQ260619P464000.US": (Decimal("0.60"), Decimal("0.70")),
            }
        return prices[symbol]


class FakeOrderService:
    def __init__(self) -> None:
        self.counter = 0
        self.orders: dict[str, Order] = {}
        self.exit_phase = False

    def submit_order(self, request) -> Order:
        self.counter += 1
        order_id = f"mock-order-{self.counter}"
        now = datetime.now(timezone.utc)
        limit_price = request.limit_price
        status = OrderStatus.FILLED
        if self.exit_phase and request.side == OrderSide.SELL and limit_price is None:
            limit_price = Decimal("0.30")
        order = Order(
            id=order_id,
            broker=BrokerName.LONGBRIDGE,
            external_account_id=request.external_account_id,
            external_order_id=f"remote-{order_id}",
            symbol=request.symbol,
            asset_type=AssetType.OPTION,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            time_in_force=TimeInForce.DAY,
            mode=request.mode,
            status=status,
            limit_price=limit_price,
            option_contract=OptionContractRef(
                underlying_symbol=request.option_contract.underlying_symbol,
                expiration_date=request.option_contract.expiration_date,
                strike=request.option_contract.strike,
                right=request.option_contract.right,
            ),
            raw_payload={
                "remote_order": {
                    "executed_price": str(limit_price) if limit_price is not None else None,
                }
            },
            submitted_at=now,
            created_at=now,
            updated_at=now,
        )
        self.orders[order.id] = order
        return order

    def refresh_order(self, order_id: str) -> Order:
        return self.orders[order_id]

    def cancel_order(self, order_id: str) -> Order:
        order = self.orders[order_id].model_copy(update={"status": OrderStatus.CANCELED})
        self.orders[order_id] = order
        return order


def build_account() -> BrokerAccount:
    now = datetime(2026, 5, 23, 14, 30, tzinfo=timezone.utc)
    return BrokerAccount(
        id="broker-account-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        display_name="Longbridge Paper",
        base_currency="USD",
        options_level="Level 2",
        is_active=True,
        auto_reconcile_enabled=True,
        created_at=now,
        updated_at=now,
    )


def build_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        id="snapshot-1",
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        currency="USD",
        cash_balance=Decimal("25000"),
        net_liquidation=Decimal("50000"),
        buying_power=Decimal("25000"),
        options_level="Level 2",
        positions=[],
        captured_at=datetime(2026, 5, 23, 14, 35, tzinfo=timezone.utc),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the paper bull put strategy regression workflow.")
    parser.add_argument("--json-output", default=None, help="Optional path to write the rendered JSON report.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        settings = Settings()
        adapter = FakeAdapter()
        order_service = FakeOrderService()
        journal_service = InMemoryJournalService()
        spreads = InMemorySpreadRepository(items={})
        runtime_states = InMemoryRuntimeRepository()
        service = BullPutStrategyService(
            settings=settings,
            broker_accounts=StaticBrokerAccounts(build_account()),
            account_snapshots=StaticSnapshots(build_snapshot()),
            spreads=spreads,
            runtime_states=runtime_states,
            order_service=order_service,
            longbridge_adapter=adapter,
            risk_service=RiskService(settings=settings),
            journal_service=journal_service,
        )

        scan_result = service.run_entry_scan(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            as_of=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
            force=True,
        )
        if scan_result.executed_spread is None:
            raise RuntimeError(scan_result.reason or "Expected bull put scan to open a spread.")

        adapter.exit_phase = True
        order_service.exit_phase = True
        monitor_result = service.monitor_spread(
            scan_result.executed_spread.id,
            as_of=datetime(2026, 5, 23, 15, 5, tzinfo=timezone.utc),
        )

        payload = {
            "checks": {
                "scan_executed": scan_result.executed,
                "spread_opened": scan_result.executed_spread.status == SpreadStatus.OPEN,
                "monitor_closed": monitor_result.spread.status == SpreadStatus.CLOSED,
                "daily_entry_count": scan_result.strategy_state.daily_entry_count == 1,
                "runtime_realized_pnl": runtime_states.state is not None and runtime_states.state.daily_realized_pnl == Decimal("80.00"),
                "journal_entries": len(journal_service.entries) >= 2,
            },
            "scan": {
                "runtime_result": scan_result.strategy_state.last_scan_result,
                "spread_id": scan_result.executed_spread.id,
                "entry_credit": str(scan_result.executed_spread.entry_net_credit),
            },
            "monitor": {
                "status": monitor_result.spread.status.value,
                "exit_reason": monitor_result.exit_reason,
                "estimated_pnl": str(monitor_result.estimated_pnl),
            },
            "journal_titles": [entry.title for entry in journal_service.entries],
        }
        report = build_report(
            script="run_bull_put_strategy_regression.py",
            workflow="bull-put-paper-regression",
            status="passed",
            mode="paper",
            summary="Bull put scan, open, monitor, close, and journal workflow passed.",
            target="BullPutStrategyService",
            payload=payload,
        )
        emit_report(report, json_output=args.json_output)
    except Exception as exc:
        report = build_report(
            script="run_bull_put_strategy_regression.py",
            workflow="bull-put-paper-regression",
            status="failed",
            mode="paper",
            summary="Bull put strategy regression failed.",
            target="BullPutStrategyService",
            error="".join(traceback.format_exception_only(type(exc), exc)).strip(),
        )
        emit_report(report, json_output=args.json_output)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
