from __future__ import annotations

import time
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.application.services.orders import OrderService
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
    RiskStatus,
    SpreadStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BullPutSpread,
    BullPutSpreadCandidate,
    BullPutSpreadMonitorResult,
    BullPutSpreadScanResult,
    CreateOrderRequest,
    ExecuteBullPutSpreadRequest,
    HistoricalPriceBar,
    OptionMarketSnapshot,
    OptionContractRef,
    Order,
)
from stocks_tool.ports.repository import (
    AccountSnapshotRepository,
    BrokerAccountRepository,
    BullPutSpreadRepository,
)


ACTIVE_SPREAD_STATUSES = {
    SpreadStatus.ENTRY_PENDING_LONG,
    SpreadStatus.ENTRY_PENDING_SHORT,
    SpreadStatus.OPEN,
    SpreadStatus.EXIT_PENDING_SHORT,
    SpreadStatus.EXIT_PENDING_LONG,
}


class BullPutStrategyService:
    def __init__(
        self,
        *,
        settings: Settings,
        broker_accounts: BrokerAccountRepository,
        account_snapshots: AccountSnapshotRepository,
        spreads: BullPutSpreadRepository,
        order_service: OrderService,
        longbridge_adapter: LongbridgeBrokerAdapter,
        risk_service: RiskService,
    ) -> None:
        self.settings = settings
        self.broker_accounts = broker_accounts
        self.account_snapshots = account_snapshots
        self.spreads = spreads
        self.order_service = order_service
        self.longbridge_adapter = longbridge_adapter
        self.risk_service = risk_service
        self.new_york = ZoneInfo("America/New_York")

    def list_spreads(
        self,
        *,
        external_account_id: str | None = None,
        status: SpreadStatus | None = None,
    ) -> list[BullPutSpread]:
        return self.spreads.list_spreads(
            external_account_id=external_account_id,
            status=status,
        )

    def get_spread(self, spread_id: str) -> BullPutSpread | None:
        return self.spreads.get_spread(spread_id)

    def preview_spread(
        self,
        *,
        external_account_id: str,
        symbol: str,
        mode: ExecutionMode,
        as_of: datetime | None = None,
    ) -> BullPutSpreadScanResult:
        strategy = self.settings.bull_put_strategy
        if symbol not in strategy.symbols:
            raise ValueError(
                f"Symbol '{symbol}' is outside the configured bull put spread universe: {', '.join(strategy.symbols)}."
            )

        broker_account = self.broker_accounts.get_by_external_account_id(external_account_id)
        if broker_account is None or broker_account.broker != BrokerName.LONGBRIDGE:
            raise LookupError(
                f"No local Longbridge broker account was found for '{external_account_id}'."
            )

        scanned_at = as_of or datetime.now(tz=timezone.utc)
        if scanned_at.tzinfo is None:
            scanned_at = scanned_at.replace(tzinfo=timezone.utc)
        account_snapshot = self._get_latest_account_snapshot(external_account_id)
        account_snapshot = account_snapshot.model_copy(
            update={
                "options_level": account_snapshot.options_level or broker_account.options_level,
            }
        )

        result = BullPutSpreadScanResult(
            symbol=symbol,
            mode=mode,
            external_account_id=external_account_id,
            scanned_at=scanned_at,
            eligible=False,
        )

        if not strategy.enabled:
            result.reasons.append("Bull put spread strategy is disabled by configuration.")
            return result

        if mode != ExecutionMode.PAPER:
            result.reasons.append("paper_bull_put_v1 currently supports paper mode only.")
            return result

        underlying_quote = self.longbridge_adapter.get_quote(symbol=symbol, mode=mode)
        result.underlying_quote = underlying_quote

        bars = self.longbridge_adapter.get_recent_daily_bars(symbol=symbol, count=60, mode=mode)
        if len(bars) < 50:
            result.reasons.append("At least 50 daily bars are required for trend filtering.")
            return result

        moving_average_20 = self._moving_average(bars[-20:])
        moving_average_50 = self._moving_average(bars[-50:])
        result.moving_average_20 = moving_average_20
        result.moving_average_50 = moving_average_50

        result.reasons.extend(
            self._entry_filter_reasons(
                account_snapshot=account_snapshot,
                underlying_quote=underlying_quote,
                moving_average_20=moving_average_20,
                moving_average_50=moving_average_50,
            )
        )
        if result.reasons:
            return result

        expiry_dates = self.longbridge_adapter.list_option_expiry_dates(symbol=symbol, mode=mode)
        selected_expiration_date = self._select_expiration_date(expiry_dates, scanned_at)
        if selected_expiration_date is None:
            result.reasons.append(
                "No listed option expiration date falls inside the configured 28-35 DTE window."
            )
            return result

        result.selected_expiration_date = selected_expiration_date
        result.days_to_expiration = self._days_to_expiration(selected_expiration_date, scanned_at)

        option_chain = self.longbridge_adapter.list_option_chain(
            symbol=symbol,
            expiry_date=selected_expiration_date,
            mode=mode,
        )
        put_symbols = [
            contract.put_symbol
            for contract in option_chain
            if contract.standard and contract.put_symbol
        ]
        if not put_symbols:
            result.reasons.append("No standard put contracts were returned for the selected expiration date.")
            return result

        option_quotes = self.longbridge_adapter.get_option_market_snapshots(
            symbols=put_symbols,
            mode=mode,
        )
        option_quotes_by_strike = {
            quote.strike: quote
            for quote in option_quotes
            if quote.right == OptionRight.PUT and quote.expiration_date == selected_expiration_date
        }
        width = strategy.width_for_underlying_price(underlying_quote.last_done)
        ranked_short_puts = sorted(
            [
                quote
                for quote in option_quotes_by_strike.values()
                if self._is_short_put_candidate(quote)
            ],
            key=lambda quote: (
                abs(abs(quote.delta or Decimal("0")) - strategy.short_delta_target),
                -(quote.open_interest or 0),
                -quote.strike,
            ),
        )
        if not ranked_short_puts:
            result.reasons.append("No short put met the configured delta and open-interest filters.")
            return result

        last_risk_reasons: list[str] = []
        for short_put in ranked_short_puts:
            enriched_short = self._with_top_of_book(short_put, mode=mode)
            if not self._passes_top_of_book_filters(enriched_short):
                continue

            long_put = option_quotes_by_strike.get(short_put.strike - width)
            if long_put is None:
                continue

            enriched_long = self._with_top_of_book(long_put, mode=mode)
            if not self._has_tradeable_long_leg(enriched_long):
                continue

            short_mid = self._mid_price(enriched_short)
            long_mid = self._mid_price(enriched_long)
            if short_mid is None or long_mid is None:
                continue

            conservative_credit = (enriched_short.bid or Decimal("0")) - (enriched_long.ask or Decimal("0"))
            mid_credit = short_mid - long_mid
            if mid_credit < width * strategy.min_credit_per_width_ratio:
                continue
            if conservative_credit < width * strategy.min_conservative_credit_per_width_ratio:
                continue
            if mid_credit < strategy.min_mid_credit:
                continue

            candidate = BullPutSpreadCandidate(
                underlying_symbol=symbol,
                expiration_date=selected_expiration_date,
                days_to_expiration=result.days_to_expiration or 0,
                width=width,
                short_put=enriched_short,
                long_put=enriched_long,
                short_mid=short_mid,
                long_mid=long_mid,
                mid_credit=mid_credit,
                conservative_credit=conservative_credit,
            )
            risk = self.risk_service.evaluate_bull_put_candidate(
                candidate=candidate,
                account=account_snapshot,
                strategy=strategy,
            )
            if risk.status == RiskStatus.BLOCK:
                last_risk_reasons = risk.reasons
                continue

            result.candidate = candidate
            result.risk = risk
            result.warnings.extend(risk.warnings)
            result.eligible = True
            return result

        if last_risk_reasons:
            result.reasons.extend(last_risk_reasons)
        else:
            result.reasons.append(
                "No bull put spread candidate satisfied liquidity, width, credit, and risk filters."
            )
        return result

    def execute_spread(self, request: ExecuteBullPutSpreadRequest) -> BullPutSpread:
        preview = self.preview_spread(
            external_account_id=request.external_account_id,
            symbol=request.symbol,
            mode=request.mode,
            as_of=request.as_of,
        )
        if not preview.eligible or preview.candidate is None or preview.risk is None:
            failure_reason = (
                preview.reasons[0]
                if preview.reasons
                else "Bull put spread preview did not produce an eligible candidate."
            )
            raise ValueError(failure_reason)

        self._assert_entry_capacity(
            external_account_id=request.external_account_id,
            symbol=request.symbol,
        )

        now = preview.scanned_at
        spread = BullPutSpread(
            broker=BrokerName.LONGBRIDGE,
            external_account_id=request.external_account_id,
            mode=request.mode,
            underlying_symbol=request.symbol,
            expiration_date=preview.candidate.expiration_date,
            contracts=self.settings.bull_put_strategy.contracts_per_trade,
            width=preview.candidate.width,
            long_symbol=preview.candidate.long_put.symbol,
            long_strike=preview.candidate.long_put.strike,
            short_symbol=preview.candidate.short_put.symbol,
            short_strike=preview.candidate.short_put.strike,
            status=SpreadStatus.ENTRY_PENDING_LONG,
            max_profit=preview.risk.max_profit,
            max_loss=preview.risk.max_loss,
            break_even=preview.risk.break_even,
            account_risk_pct=preview.risk.account_risk_pct,
            raw_payload={
                "preview": preview.model_dump(mode="json"),
            },
            entry_started_at=now,
            created_at=now,
            updated_at=now,
        )
        spread = self.spreads.create_spread(spread)

        long_entry_order = self.order_service.submit_order(
            self._build_leg_order_request(
                external_account_id=request.external_account_id,
                leg=preview.candidate.long_put,
                side=OrderSide.BUY,
                quantity=spread.contracts,
                mode=request.mode,
                order_type=OrderType.LIMIT,
                limit_price=preview.candidate.long_put.ask,
                remark=request.remark,
            )
        )
        spread = self._update_spread(
            spread,
            long_entry_order_id=long_entry_order.id,
            updated_at=datetime.now(timezone.utc),
        )
        long_entry_order = self._await_terminal_or_fill(long_entry_order)
        if not self._is_filled(long_entry_order):
            self._cancel_if_working(long_entry_order)
            return self._update_spread(
                spread,
                status=SpreadStatus.ENTRY_FAILED,
                exit_reason="long_entry_unfilled",
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        spread = self._update_spread(
            spread,
            status=SpreadStatus.ENTRY_PENDING_SHORT,
            entry_long_price=self._effective_fill_price(long_entry_order),
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        try:
            short_entry_order = self.order_service.submit_order(
                self._build_leg_order_request(
                    external_account_id=request.external_account_id,
                    leg=preview.candidate.short_put,
                    side=OrderSide.SELL,
                    quantity=spread.contracts,
                    mode=request.mode,
                    order_type=OrderType.LIMIT,
                    limit_price=preview.candidate.short_put.bid,
                    remark=request.remark,
                )
            )
        except Exception:
            return self._rollback_long_leg(spread, reason="short_entry_submit_failed")

        spread = self._update_spread(
            spread,
            short_entry_order_id=short_entry_order.id,
            updated_at=datetime.now(timezone.utc),
        )
        short_entry_order = self._await_terminal_or_fill(short_entry_order)
        if not self._is_filled(short_entry_order):
            self._cancel_if_working(short_entry_order)
            return self._rollback_long_leg(spread, reason="short_entry_unfilled")

        entry_long_price = self._effective_fill_price(long_entry_order)
        entry_short_price = self._effective_fill_price(short_entry_order)
        entry_net_credit = None
        if entry_long_price is not None and entry_short_price is not None:
            entry_net_credit = entry_short_price - entry_long_price

        return self._update_spread(
            spread,
            status=SpreadStatus.OPEN,
            entry_long_price=entry_long_price,
            entry_short_price=entry_short_price,
            entry_net_credit=entry_net_credit,
            opened_at=datetime.now(timezone.utc),
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def refresh_spread(self, spread_id: str) -> BullPutSpread:
        spread = self._get_spread_or_raise(spread_id)
        updates: dict = {
            "last_synced_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        long_entry_order = self._refresh_if_present(spread.long_entry_order_id)
        short_entry_order = self._refresh_if_present(spread.short_entry_order_id)
        short_exit_order = self._refresh_if_present(spread.short_exit_order_id)
        long_exit_order = self._refresh_if_present(spread.long_exit_order_id)

        if long_entry_order is not None:
            updates["entry_long_price"] = self._effective_fill_price(long_entry_order)
        if short_entry_order is not None:
            updates["entry_short_price"] = self._effective_fill_price(short_entry_order)

        if self._is_filled(long_entry_order) and self._is_filled(short_entry_order):
            updates["status"] = SpreadStatus.OPEN
            if spread.opened_at is None:
                updates["opened_at"] = datetime.now(timezone.utc)
            if updates.get("entry_long_price") is not None and updates.get("entry_short_price") is not None:
                updates["entry_net_credit"] = (
                    updates["entry_short_price"] - updates["entry_long_price"]
                )
        elif spread.status == SpreadStatus.ENTRY_PENDING_LONG and long_entry_order is not None:
            if long_entry_order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
                updates["status"] = SpreadStatus.ENTRY_FAILED
                updates["exit_reason"] = "long_entry_canceled"
        elif spread.status == SpreadStatus.ENTRY_PENDING_SHORT:
            if short_entry_order is not None and short_entry_order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
                if self._is_filled(long_exit_order):
                    updates["status"] = SpreadStatus.ROLLED_BACK
                    if spread.closed_at is None:
                        updates["closed_at"] = datetime.now(timezone.utc)
                else:
                    updates["status"] = SpreadStatus.ROLLBACK_FAILED
                    updates["exit_reason"] = spread.exit_reason or "short_entry_canceled"
        elif spread.status == SpreadStatus.ROLLBACK_FAILED and self._is_filled(long_exit_order):
            updates["status"] = SpreadStatus.ROLLED_BACK
            if spread.closed_at is None:
                updates["closed_at"] = datetime.now(timezone.utc)
        elif spread.status == SpreadStatus.EXIT_PENDING_SHORT:
            if self._is_filled(short_exit_order):
                if self._is_filled(long_exit_order):
                    updates["status"] = SpreadStatus.CLOSED
                    if spread.closed_at is None:
                        updates["closed_at"] = datetime.now(timezone.utc)
                else:
                    updates["status"] = SpreadStatus.EXIT_PENDING_LONG
            elif short_exit_order is not None and short_exit_order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
                updates["status"] = SpreadStatus.OPEN
        elif spread.status == SpreadStatus.EXIT_PENDING_LONG and self._is_filled(long_exit_order):
            updates["status"] = SpreadStatus.CLOSED
            if spread.closed_at is None:
                updates["closed_at"] = datetime.now(timezone.utc)

        return self._update_spread(spread, **updates)

    def monitor_spread(
        self,
        spread_id: str,
        *,
        as_of: datetime | None = None,
    ) -> BullPutSpreadMonitorResult:
        spread = self.refresh_spread(spread_id)
        evaluated_at = as_of or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        if spread.status == SpreadStatus.EXIT_PENDING_LONG:
            spread = self._close_long_leg(
                spread,
                reason=spread.exit_reason or "long_exit_retry",
            )
            return BullPutSpreadMonitorResult(
                spread=spread,
                evaluated_at=evaluated_at,
                should_close=True,
                exit_reason=spread.exit_reason,
            )

        if spread.status != SpreadStatus.OPEN:
            return BullPutSpreadMonitorResult(
                spread=spread,
                evaluated_at=evaluated_at,
                should_close=False,
                exit_reason=spread.exit_reason,
            )

        underlying_quote = self.longbridge_adapter.get_quote(
            symbol=spread.underlying_symbol,
            mode=spread.mode,
        )
        short_leg, long_leg = self._load_spread_leg_quotes(spread)
        estimated_exit_debit = self._estimated_exit_debit(
            short_leg=short_leg,
            long_leg=long_leg,
        )
        days_to_expiration = self._days_to_expiration(
            spread.expiration_date,
            evaluated_at,
        )
        exit_reason = self._determine_exit_reason(
            spread=spread,
            underlying_price=underlying_quote.last_done,
            estimated_exit_debit=estimated_exit_debit,
            days_to_expiration=days_to_expiration,
        )
        estimated_pnl = self._estimated_pnl(
            spread=spread,
            estimated_exit_debit=estimated_exit_debit,
        )

        if exit_reason is None:
            spread = self._update_spread(
                spread,
                last_synced_at=evaluated_at,
                updated_at=evaluated_at,
            )
            return BullPutSpreadMonitorResult(
                spread=spread,
                evaluated_at=evaluated_at,
                should_close=False,
                current_underlying_price=underlying_quote.last_done,
                estimated_exit_debit=estimated_exit_debit,
                estimated_pnl=estimated_pnl,
                days_to_expiration=days_to_expiration,
            )

        spread = self._close_spread(
            spread=spread,
            reason=exit_reason,
            short_leg=short_leg,
            long_leg=long_leg,
        )
        return BullPutSpreadMonitorResult(
            spread=spread,
            evaluated_at=evaluated_at,
            should_close=True,
            exit_reason=exit_reason,
            current_underlying_price=underlying_quote.last_done,
            estimated_exit_debit=estimated_exit_debit,
            estimated_pnl=estimated_pnl,
            days_to_expiration=days_to_expiration,
        )

    def _entry_filter_reasons(
        self,
        *,
        account_snapshot: AccountSnapshot,
        underlying_quote,
        moving_average_20: Decimal,
        moving_average_50: Decimal,
    ) -> list[str]:
        reasons: list[str] = []
        if account_snapshot.options_level is None:
            reasons.append("Bull put spread entry requires options approval on the selected account.")

        if underlying_quote.last_done <= moving_average_20:
            reasons.append("Underlying price is below the 20-day moving average.")

        if moving_average_20 <= moving_average_50:
            reasons.append("20-day moving average is not above the 50-day moving average.")

        if underlying_quote.last_done < (underlying_quote.prev_close * Decimal("0.995")):
            reasons.append("Underlying price is trading more than 0.5% below the previous close.")

        if underlying_quote.open < (underlying_quote.prev_close * Decimal("0.98")):
            reasons.append("Underlying opened more than 2% below the previous close.")

        return reasons

    def _get_latest_account_snapshot(self, external_account_id: str) -> AccountSnapshot:
        snapshots = self.account_snapshots.list_account_snapshots(
            external_account_id=external_account_id
        )
        if not snapshots:
            raise LookupError(
                f"No local account snapshot was found for '{external_account_id}'. Run account sync first."
            )
        return max(snapshots, key=lambda snapshot: snapshot.captured_at)

    @staticmethod
    def _moving_average(bars: list[HistoricalPriceBar]) -> Decimal:
        close_total = sum((bar.close for bar in bars), start=Decimal("0"))
        return close_total / Decimal(len(bars))

    def _assert_entry_capacity(self, *, external_account_id: str, symbol: str) -> None:
        strategy = self.settings.bull_put_strategy
        active_spreads = [
            spread
            for spread in self.spreads.list_spreads(external_account_id=external_account_id)
            if spread.status in ACTIVE_SPREAD_STATUSES
        ]

        if len(active_spreads) >= strategy.account_max_open_spreads:
            raise ValueError(
                f"Account '{external_account_id}' already has the maximum number of active bull put spreads."
            )

        symbol_spreads = [
            spread
            for spread in active_spreads
            if spread.underlying_symbol == symbol
        ]
        if len(symbol_spreads) >= strategy.per_symbol_max_open_spreads:
            raise ValueError(
                f"An active bull put spread already exists for '{symbol}' in account '{external_account_id}'."
            )

        if symbol in strategy.correlated_symbols:
            correlated_spreads = [
                spread
                for spread in active_spreads
                if spread.underlying_symbol in strategy.correlated_symbols
            ]
            if len(correlated_spreads) >= strategy.correlated_group_max_open_spreads:
                correlated_group = ", ".join(strategy.correlated_symbols)
                raise ValueError(
                    f"Account '{external_account_id}' already has the maximum number of active correlated bull put spreads in [{correlated_group}]."
                )

    def _build_leg_order_request(
        self,
        *,
        external_account_id: str,
        leg: OptionMarketSnapshot,
        side: OrderSide,
        quantity: int,
        mode: ExecutionMode,
        order_type: OrderType,
        limit_price: Decimal | None,
        remark: str | None,
    ) -> CreateOrderRequest:
        return CreateOrderRequest(
            external_account_id=external_account_id,
            broker=BrokerName.LONGBRIDGE,
            symbol=leg.symbol,
            asset_type=AssetType.OPTION,
            side=side,
            quantity=quantity,
            order_type=order_type,
            time_in_force=TimeInForce.DAY,
            mode=mode,
            limit_price=limit_price,
            option_contract=OptionContractRef(
                underlying_symbol=leg.underlying_symbol,
                expiration_date=leg.expiration_date,
                strike=leg.strike,
                right=leg.right,
            ),
            remark=remark,
        )

    def _build_spread_leg_snapshot(
        self,
        spread: BullPutSpread,
        *,
        symbol: str,
        strike: Decimal,
    ) -> OptionMarketSnapshot:
        return OptionMarketSnapshot(
            symbol=symbol,
            underlying_symbol=spread.underlying_symbol,
            expiration_date=spread.expiration_date,
            strike=strike,
            right=OptionRight.PUT,
            last_done=Decimal("0"),
            prev_close=Decimal("0"),
            open=Decimal("0"),
            high=Decimal("0"),
            low=Decimal("0"),
            timestamp=datetime.now(timezone.utc),
            volume=0,
            turnover=Decimal("0"),
            contract_multiplier=Decimal("100"),
        )

    def _await_terminal_or_fill(self, order: Order) -> Order:
        current = order
        if self._is_terminal(current) or self._is_filled(current):
            return current
        time.sleep(0)
        return self.order_service.refresh_order(current.id)

    def _cancel_if_working(self, order: Order) -> Order | None:
        if order.status not in {
            OrderStatus.CREATED,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIALLY_FILLED,
        }:
            return order
        return self.order_service.cancel_order(order.id)

    def _rollback_long_leg(
        self,
        spread: BullPutSpread,
        *,
        reason: str,
    ) -> BullPutSpread:
        rollback_leg = self._build_spread_leg_snapshot(
            spread,
            symbol=spread.long_symbol,
            strike=spread.long_strike,
        )
        try:
            rollback_order = self.order_service.submit_order(
                self._build_leg_order_request(
                    external_account_id=spread.external_account_id,
                    leg=rollback_leg,
                    side=OrderSide.SELL,
                    quantity=spread.contracts,
                    mode=spread.mode,
                    order_type=OrderType.MARKET,
                    limit_price=None,
                    remark=reason,
                )
            )
        except Exception:
            return self._update_spread(
                spread,
                status=SpreadStatus.ROLLBACK_FAILED,
                exit_reason=reason,
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        spread = self._update_spread(
            spread,
            long_exit_order_id=rollback_order.id,
            exit_reason=reason,
            updated_at=datetime.now(timezone.utc),
        )
        rollback_order = self._await_terminal_or_fill(rollback_order)
        if self._is_filled(rollback_order):
            return self._update_spread(
                spread,
                status=SpreadStatus.ROLLED_BACK,
                closed_at=datetime.now(timezone.utc),
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        return self._update_spread(
            spread,
            status=SpreadStatus.ROLLBACK_FAILED,
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def _close_spread(
        self,
        *,
        spread: BullPutSpread,
        reason: str,
        short_leg: OptionMarketSnapshot,
        long_leg: OptionMarketSnapshot,
    ) -> BullPutSpread:
        short_exit_order = self.order_service.submit_order(
            self._build_leg_order_request(
                external_account_id=spread.external_account_id,
                leg=short_leg,
                side=OrderSide.BUY,
                quantity=spread.contracts,
                mode=spread.mode,
                order_type=OrderType.LIMIT,
                limit_price=short_leg.ask,
                remark=reason,
            )
        )
        spread = self._update_spread(
            spread,
            status=SpreadStatus.EXIT_PENDING_SHORT,
            short_exit_order_id=short_exit_order.id,
            exit_reason=reason,
            updated_at=datetime.now(timezone.utc),
        )
        short_exit_order = self._await_terminal_or_fill(short_exit_order)
        if not self._is_filled(short_exit_order):
            self._cancel_if_working(short_exit_order)
            return self._update_spread(
                spread,
                status=SpreadStatus.OPEN,
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        return self._close_long_leg(spread, reason=reason, leg=long_leg)

    def _close_long_leg(
        self,
        spread: BullPutSpread,
        *,
        reason: str,
        leg: OptionMarketSnapshot | None = None,
    ) -> BullPutSpread:
        long_leg = leg or self._build_spread_leg_snapshot(
            spread,
            symbol=spread.long_symbol,
            strike=spread.long_strike,
        )
        long_exit_order = self.order_service.submit_order(
            self._build_leg_order_request(
                external_account_id=spread.external_account_id,
                leg=long_leg,
                side=OrderSide.SELL,
                quantity=spread.contracts,
                mode=spread.mode,
                order_type=OrderType.MARKET,
                limit_price=None,
                remark=reason,
            )
        )
        spread = self._update_spread(
            spread,
            status=SpreadStatus.EXIT_PENDING_LONG,
            long_exit_order_id=long_exit_order.id,
            exit_reason=reason,
            updated_at=datetime.now(timezone.utc),
        )
        long_exit_order = self._await_terminal_or_fill(long_exit_order)
        if self._is_filled(long_exit_order):
            return self._update_spread(
                spread,
                status=SpreadStatus.CLOSED,
                closed_at=datetime.now(timezone.utc),
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        self._cancel_if_working(long_exit_order)
        return self._update_spread(
            spread,
            status=SpreadStatus.EXIT_PENDING_LONG,
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def _get_spread_or_raise(self, spread_id: str) -> BullPutSpread:
        spread = self.spreads.get_spread(spread_id)
        if spread is None:
            raise LookupError(f"Bull put spread '{spread_id}' was not found.")
        return spread

    def _refresh_if_present(self, order_id: str | None) -> Order | None:
        if order_id is None:
            return None
        return self.order_service.refresh_order(order_id)

    def _update_spread(self, spread: BullPutSpread, **updates) -> BullPutSpread:
        next_spread = spread.model_copy(update=updates)
        return self.spreads.update_spread(next_spread)

    def _load_spread_leg_quotes(
        self,
        spread: BullPutSpread,
    ) -> tuple[OptionMarketSnapshot, OptionMarketSnapshot]:
        quotes = self.longbridge_adapter.get_option_market_snapshots(
            symbols=[spread.short_symbol, spread.long_symbol],
            mode=spread.mode,
        )
        quotes_by_symbol = {quote.symbol: quote for quote in quotes}
        short_leg = quotes_by_symbol.get(spread.short_symbol)
        long_leg = quotes_by_symbol.get(spread.long_symbol)
        if short_leg is None or long_leg is None:
            raise LookupError(f"Could not load option quotes for spread '{spread.id}'.")
        return (
            self._with_top_of_book(short_leg, mode=spread.mode),
            self._with_top_of_book(long_leg, mode=spread.mode),
        )

    def _determine_exit_reason(
        self,
        *,
        spread: BullPutSpread,
        underlying_price: Decimal,
        estimated_exit_debit: Decimal | None,
        days_to_expiration: int,
    ) -> str | None:
        strategy = self.settings.bull_put_strategy
        if days_to_expiration <= strategy.close_days_to_expiration:
            return "days_to_expiration_limit"
        if underlying_price <= spread.short_strike:
            return "short_strike_breach"
        if spread.entry_net_credit is None or estimated_exit_debit is None:
            return None
        if estimated_exit_debit >= (spread.entry_net_credit * strategy.stop_loss_exit_multiple):
            return "stop_loss"
        if estimated_exit_debit <= (spread.entry_net_credit * strategy.take_profit_exit_ratio):
            return "take_profit"
        return None

    @staticmethod
    def _estimated_exit_debit(
        *,
        short_leg: OptionMarketSnapshot,
        long_leg: OptionMarketSnapshot,
    ) -> Decimal | None:
        if short_leg.ask is None or long_leg.bid is None:
            return None
        return short_leg.ask - long_leg.bid

    @staticmethod
    def _estimated_pnl(
        *,
        spread: BullPutSpread,
        estimated_exit_debit: Decimal | None,
    ) -> Decimal | None:
        if spread.entry_net_credit is None or estimated_exit_debit is None:
            return None
        return (
            (spread.entry_net_credit - estimated_exit_debit)
            * Decimal(spread.contracts)
            * Decimal("100")
        )

    @staticmethod
    def _effective_fill_price(order: Order | None) -> Decimal | None:
        if order is None:
            return None
        if order.status not in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}:
            return None
        raw_payload = order.raw_payload or {}
        remote_order = raw_payload.get("remote_order") or {}
        if remote_order.get("executed_price") is not None:
            return Decimal(str(remote_order["executed_price"]))
        if order.limit_price is not None:
            return order.limit_price
        return None

    @staticmethod
    def _is_filled(order: Order | None) -> bool:
        return order is not None and order.status == OrderStatus.FILLED

    @staticmethod
    def _is_terminal(order: Order | None) -> bool:
        return order is not None and order.status in {
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
        }

    def _select_expiration_date(
        self,
        expiry_dates: list[date],
        scanned_at: datetime,
    ) -> date | None:
        strategy = self.settings.bull_put_strategy
        scanned_date = scanned_at.astimezone(self.new_york).date()
        candidates = [
            expiry_date
            for expiry_date in expiry_dates
            if strategy.min_dte <= (expiry_date - scanned_date).days <= strategy.max_dte
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda expiry_date: (expiry_date - scanned_date).days)

    def _days_to_expiration(self, expiry_date: date, scanned_at: datetime) -> int:
        scanned_date = scanned_at.astimezone(self.new_york).date()
        return (expiry_date - scanned_date).days

    def _is_short_put_candidate(self, quote: OptionMarketSnapshot) -> bool:
        strategy = self.settings.bull_put_strategy
        if quote.delta is None:
            return False
        if quote.open_interest is None or quote.open_interest < strategy.min_open_interest:
            return False
        delta_abs = abs(quote.delta)
        return strategy.short_delta_min <= delta_abs <= strategy.short_delta_max

    def _with_top_of_book(
        self,
        quote: OptionMarketSnapshot,
        *,
        mode: ExecutionMode,
    ) -> OptionMarketSnapshot:
        bid, ask = self.longbridge_adapter.get_best_bid_ask(symbol=quote.symbol, mode=mode)
        return quote.model_copy(update={"bid": bid, "ask": ask})

    def _passes_top_of_book_filters(self, quote: OptionMarketSnapshot) -> bool:
        strategy = self.settings.bull_put_strategy
        if quote.bid is None or quote.ask is None:
            return False
        if quote.bid <= Decimal("0") or quote.ask <= quote.bid:
            return False
        mid = (quote.ask + quote.bid) / Decimal("2")
        if mid <= Decimal("0"):
            return False
        return ((quote.ask - quote.bid) / mid) <= strategy.max_bid_ask_spread_pct

    @staticmethod
    def _has_tradeable_long_leg(quote: OptionMarketSnapshot) -> bool:
        if quote.ask is None or quote.bid is None:
            return False
        if quote.ask <= Decimal("0"):
            return False
        return quote.ask > quote.bid

    @staticmethod
    def _mid_price(quote: OptionMarketSnapshot) -> Decimal | None:
        if quote.bid is None or quote.ask is None:
            return None
        return (quote.bid + quote.ask) / Decimal("2")
