from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.application.services.journal import JournalService
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    JournalEntryType,
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
    BullPutStrategyReviewResult,
    BullPutStrategyRuntimeState,
    BullPutStrategyScanRunResult,
    CreateOrderRequest,
    CreateJournalEntryRequest,
    DirectionalPutSnapshot,
    ExecuteBullPutSpreadRequest,
    HistoricalPriceBar,
    OptionMarketSnapshot,
    OptionContractRef,
    Order,
    PreOpenDownsideAssessment,
    PreOpenProxySignal,
    UpdateBullPutStrategyRuntimeRequest,
)
from stocks_tool.ports.repository import (
    AccountSnapshotRepository,
    BrokerAccountRepository,
    BullPutSpreadRepository,
    BullPutStrategyRuntimeRepository,
)


ACTIVE_SPREAD_STATUSES = {
    SpreadStatus.ENTRY_PENDING_LONG,
    SpreadStatus.ENTRY_PENDING_SHORT,
    SpreadStatus.OPEN,
    SpreadStatus.EXIT_PENDING_SHORT,
    SpreadStatus.EXIT_PENDING_LONG,
}
logger = logging.getLogger(__name__)


class BullPutStrategyService:
    def __init__(
        self,
        *,
        settings: Settings,
        broker_accounts: BrokerAccountRepository,
        account_snapshots: AccountSnapshotRepository,
        spreads: BullPutSpreadRepository,
        runtime_states: BullPutStrategyRuntimeRepository,
        order_service: OrderService,
        longbridge_adapter: LongbridgeBrokerAdapter,
        risk_service: RiskService,
        journal_service: JournalService,
    ) -> None:
        self.settings = settings
        self.broker_accounts = broker_accounts
        self.account_snapshots = account_snapshots
        self.spreads = spreads
        self.runtime_states = runtime_states
        self.order_service = order_service
        self.longbridge_adapter = longbridge_adapter
        self.risk_service = risk_service
        self.journal_service = journal_service
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

    def get_runtime_state(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
    ) -> BullPutStrategyRuntimeState:
        return self._prepare_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
            as_of=as_of,
        )

    def update_runtime_state(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        request: UpdateBullPutStrategyRuntimeRequest,
        as_of: datetime | None = None,
    ) -> BullPutStrategyRuntimeState:
        state = self._prepare_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
            as_of=as_of,
        )
        updates: dict = {}
        if request.auto_entry_enabled is not None:
            updates["auto_entry_enabled"] = request.auto_entry_enabled
        if request.manual_pause is not None:
            updates["manual_pause"] = request.manual_pause
        if request.kill_switch_active is not None:
            updates["kill_switch_active"] = request.kill_switch_active
        if request.paused_symbols is not None:
            updates["paused_symbols"] = self._normalize_paused_symbols(request.paused_symbols)
        if updates:
            summary = self._describe_runtime_update(updates)
            state = self._update_runtime_state(
                state,
                last_action=summary,
                last_action_at=as_of or datetime.now(timezone.utc),
                **updates,
            )
        return state

    def run_entry_scan(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
        force: bool = False,
    ) -> BullPutStrategyScanRunResult:
        scanned_at = as_of or datetime.now(timezone.utc)
        if scanned_at.tzinfo is None:
            scanned_at = scanned_at.replace(tzinfo=timezone.utc)

        state = self._prepare_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
            as_of=scanned_at,
        )
        if not force:
            due_reason = self._scan_not_due_reason(state=state, as_of=scanned_at)
            if due_reason is not None:
                updates: dict = {
                    "last_scan_result": "not_due",
                    "last_skip_reason": due_reason,
                    "last_error": None,
                }
                if due_reason == "Automatic bull put scan already ran for this account today.":
                    updates["last_scan_at"] = scanned_at
                state = self._update_runtime_state(
                    state,
                    **updates,
                )
                return BullPutStrategyScanRunResult(
                    strategy_state=state,
                    scanned_at=scanned_at,
                    executed=False,
                    reason=due_reason,
                )

        previews: list[BullPutSpreadScanResult] = []
        strategy = self.settings.bull_put_strategy
        for symbol in strategy.symbols:
            preview = self.preview_spread(
                external_account_id=external_account_id,
                symbol=symbol,
                mode=mode,
                as_of=scanned_at,
            )
            previews.append(preview)
            if preview.eligible:
                spread = self._execute_preview_candidate(
                    request=ExecuteBullPutSpreadRequest(
                        external_account_id=external_account_id,
                        symbol=symbol,
                        mode=mode,
                        as_of=scanned_at,
                        remark="auto_scan",
                    ),
                    preview=preview,
                )
                state = self._prepare_runtime_state(
                    external_account_id=external_account_id,
                    mode=mode,
                    as_of=scanned_at,
                )
                state = self._update_runtime_state(
                    state,
                    last_scan_at=scanned_at,
                    last_scan_result="executed",
                    last_scan_symbol=symbol,
                    last_skip_reason=None,
                    last_action=f"Opened bull put spread for {symbol} during scheduled scan.",
                    last_action_at=scanned_at,
                    last_error=None,
                )
                return BullPutStrategyScanRunResult(
                    strategy_state=state,
                    scanned_at=scanned_at,
                    executed=spread.status == SpreadStatus.OPEN,
                    executed_spread=spread,
                    previews=previews,
                )

            self._log_scan_skip(preview=preview, automatic=not force)

        last_preview = previews[-1] if previews else None
        reason = last_preview.reasons[0] if last_preview and last_preview.reasons else "No bull put spread candidate was eligible."
        state = self._update_runtime_state(
            state,
            last_scan_at=scanned_at,
            last_scan_result="skipped",
            last_scan_symbol=last_preview.symbol if last_preview is not None else None,
            last_skip_reason=reason,
            last_error=None,
        )
        return BullPutStrategyScanRunResult(
            strategy_state=state,
            scanned_at=scanned_at,
            executed=False,
            previews=previews,
            reason=reason,
        )

    def run_review(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
        force: bool = False,
    ) -> BullPutStrategyReviewResult:
        evaluated_at = as_of or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        state = self._prepare_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
            as_of=evaluated_at,
        )
        closed_spreads = self._list_closed_spreads(external_account_id=external_account_id)
        if not force:
            due_reason = self._review_not_due_reason(
                state=state,
                closed_spreads=closed_spreads,
                as_of=evaluated_at,
            )
            if due_reason is not None:
                return BullPutStrategyReviewResult(
                    strategy_state=state,
                    evaluated_at=evaluated_at,
                    review_status="not_due",
                    closed_spreads_considered=0,
                    lookback_days=self.settings.bull_put_strategy.review_interval_days,
                    reason=due_reason,
                )

        strategy = self.settings.bull_put_strategy
        window_start = evaluated_at.astimezone(self.new_york).date() - timedelta(days=strategy.review_interval_days)
        recent_spreads = [
            spread
            for spread in closed_spreads
            if spread.closed_at is not None
            and spread.closed_at.astimezone(self.new_york).date() >= window_start
        ]
        reviewed_metrics = [
            (spread, realized_pnl)
            for spread in recent_spreads
            if (realized_pnl := self._resolved_realized_pnl(spread)) is not None
        ]
        spread_ids = [spread.id for spread, _ in reviewed_metrics]
        count = len(reviewed_metrics)
        total_realized_pnl = sum((pnl for _, pnl in reviewed_metrics), start=Decimal("0"))
        take_profit_count = sum(1 for spread, _ in reviewed_metrics if spread.exit_reason == "take_profit")
        stop_loss_count = sum(1 for spread, _ in reviewed_metrics if spread.exit_reason == "stop_loss")
        take_profit_rate = (
            Decimal(take_profit_count) / Decimal(count)
            if count > 0
            else None
        )
        stop_loss_rate = (
            Decimal(stop_loss_count) / Decimal(count)
            if count > 0
            else None
        )

        review_status = "no_change"
        summary = "Recent closed bull put spreads do not justify a parameter change."
        recommendation = None
        parameter_name = None
        current_value = None
        suggested_value = None

        if count == 0:
            review_status = "insufficient_history"
            summary = "No closed bull put spreads with realized PnL are available for review yet."
        elif count < strategy.review_min_closed_spreads:
            review_status = "insufficient_history"
            summary = (
                f"Closed-spread sample is {count} trades in the last {strategy.review_interval_days} days. "
                "Keep collecting history before changing bull put parameters."
            )
        else:
            (
                review_status,
                summary,
                recommendation,
                parameter_name,
                current_value,
                suggested_value,
            ) = self._build_review_recommendation(
                count=count,
                total_realized_pnl=total_realized_pnl,
                take_profit_rate=take_profit_rate,
                stop_loss_rate=stop_loss_rate,
            )

        journal_entry = self._create_strategy_review_entry(
            external_account_id=external_account_id,
            reviewed_metrics=reviewed_metrics,
            evaluated_at=evaluated_at,
            review_status=review_status,
            summary=summary,
            recommendation=recommendation,
        )
        state = self._update_runtime_state(
            state,
            last_review_at=evaluated_at,
            last_review_status=review_status,
            last_review_summary=summary,
            last_action=summary,
            last_action_at=evaluated_at,
            last_error=None,
        )
        return BullPutStrategyReviewResult(
            strategy_state=state,
            evaluated_at=evaluated_at,
            review_status=review_status,
            closed_spreads_considered=count,
            lookback_days=strategy.review_interval_days,
            net_realized_pnl=total_realized_pnl if count > 0 else None,
            take_profit_rate=take_profit_rate,
            stop_loss_rate=stop_loss_rate,
            recommendation=recommendation,
            parameter_name=parameter_name,
            current_value=current_value,
            suggested_value=suggested_value,
            journal_entry_id=getattr(journal_entry, "id", None) if journal_entry is not None else None,
            reviewed_spread_ids=spread_ids,
        )

    def get_pre_open_downside_assessment(
        self,
        *,
        as_of: datetime | None = None,
    ) -> PreOpenDownsideAssessment:
        evaluated_at = as_of or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        session = self._market_session_label(evaluated_at)
        signal_specs = [
            ("spy", "S&P 500 ETF", self.settings.bull_put_strategy.pre_open_proxy_spy_symbol),
            ("qqq", "Nasdaq 100 ETF", self.settings.bull_put_strategy.pre_open_proxy_qqq_symbol),
            ("semis", "Semiconductor Proxy", self.settings.bull_put_strategy.pre_open_proxy_semis_symbol),
            ("oil", "Oil Proxy", self.settings.bull_put_strategy.pre_open_proxy_oil_symbol),
            ("rates", "Rates Proxy", self.settings.bull_put_strategy.pre_open_proxy_rates_symbol),
        ]

        signals: list[PreOpenProxySignal] = []
        signal_by_key: dict[str, PreOpenProxySignal] = {}
        for key, label, symbol in signal_specs:
            quote = self.longbridge_adapter.get_quote(symbol=symbol, mode=ExecutionMode.PAPER)
            signal = self._build_pre_open_signal(
                key=key,
                label=label,
                quote=quote,
                session=session,
            )
            signals.append(signal)
            signal_by_key[key] = signal

        score = 0
        reasons: list[str] = []
        spy_change = signal_by_key["spy"].change_pct
        qqq_change = signal_by_key["qqq"].change_pct
        semis_change = signal_by_key["semis"].change_pct
        oil_change = signal_by_key["oil"].change_pct
        rates_change = signal_by_key["rates"].change_pct

        if qqq_change <= Decimal("-0.60"):
            score += 2
            reasons.append("QQQ is trading meaningfully below its reference level.")
        if spy_change <= Decimal("-0.45"):
            score += 1
            reasons.append("SPY is leaning lower before the regular session.")
        if semis_change <= Decimal("-0.90"):
            score += 2
            reasons.append("Semiconductor leadership is weakening faster than the broad market.")
        if oil_change >= Decimal("1.25"):
            score += 1
            reasons.append("Oil proxy strength points to fresh inflation and geopolitical pressure.")
        if rates_change <= Decimal("-0.60"):
            score += 1
            reasons.append("Long-duration Treasuries are slipping, which implies higher yield pressure.")
        if (qqq_change - spy_change) <= Decimal("-0.30"):
            score += 1
            reasons.append("QQQ is underperforming SPY, which tilts downside risk toward tech.")

        if score >= 5:
            regime = "broad_downside_risk"
            plain_put_view = "reasonable"
            summary = "Multiple macro and tech proxies are aligned for a weaker U.S. open."
        elif score >= 3:
            regime = "selective_downside_risk"
            plain_put_view = "selective"
            summary = "Downside risk is building, but the setup is not broad-based enough to assume a full risk-off open."
        else:
            regime = "mixed_to_firm"
            plain_put_view = "not_favored"
            summary = "The proxy set is mixed, so plain downside puts do not have a strong pre-open edge."

        preferred_vehicle = None
        if score >= 3:
            preferred_vehicle = "QQQ" if semis_change <= spy_change or qqq_change < spy_change else "SPY"
        if not reasons:
            reasons.append("No broad bearish proxy cluster is present right now.")

        put_snapshots = self._build_directional_put_snapshots(
            evaluated_at=evaluated_at,
            spy_signal=signal_by_key["spy"],
            qqq_signal=signal_by_key["qqq"],
        )

        return PreOpenDownsideAssessment(
            analyzed_at=evaluated_at,
            session=session,
            market_open=session == "regular",
            minutes_to_regular_open=self._minutes_to_regular_open(evaluated_at, session),
            downside_score=score,
            regime=regime,
            plain_put_view=plain_put_view,
            preferred_vehicle=preferred_vehicle,
            summary=summary,
            reasons=reasons,
            signals=signals,
            put_snapshots=put_snapshots,
        )

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
        runtime_state = self._prepare_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
            as_of=scanned_at,
        )
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

        runtime_reason = self._runtime_entry_block_reason(
            state=runtime_state,
            symbol=symbol,
        )
        if runtime_reason is not None:
            result.reasons.append(runtime_reason)
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
        return self._execute_preview_candidate(request=request, preview=preview)

    def _execute_preview_candidate(
        self,
        *,
        request: ExecuteBullPutSpreadRequest,
        preview: BullPutSpreadScanResult,
    ) -> BullPutSpread:
        if not preview.eligible or preview.candidate is None or preview.risk is None:
            failure_reason = (
                preview.reasons[0]
                if preview.reasons
                else "Bull put spread preview did not produce an eligible candidate."
            )
            raise ValueError(failure_reason)
        session_reason = self._entry_session_gate_reason(preview.scanned_at)
        if session_reason is not None:
            raise ValueError(session_reason)

        runtime_state = self._prepare_runtime_state(
            external_account_id=request.external_account_id,
            mode=request.mode,
            as_of=preview.scanned_at,
        )
        self._assert_entry_capacity(
            external_account_id=request.external_account_id,
            symbol=request.symbol,
            runtime_state=runtime_state,
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
        entry_long_leg = self._with_top_of_book(preview.candidate.long_put, mode=request.mode)
        entry_short_leg = self._with_top_of_book(preview.candidate.short_put, mode=request.mode)
        long_entry_cap = self._entry_long_limit_price(
            long_leg=entry_long_leg,
            short_leg=entry_short_leg,
            width=preview.candidate.width,
        )
        spread, long_entry_order = self._submit_entry_leg_with_repricing(
            spread=spread,
            external_account_id=request.external_account_id,
            leg=entry_long_leg,
            side=OrderSide.BUY,
            quantity=spread.contracts,
            mode=request.mode,
            remark=request.remark,
            price_ladder=self._entry_long_price_ladder(
                ask_price=entry_long_leg.ask,
                capped_price=long_entry_cap,
            ),
            order_id_field="long_entry_order_id",
        )
        if not self._is_filled(long_entry_order):
            failed = self._update_spread(
                spread,
                status=SpreadStatus.ENTRY_FAILED,
                exit_reason="long_entry_unfilled",
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            self._log_spread_entry_failure(failed, reason="long_entry_unfilled")
            return failed

        spread = self._update_spread(
            spread,
            status=SpreadStatus.ENTRY_PENDING_SHORT,
            entry_long_price=self._effective_fill_price(long_entry_order),
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        try:
            spread, short_entry_order = self._submit_entry_leg_with_repricing(
                spread=spread,
                external_account_id=request.external_account_id,
                leg=entry_short_leg,
                side=OrderSide.SELL,
                quantity=spread.contracts,
                mode=request.mode,
                remark=request.remark,
                price_ladder=self._entry_short_price_ladder(
                    bid_price=entry_short_leg.bid,
                    filled_long_price=self._effective_fill_price(long_entry_order),
                    width=preview.candidate.width,
                ),
                order_id_field="short_entry_order_id",
            )
        except Exception:
            rolled_back = self._rollback_long_leg(spread, reason="short_entry_submit_failed")
            self._log_spread_entry_failure(rolled_back, reason="short_entry_submit_failed")
            return rolled_back
        if not self._is_filled(short_entry_order):
            rolled_back = self._rollback_long_leg(spread, reason="short_entry_unfilled")
            self._log_spread_entry_failure(rolled_back, reason="short_entry_unfilled")
            return rolled_back

        entry_long_price = self._effective_fill_price(long_entry_order)
        entry_short_price = self._effective_fill_price(short_entry_order)
        entry_net_credit = None
        if entry_long_price is not None and entry_short_price is not None:
            entry_net_credit = entry_short_price - entry_long_price

        opened = self._update_spread(
            spread,
            status=SpreadStatus.OPEN,
            entry_long_price=entry_long_price,
            entry_short_price=entry_short_price,
            entry_net_credit=entry_net_credit,
            opened_at=datetime.now(timezone.utc),
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self._record_opened_spread(opened, preview=preview, runtime_state=runtime_state, as_of=now)
        return opened

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
        runtime_state = self._prepare_runtime_state(
            external_account_id=spread.external_account_id,
            mode=spread.mode,
            as_of=evaluated_at,
        )
        previous_status = spread.status

        if spread.status == SpreadStatus.EXIT_PENDING_LONG:
            spread = self._close_long_leg(
                spread,
                reason=spread.exit_reason or "long_exit_retry",
            )
            result = BullPutSpreadMonitorResult(
                spread=spread,
                evaluated_at=evaluated_at,
                should_close=True,
                exit_reason=spread.exit_reason,
            )
            self._record_monitor_close_if_terminal(
                previous_status=previous_status,
                result=result,
                runtime_state=runtime_state,
            )
            return result

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
        result = BullPutSpreadMonitorResult(
            spread=spread,
            evaluated_at=evaluated_at,
            should_close=True,
            exit_reason=exit_reason,
            current_underlying_price=underlying_quote.last_done,
            estimated_exit_debit=estimated_exit_debit,
            estimated_pnl=estimated_pnl,
            days_to_expiration=days_to_expiration,
        )
        self._record_monitor_close_if_terminal(
            previous_status=previous_status,
            result=result,
            runtime_state=runtime_state,
        )
        return result

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

    def _prepare_runtime_state(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        as_of: datetime | None,
    ) -> BullPutStrategyRuntimeState:
        broker_account = self.broker_accounts.get_by_external_account_id(external_account_id)
        if broker_account is None or broker_account.broker != BrokerName.LONGBRIDGE:
            raise LookupError(
                f"No local Longbridge broker account was found for '{external_account_id}'."
            )
        reference_time = as_of or datetime.now(timezone.utc)
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        state = self.runtime_states.get_runtime_state(external_account_id=external_account_id)
        if state is None:
            state = BullPutStrategyRuntimeState(
                external_account_id=external_account_id,
                mode=mode,
                current_session_date=self._session_date(reference_time),
            )
            return self.runtime_states.upsert_runtime_state(state)

        if state.current_session_date != self._session_date(reference_time):
            state = self._update_runtime_state(
                state,
                current_session_date=self._session_date(reference_time),
                daily_entry_count=0,
                daily_realized_pnl=Decimal("0"),
                last_error=None,
            )
        return state

    def _update_runtime_state(
        self,
        state: BullPutStrategyRuntimeState,
        **updates,
    ) -> BullPutStrategyRuntimeState:
        payload = {"updated_at": datetime.now(timezone.utc), **updates}
        next_state = state.model_copy(update=payload)
        return self.runtime_states.upsert_runtime_state(next_state)

    def _runtime_entry_block_reason(
        self,
        *,
        state: BullPutStrategyRuntimeState,
        symbol: str,
    ) -> str | None:
        strategy = self.settings.bull_put_strategy
        if not state.auto_entry_enabled:
            return "Automatic bull put entry is disabled for this account."
        if state.manual_pause:
            return "Bull put strategy is manually paused for this account."
        if state.kill_switch_active:
            return "Bull put kill switch is active for this account."
        if symbol in state.paused_symbols:
            return f"Bull put strategy is paused for '{symbol}'."
        if state.daily_entry_count >= strategy.max_new_spreads_per_day:
            return "Bull put daily entry cap has already been reached for this account."
        if state.daily_realized_pnl <= (strategy.daily_realized_loss_limit * Decimal("-1")):
            return "Bull put daily realized loss limit has already been reached for this account."
        return None

    def _scan_not_due_reason(
        self,
        *,
        state: BullPutStrategyRuntimeState,
        as_of: datetime,
    ) -> str | None:
        strategy = self.settings.bull_put_strategy
        if not strategy.enabled:
            return "Bull put spread strategy is disabled by configuration."
        if not strategy.auto_scan_enabled:
            return "Automatic bull put scan is disabled by configuration."
        local_time = as_of.astimezone(self.new_york)
        if local_time.weekday() >= 5:
            return "Automatic bull put scans only run on weekdays."

        window_minutes = (local_time.hour * 60) + local_time.minute
        start_minutes = (strategy.scan_window_start_hour_et * 60) + strategy.scan_window_start_minute_et
        end_minutes = (strategy.scan_window_end_hour_et * 60) + strategy.scan_window_end_minute_et
        if window_minutes < start_minutes or window_minutes > end_minutes:
            return "Automatic bull put scan is outside the configured ET entry window."

        if state.last_scan_at is None:
            return None
        if state.last_scan_at.astimezone(self.new_york).date() == local_time.date():
            return "Automatic bull put scan already ran for this account today."
        return None

    def _entry_session_gate_reason(self, as_of: datetime) -> str | None:
        local_time = as_of.astimezone(self.new_york)
        if local_time.weekday() >= 5:
            return "Bull put entries only execute during the regular U.S. options week."
        strategy = self.settings.bull_put_strategy
        session_minutes = (local_time.hour * 60) + local_time.minute
        start_minutes = (strategy.entry_session_start_hour_et * 60) + strategy.entry_session_start_minute_et
        end_minutes = (strategy.entry_session_end_hour_et * 60) + strategy.entry_session_end_minute_et
        if session_minutes < start_minutes or session_minutes >= end_minutes:
            return "Bull put entries only execute during regular U.S. options hours (09:30-16:00 ET)."
        return None

    def _review_not_due_reason(
        self,
        *,
        state: BullPutStrategyRuntimeState,
        closed_spreads: list[BullPutSpread],
        as_of: datetime,
    ) -> str | None:
        strategy = self.settings.bull_put_strategy
        if not strategy.enabled:
            return "Bull put spread strategy is disabled by configuration."
        if not strategy.auto_review_enabled:
            return "Automatic bull put review is disabled by configuration."
        if not closed_spreads:
            return "Bull put review is waiting for the first closed spread."

        if state.last_review_at is None:
            if len(closed_spreads) >= strategy.review_min_closed_spreads:
                return None
            oldest_close = min(
                spread.closed_at for spread in closed_spreads if spread.closed_at is not None
            )
            if oldest_close is None:
                return "Bull put review is waiting for the first closed spread."
            if (as_of - oldest_close).days >= strategy.review_interval_days:
                return None
            return "Bull put review is not due yet."

        closed_since_last_review = [
            spread
            for spread in closed_spreads
            if spread.closed_at is not None and spread.closed_at > state.last_review_at
        ]
        if len(closed_since_last_review) >= strategy.review_min_closed_spreads:
            return None
        if (as_of - state.last_review_at).days >= strategy.review_interval_days:
            return None
        return "Bull put review is not due yet."

    def _list_closed_spreads(self, *, external_account_id: str) -> list[BullPutSpread]:
        spreads = self.spreads.list_spreads(
            external_account_id=external_account_id,
            status=SpreadStatus.CLOSED,
        )
        return sorted(
            [spread for spread in spreads if spread.closed_at is not None],
            key=lambda spread: spread.closed_at or spread.updated_at,
            reverse=True,
        )

    def _record_opened_spread(
        self,
        spread: BullPutSpread,
        *,
        preview: BullPutSpreadScanResult,
        runtime_state: BullPutStrategyRuntimeState,
        as_of: datetime,
    ) -> None:
        runtime_state = self._update_runtime_state(
            runtime_state,
            daily_entry_count=runtime_state.daily_entry_count + 1,
            last_action=f"Opened bull put spread for {spread.underlying_symbol}.",
            last_action_at=as_of,
            last_error=None,
        )
        self._log_spread_entry_open(spread=spread, preview=preview)
        self._update_runtime_state(
            runtime_state,
            last_scan_at=as_of,
            last_scan_result="executed",
            last_scan_symbol=spread.underlying_symbol,
            last_skip_reason=None,
        )

    def _record_monitor_close_if_terminal(
        self,
        *,
        previous_status: SpreadStatus,
        result: BullPutSpreadMonitorResult,
        runtime_state: BullPutStrategyRuntimeState,
    ) -> None:
        spread = result.spread
        if spread.status != SpreadStatus.CLOSED or previous_status == SpreadStatus.CLOSED:
            return
        realized_pnl = result.estimated_pnl
        if realized_pnl is None:
            realized_pnl = self._realized_pnl_from_orders(spread)
        spread = self._persist_closed_spread_metrics(
            spread=spread,
            realized_pnl=realized_pnl,
            evaluated_at=result.evaluated_at,
        )
        result.spread = spread
        runtime_state = self._update_runtime_state(
            runtime_state,
            daily_realized_pnl=runtime_state.daily_realized_pnl + (realized_pnl or Decimal("0")),
            last_action=f"Closed bull put spread for {spread.underlying_symbol} via {spread.exit_reason or 'manual_close'}.",
            last_action_at=result.evaluated_at,
            last_error=None,
        )
        self._log_spread_close(spread=spread, realized_pnl=realized_pnl, evaluated_at=result.evaluated_at)
        self._update_runtime_state(
            runtime_state,
            last_scan_result=runtime_state.last_scan_result,
            last_skip_reason=None,
        )
        if self.settings.bull_put_strategy.auto_review_enabled:
            try:
                self.run_review(
                    external_account_id=spread.external_account_id,
                    mode=spread.mode,
                    as_of=result.evaluated_at,
                )
            except Exception:
                logger.exception("Bull put review generation failed after spread close %s", spread.id)

    def _log_spread_entry_open(
        self,
        *,
        spread: BullPutSpread,
        preview: BullPutSpreadScanResult,
    ) -> None:
        if self._spread_journal_flag(spread, "entry_logged_at"):
            return
        candidate = preview.candidate
        risk = preview.risk
        if candidate is None or risk is None:
            return
        self._safe_create_journal_entry(
            CreateJournalEntryRequest(
                external_account_id=spread.external_account_id,
                symbol=spread.underlying_symbol,
                entry_type=JournalEntryType.PLAN,
                title=f"Bull put spread opened for {spread.underlying_symbol}",
                notes=(
                    f"Spread {spread.id} opened {spread.contracts}x "
                    f"{candidate.long_put.strike}/{candidate.short_put.strike} puts expiring {spread.expiration_date}. "
                    f"Entry credit {self._format_decimal(spread.entry_net_credit)}. "
                    f"Max profit {self._format_decimal(risk.max_profit)}, max loss {self._format_decimal(risk.max_loss)}."
                ),
                tags=["strategy", "bull-put", "entry", "paper"],
            ),
            context=f"bull put entry open {spread.id}",
        )
        self._mark_spread_journal_flag(spread, "entry_logged_at")

    def _log_spread_entry_failure(self, spread: BullPutSpread, *, reason: str) -> None:
        if self._spread_journal_flag(spread, "entry_failure_logged_at"):
            return
        self._safe_create_journal_entry(
            CreateJournalEntryRequest(
                external_account_id=spread.external_account_id,
                symbol=spread.underlying_symbol,
                entry_type=JournalEntryType.NOTE,
                title=f"Bull put entry failed for {spread.underlying_symbol}",
                notes=f"Spread {spread.id} did not open cleanly. Final status {spread.status.value}. Reason: {reason}.",
                tags=["strategy", "bull-put", "entry-failed", "paper"],
            ),
            context=f"bull put entry failure {spread.id}",
        )
        self._mark_spread_journal_flag(spread, "entry_failure_logged_at")

    def _build_review_recommendation(
        self,
        *,
        count: int,
        total_realized_pnl: Decimal,
        take_profit_rate: Decimal | None,
        stop_loss_rate: Decimal | None,
    ) -> tuple[str, str, str | None, str | None, str | None, str | None]:
        strategy = self.settings.bull_put_strategy
        if count < strategy.review_min_spreads_for_suggestion:
            return (
                "no_change",
                "Recent closed bull put spreads do not justify a parameter change yet.",
                None,
                None,
                None,
                None,
            )

        if (
            stop_loss_rate is not None
            and stop_loss_rate >= Decimal("0.35")
            and total_realized_pnl < 0
        ):
            suggested_delta = max(
                strategy.short_delta_min,
                strategy.short_delta_target - strategy.review_delta_step,
            )
            summary = (
                f"Stop-loss exits were elevated over the last {count} closed spreads. "
                f"Suggest tightening short delta target from {strategy.short_delta_target:.2f} to {suggested_delta:.2f}."
            )
            return (
                "suggested",
                summary,
                summary,
                "short_delta_target",
                f"{strategy.short_delta_target:.2f}",
                f"{suggested_delta:.2f}",
            )

        if (
            take_profit_rate is not None
            and take_profit_rate >= Decimal("0.75")
            and total_realized_pnl > 0
        ):
            suggested_credit = strategy.min_mid_credit + strategy.review_credit_step
            summary = (
                f"Take-profit exits dominated the last {count} closed spreads. "
                f"Suggest raising minimum mid credit from {strategy.min_mid_credit:.2f} to {suggested_credit:.2f}."
            )
            return (
                "suggested",
                summary,
                summary,
                "min_mid_credit",
                f"{strategy.min_mid_credit:.2f}",
                f"{suggested_credit:.2f}",
            )

        return (
            "no_change",
            "Recent closed bull put spreads do not justify a parameter change.",
            None,
            None,
            None,
            None,
        )

    def _create_strategy_review_entry(
        self,
        *,
        external_account_id: str,
        reviewed_metrics: list[tuple[BullPutSpread, Decimal]],
        evaluated_at: datetime,
        review_status: str,
        summary: str,
        recommendation: str | None,
    ):
        primary_symbol = self._primary_review_symbol(reviewed_metrics)
        notes = (
            f"Bull put review at {evaluated_at.isoformat()} considered {len(reviewed_metrics)} closed spreads. "
            f"{summary}"
        )
        if recommendation is not None:
            notes = f"{notes} Recommendation: {recommendation}"
        try:
            return self.journal_service.create_entry(
                CreateJournalEntryRequest(
                    external_account_id=external_account_id,
                    symbol=primary_symbol,
                    entry_type=JournalEntryType.REVIEW,
                    title="Bull put strategy review",
                    notes=notes,
                    tags=["strategy", "bull-put", "review", review_status, "paper"],
                )
            )
        except Exception:
            logger.exception("Bull put strategy review journal write failed for %s", external_account_id)
            return None

    def _primary_review_symbol(self, reviewed_metrics: list[tuple[BullPutSpread, Decimal]]) -> str:
        if not reviewed_metrics:
            return self.settings.bull_put_strategy.symbols[0]
        counts: dict[str, int] = {}
        for spread, _ in reviewed_metrics:
            counts[spread.underlying_symbol] = counts.get(spread.underlying_symbol, 0) + 1
        return max(counts.items(), key=lambda item: item[1])[0]

    def _log_spread_close(
        self,
        *,
        spread: BullPutSpread,
        realized_pnl: Decimal | None,
        evaluated_at: datetime,
    ) -> None:
        if self._spread_journal_flag(spread, "close_logged_at"):
            return
        self._safe_create_journal_entry(
            CreateJournalEntryRequest(
                external_account_id=spread.external_account_id,
                symbol=spread.underlying_symbol,
                entry_type=JournalEntryType.REVIEW,
                title=f"Bull put spread closed for {spread.underlying_symbol}",
                notes=(
                    f"Spread {spread.id} closed on {evaluated_at.date()} via {spread.exit_reason or 'manual_close'}. "
                    f"Estimated realized PnL {self._format_decimal(realized_pnl)}."
                ),
                tags=["strategy", "bull-put", "close", spread.exit_reason or "manual-close", "paper"],
            ),
            context=f"bull put close {spread.id}",
        )
        self._mark_spread_journal_flag(spread, "close_logged_at")

    def _log_scan_skip(self, *, preview: BullPutSpreadScanResult, automatic: bool) -> None:
        reason = preview.reasons[0] if preview.reasons else "No bull put spread candidate was eligible."
        self._safe_create_journal_entry(
            CreateJournalEntryRequest(
                external_account_id=preview.external_account_id,
                symbol=preview.symbol,
                entry_type=JournalEntryType.NOTE,
                title=f"Bull put scan skipped for {preview.symbol}",
                notes=(
                    f"{'Automatic' if automatic else 'Manual'} bull put scan at {preview.scanned_at.isoformat()} skipped "
                    f"{preview.symbol}. Reason: {reason}."
                ),
                tags=["strategy", "bull-put", "scan", "skip", "paper"],
            ),
            context=f"bull put scan skip {preview.symbol}",
        )

    @staticmethod
    def _format_decimal(value: Decimal | None) -> str:
        if value is None:
            return "--"
        return f"{value:.2f}"

    def _mark_spread_journal_flag(self, spread: BullPutSpread, key: str) -> BullPutSpread:
        raw_payload = dict(spread.raw_payload or {})
        journal_meta = dict(raw_payload.get("journal") or {})
        journal_meta[key] = datetime.now(timezone.utc).isoformat()
        raw_payload["journal"] = journal_meta
        return self._update_spread(
            spread,
            raw_payload=raw_payload,
            updated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _spread_journal_flag(spread: BullPutSpread, key: str) -> bool:
        raw_payload = spread.raw_payload or {}
        journal_meta = raw_payload.get("journal") or {}
        return key in journal_meta

    def _realized_pnl_from_orders(self, spread: BullPutSpread) -> Decimal | None:
        if spread.entry_net_credit is None:
            return None
        short_exit_order = self._refresh_if_present(spread.short_exit_order_id)
        long_exit_order = self._refresh_if_present(spread.long_exit_order_id)
        short_exit_price = self._effective_fill_price(short_exit_order)
        long_exit_price = self._effective_fill_price(long_exit_order)
        if short_exit_price is None or long_exit_price is None:
            return None
        exit_debit = short_exit_price - long_exit_price
        return (spread.entry_net_credit - exit_debit) * Decimal(spread.contracts) * Decimal("100")

    def _resolved_realized_pnl(self, spread: BullPutSpread) -> Decimal | None:
        raw_payload = spread.raw_payload or {}
        close_meta = raw_payload.get("close") or {}
        if close_meta.get("realized_pnl") is not None:
            return Decimal(str(close_meta["realized_pnl"]))
        if spread.entry_net_credit is None:
            return None
        short_exit_order = self._get_local_order_if_present(spread.short_exit_order_id)
        long_exit_order = self._get_local_order_if_present(spread.long_exit_order_id)
        short_exit_price = self._effective_fill_price(short_exit_order)
        long_exit_price = self._effective_fill_price(long_exit_order)
        if short_exit_price is None or long_exit_price is None:
            return None
        exit_debit = short_exit_price - long_exit_price
        return (spread.entry_net_credit - exit_debit) * Decimal(spread.contracts) * Decimal("100")

    def _persist_closed_spread_metrics(
        self,
        *,
        spread: BullPutSpread,
        realized_pnl: Decimal | None,
        evaluated_at: datetime,
    ) -> BullPutSpread:
        raw_payload = dict(spread.raw_payload or {})
        close_meta = dict(raw_payload.get("close") or {})
        close_meta.update(
            {
                "evaluated_at": evaluated_at.isoformat(),
                "exit_reason": spread.exit_reason,
                "realized_pnl": str(realized_pnl) if realized_pnl is not None else None,
            }
        )
        raw_payload["close"] = close_meta
        return self._update_spread(
            spread,
            raw_payload=raw_payload,
            updated_at=datetime.now(timezone.utc),
        )

    def _normalize_paused_symbols(self, symbols: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        configured = set(self.settings.bull_put_strategy.symbols)
        for symbol in symbols:
            value = symbol.strip().upper()
            if not value or value in seen or value not in configured:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    @staticmethod
    def _describe_runtime_update(updates: dict) -> str:
        parts: list[str] = []
        for key, value in updates.items():
            if key == "paused_symbols":
                rendered = ", ".join(value) if value else "none"
                parts.append(f"paused symbols={rendered}")
            else:
                parts.append(f"{key}={value}")
        return "Updated bull put runtime controls: " + "; ".join(parts)

    def _session_date(self, as_of: datetime) -> date:
        return as_of.astimezone(self.new_york).date()

    def _market_session_label(self, as_of: datetime) -> str:
        local_time = as_of.astimezone(self.new_york)
        if local_time.weekday() >= 5:
            return "weekend"
        session_minutes = (local_time.hour * 60) + local_time.minute
        if session_minutes < 570:
            return "premarket"
        if session_minutes < 960:
            return "regular"
        return "postmarket"

    def _minutes_to_regular_open(self, as_of: datetime, session: str) -> int | None:
        if session != "premarket":
            return None
        local_time = as_of.astimezone(self.new_york)
        open_minutes = (9 * 60) + 30
        session_minutes = (local_time.hour * 60) + local_time.minute
        return max(open_minutes - session_minutes, 0)

    def _build_pre_open_signal(
        self,
        *,
        key: str,
        label: str,
        quote: SecurityQuoteSnapshot,
        session: str,
    ) -> PreOpenProxySignal:
        session_price = self._quote_session_price(quote=quote, session=session)
        reference_price = quote.prev_close
        change_pct = Decimal("0")
        if reference_price not in {Decimal("0"), None}:
            change_pct = ((session_price - reference_price) / reference_price) * Decimal("100")
        signal = "neutral"
        note = None
        if key == "oil":
            if change_pct >= Decimal("1.25"):
                signal = "bearish"
                note = "Higher oil tends to pressure inflation expectations."
            elif change_pct <= Decimal("-1.25"):
                signal = "supportive"
                note = "Lower oil tends to relieve inflation pressure."
        elif key == "rates":
            if change_pct <= Decimal("-0.60"):
                signal = "bearish"
                note = "Long Treasuries lower implies higher yield pressure."
            elif change_pct >= Decimal("0.60"):
                signal = "supportive"
                note = "Long Treasuries firmer implies some rate relief."
        else:
            if change_pct <= Decimal("-0.60"):
                signal = "bearish"
            elif change_pct >= Decimal("0.60"):
                signal = "supportive"

        return PreOpenProxySignal(
            key=key,
            label=label,
            symbol=quote.symbol,
            session_price=session_price,
            reference_price=reference_price,
            change_pct=change_pct.quantize(Decimal("0.01")),
            signal=signal,
            note=note,
        )

    def _quote_session_price(self, *, quote: SecurityQuoteSnapshot, session: str) -> Decimal:
        if session == "premarket" and quote.pre_market_quote is not None:
            return quote.pre_market_quote.last_done
        if session == "postmarket" and quote.post_market_quote is not None:
            return quote.post_market_quote.last_done
        return quote.last_done

    def _build_directional_put_snapshots(
        self,
        *,
        evaluated_at: datetime,
        spy_signal: PreOpenProxySignal,
        qqq_signal: PreOpenProxySignal,
    ) -> list[DirectionalPutSnapshot]:
        snapshots: list[DirectionalPutSnapshot] = []
        for signal in (spy_signal, qqq_signal):
            snapshot = self._nearest_directional_put_snapshot(
                symbol=signal.symbol,
                underlying_price=signal.session_price,
                evaluated_at=evaluated_at,
            )
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    def _nearest_directional_put_snapshot(
        self,
        *,
        symbol: str,
        underlying_price: Decimal,
        evaluated_at: datetime,
    ) -> DirectionalPutSnapshot | None:
        expiry_dates = self.longbridge_adapter.list_option_expiry_dates(
            symbol=symbol,
            mode=ExecutionMode.PAPER,
        )
        expiry_date = self._select_pre_open_put_expiration(expiry_dates, evaluated_at)
        if expiry_date is None:
            return None
        chain = self.longbridge_adapter.list_option_chain(
            symbol=symbol,
            expiry_date=expiry_date,
            mode=ExecutionMode.PAPER,
        )
        put_symbols = [entry.put_symbol for entry in chain if entry.standard and entry.put_symbol]
        if not put_symbols:
            return None
        put_quotes = self.longbridge_adapter.get_option_market_snapshots(
            symbols=put_symbols,
            mode=ExecutionMode.PAPER,
        )
        if not put_quotes:
            return None
        selected = min(
            put_quotes,
            key=lambda quote: (abs(quote.strike - underlying_price), quote.expiration_date),
        )
        selected = self._with_top_of_book(selected, mode=ExecutionMode.PAPER)
        return DirectionalPutSnapshot(
            underlying_symbol=symbol,
            expiration_date=selected.expiration_date,
            days_to_expiration=self._days_to_expiration(selected.expiration_date, evaluated_at),
            strike=selected.strike,
            put_symbol=selected.symbol,
            bid=selected.bid,
            ask=selected.ask,
            delta=selected.delta,
            implied_volatility=selected.implied_volatility,
        )

    def _select_pre_open_put_expiration(
        self,
        expiry_dates: list[date],
        evaluated_at: datetime,
    ) -> date | None:
        strategy = self.settings.bull_put_strategy
        evaluated_date = evaluated_at.astimezone(self.new_york).date()
        candidates = [
            expiry_date
            for expiry_date in expiry_dates
            if strategy.pre_open_put_min_dte <= (expiry_date - evaluated_date).days <= strategy.pre_open_put_max_dte
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda expiry_date: (expiry_date - evaluated_date).days)

    def _safe_create_journal_entry(self, request: CreateJournalEntryRequest, *, context: str) -> None:
        try:
            self.journal_service.create_entry(request)
        except Exception:
            logger.exception("Bull put strategy journal write failed during %s", context)

    def _assert_entry_capacity(
        self,
        *,
        external_account_id: str,
        symbol: str,
        runtime_state: BullPutStrategyRuntimeState,
    ) -> None:
        runtime_reason = self._runtime_entry_block_reason(
            state=runtime_state,
            symbol=symbol,
        )
        if runtime_reason is not None:
            raise ValueError(runtime_reason)
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

    def _submit_entry_leg_with_repricing(
        self,
        *,
        spread: BullPutSpread,
        external_account_id: str,
        leg: OptionMarketSnapshot,
        side: OrderSide,
        quantity: int,
        mode: ExecutionMode,
        remark: str | None,
        price_ladder: list[Decimal | None],
        order_id_field: str,
    ) -> tuple[BullPutSpread, Order]:
        if not price_ladder:
            raise ValueError(f"No valid repricing ladder was available for {leg.symbol}.")
        last_order: Order | None = None
        for limit_price in price_ladder:
            submitted = self.order_service.submit_order(
                self._build_leg_order_request(
                    external_account_id=external_account_id,
                    leg=leg,
                    side=side,
                    quantity=quantity,
                    mode=mode,
                    order_type=OrderType.LIMIT,
                    limit_price=limit_price,
                    remark=remark,
                )
            )
            spread = self._update_spread(
                spread,
                **{
                    order_id_field: submitted.id,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            current = self._await_terminal_or_fill(submitted)
            if self._is_filled(current):
                return spread, current
            last_order = self._cancel_if_working(current) or current
        if last_order is None:
            raise ValueError(f"Unable to submit any repricing attempt for {leg.symbol}.")
        return spread, last_order

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
        strategy = self.settings.bull_put_strategy
        deadline = time.monotonic() + strategy.entry_fill_timeout_seconds
        first_refresh = True
        while True:
            if not first_refresh and strategy.entry_fill_poll_interval_seconds > 0:
                time.sleep(strategy.entry_fill_poll_interval_seconds)
            first_refresh = False
            current = self.order_service.refresh_order(current.id)
            if self._is_terminal(current) or self._is_filled(current):
                return current
            if time.monotonic() >= deadline:
                return current

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

    def _get_local_order_if_present(self, order_id: str | None) -> Order | None:
        if order_id is None:
            return None
        return self.order_service.get_order(order_id)

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

    def _entry_long_limit_price(
        self,
        *,
        long_leg: OptionMarketSnapshot,
        short_leg: OptionMarketSnapshot,
        width: Decimal,
    ) -> Decimal | None:
        if long_leg.ask is None:
            return None
        strategy = self.settings.bull_put_strategy
        buffered_price = long_leg.ask + strategy.entry_long_limit_buffer
        if short_leg.bid is None:
            return buffered_price
        min_credit_floor = width * strategy.min_conservative_credit_per_width_ratio
        max_price_for_credit = short_leg.bid - min_credit_floor
        if max_price_for_credit <= long_leg.ask:
            return long_leg.ask
        return min(buffered_price, max_price_for_credit)

    def _entry_long_price_ladder(
        self,
        *,
        ask_price: Decimal | None,
        capped_price: Decimal | None,
    ) -> list[Decimal | None]:
        if ask_price is None:
            return []
        limit_cap = capped_price or ask_price
        return self._price_ladder(
            start=ask_price,
            end=max(ask_price, limit_cap),
            ascending=True,
        )

    def _entry_short_price_ladder(
        self,
        *,
        bid_price: Decimal | None,
        filled_long_price: Decimal | None,
        width: Decimal,
    ) -> list[Decimal | None]:
        if bid_price is None:
            return []
        floor = bid_price
        if filled_long_price is not None:
            min_credit_floor = width * self.settings.bull_put_strategy.min_conservative_credit_per_width_ratio
            floor = max(floor - (self.settings.bull_put_strategy.entry_reprice_increment * self.settings.bull_put_strategy.entry_reprice_max_steps), filled_long_price + min_credit_floor)
        return self._price_ladder(
            start=bid_price,
            end=min(bid_price, floor),
            ascending=False,
        )

    def _price_ladder(
        self,
        *,
        start: Decimal,
        end: Decimal,
        ascending: bool,
    ) -> list[Decimal]:
        strategy = self.settings.bull_put_strategy
        step = strategy.entry_reprice_increment
        prices: list[Decimal] = [self._quantize_price(start)]
        current = start
        for _ in range(strategy.entry_reprice_max_steps):
            candidate = current + step if ascending else current - step
            if ascending and candidate >= end:
                break
            if not ascending and candidate <= end:
                break
            prices.append(self._quantize_price(candidate))
            current = candidate
        end_price = self._quantize_price(end)
        if prices[-1] != end_price:
            prices.append(end_price)
        return prices

    @staticmethod
    def _quantize_price(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"))

    @staticmethod
    def _mid_price(quote: OptionMarketSnapshot) -> Decimal | None:
        if quote.bid is None or quote.ask is None:
            return None
        return (quote.bid + quote.ask) / Decimal("2")
