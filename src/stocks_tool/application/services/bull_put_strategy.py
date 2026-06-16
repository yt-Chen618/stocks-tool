from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.application.services.journal import JournalService
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.application.services.bull_put.calendar import (
    is_us_options_trading_day as compute_is_us_options_trading_day,
    market_session_label as compute_market_session_label,
    minutes_to_regular_open as compute_minutes_to_regular_open,
    next_regular_open_at as compute_next_regular_open_at,
    next_us_options_trading_day as compute_next_us_options_trading_day,
    session_date as compute_session_date,
    target_session_date as compute_target_session_date,
)
from stocks_tool.application.services.bull_put.candidate import (
    entry_long_limit_price as compute_entry_long_limit_price,
    entry_long_price_ladder as compute_entry_long_price_ladder,
    entry_short_price_ladder as compute_entry_short_price_ladder,
    has_tradeable_long_leg as compute_has_tradeable_long_leg,
    is_option_quote_fresh as compute_is_option_quote_fresh,
    is_short_put_candidate as compute_is_short_put_candidate,
    mid_price as compute_mid_price,
    option_leg_liquidity_reasons as compute_option_leg_liquidity_reasons,
    passes_top_of_book_filters as compute_passes_top_of_book_filters,
    price_ladder as compute_price_ladder,
    quantize_price as compute_quantize_price,
    select_expiration_date as compute_select_expiration_date,
)
from stocks_tool.application.services.bull_put.runtime import (
    next_monitor_after as compute_next_monitor_after,
    open_spread_count as compute_open_spread_count,
    runtime_account_entry_block_reason as compute_runtime_account_entry_block_reason,
    runtime_entry_block_reason as compute_runtime_entry_block_reason,
    runtime_next_action as compute_runtime_next_action,
)
from stocks_tool.application.services.bull_put.monitor import (
    days_to_expiration as compute_days_to_expiration,
    determine_exit_reason as compute_exit_reason,
    estimated_exit_debit as compute_estimated_exit_debit,
    estimated_pnl as compute_estimated_pnl,
)
from stocks_tool.application.services.strategy_lifecycle import (
    BULL_PUT_CLOSE_ORDER_WARNING,
    bull_put_close_order_lifecycle_payload,
    bull_put_close_order_warning,
    bull_put_lifecycle_summary,
)
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
    BullPutRecoverCloseEligibility,
    BullPutStrategyReadinessCheck,
    BullPutStrategyReadinessResult,
    BullPutSpreadScanResult,
    BullPutStrategyReviewResult,
    BullPutStrategyRuntimeState,
    BullPutStrategyScanRunResult,
    CreateOrderRequest,
    CreateStrategyAuditEventRequest,
    CreateJournalEntryRequest,
    DirectionalPutSnapshot,
    ExecuteBullPutSpreadRequest,
    HistoricalPriceBar,
    OptionChainAnalysis,
    OptionChainExpiryAnalysis,
    OptionChainLiquidStrike,
    OptionMarketSnapshot,
    OptionContractRef,
    Order,
    PreOpenCheckpoint,
    PreOpenAssessmentCaptureResult,
    PreOpenAssessmentReviewResult,
    PreOpenDownsideAssessment,
    PreOpenProxySignal,
    PreOpenAssessmentRun,
    PreOpenReviewCheckpoint,
    RecoverBullPutCloseRequest,
    UpdateBullPutStrategyRuntimeRequest,
)
from stocks_tool.ports.broker_gateway import BrokerMarketDataGateway
from stocks_tool.ports.repository import (
    AccountSnapshotRepository,
    BrokerAccountRepository,
    BullPutSpreadRepository,
    BullPutStrategyRuntimeRepository,
    PreOpenAssessmentRunRepository,
    StrategyAuditEventRepository,
)


ACTIVE_SPREAD_STATUSES = {
    SpreadStatus.ENTRY_PENDING_LONG,
    SpreadStatus.ENTRY_PENDING_SHORT,
    SpreadStatus.OPEN,
    SpreadStatus.EXIT_PENDING_SHORT,
    SpreadStatus.EXIT_PENDING_LONG,
}
logger = logging.getLogger(__name__)
PRE_OPEN_CAPTURE_START = datetime_time(hour=8, minute=30)
PRE_OPEN_CAPTURE_END = datetime_time(hour=9, minute=15)
PRE_OPEN_REVIEW_CHECKPOINTS = (
    ("open", "Opening Print", "09:30 ET", datetime_time(hour=9, minute=30)),
    ("first_15", "First 15 Minutes", "09:45 ET", datetime_time(hour=9, minute=45)),
    ("first_30", "First 30 Minutes", "10:00 ET", datetime_time(hour=10, minute=0)),
)


class BullPutStrategyService:
    _preview_cache: dict[tuple[str, str, str, str], tuple[datetime, BullPutSpreadScanResult]] = {}
    _close_order_warning_code = BULL_PUT_CLOSE_ORDER_WARNING

    def __init__(
        self,
        *,
        settings: Settings,
        broker_accounts: BrokerAccountRepository,
        account_snapshots: AccountSnapshotRepository,
        spreads: BullPutSpreadRepository,
        runtime_states: BullPutStrategyRuntimeRepository,
        pre_open_runs: PreOpenAssessmentRunRepository,
        order_service: OrderService,
        longbridge_adapter: BrokerMarketDataGateway,
        risk_service: RiskService,
        journal_service: JournalService,
        audit_events: StrategyAuditEventRepository | None = None,
    ) -> None:
        self.settings = settings
        self.broker_accounts = broker_accounts
        self.account_snapshots = account_snapshots
        self.spreads = spreads
        self.runtime_states = runtime_states
        self.pre_open_runs = pre_open_runs
        self.order_service = order_service
        self.longbridge_adapter = longbridge_adapter
        self.risk_service = risk_service
        self.journal_service = journal_service
        self.audit_events = audit_events
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

    def check_entry_readiness(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
        symbol: str | None = None,
    ) -> BullPutStrategyReadinessResult:
        evaluated_at = as_of or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        checks: list[BullPutStrategyReadinessCheck] = []
        previews: list[BullPutSpreadScanResult] = []
        strategy = self.settings.bull_put_strategy
        target_symbols = (symbol,) if symbol is not None else strategy.symbols
        unsupported_symbols = [target for target in target_symbols if target not in strategy.symbols]
        if unsupported_symbols:
            unsupported = ", ".join(unsupported_symbols)
            raise ValueError(
                f"Symbol '{unsupported}' is outside the configured bull put spread universe: {', '.join(strategy.symbols)}."
            )

        def add_check(name: str, status: str, detail: str, *, blocking: bool = False) -> None:
            checks.append(
                BullPutStrategyReadinessCheck(
                    name=name,
                    status=status,
                    detail=detail,
                    blocking=blocking,
                )
            )

        broker_account = self.broker_accounts.get_by_external_account_id(external_account_id)
        if broker_account is None or broker_account.broker != BrokerName.LONGBRIDGE:
            add_check(
                "broker_account",
                "blocked",
                f"No local Longbridge broker account was found for '{external_account_id}'.",
                blocking=True,
            )
            return self._build_readiness_result(
                external_account_id=external_account_id,
                mode=mode,
                evaluated_at=evaluated_at,
                checks=checks,
                previews=previews,
                next_action="Sync or create the Longbridge paper broker account before checking entries.",
            )
        add_check("broker_account", "ok", f"Longbridge paper account {external_account_id} is configured.")

        if mode != ExecutionMode.PAPER:
            add_check("execution_mode", "blocked", "paper_bull_put_v1 currently supports paper mode only.", blocking=True)
        else:
            add_check("execution_mode", "ok", "Paper execution mode is selected.")

        if not strategy.enabled:
            add_check("strategy_config", "blocked", "Bull put spread strategy is disabled by configuration.", blocking=True)
        else:
            add_check("strategy_config", "ok", "Bull put spread strategy is enabled.")

        runtime_state = self._prepare_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
            as_of=evaluated_at,
        )
        runtime_reason = self._runtime_account_entry_block_reason(state=runtime_state)
        if runtime_reason is not None:
            add_check("runtime_controls", "blocked", runtime_reason, blocking=True)
        else:
            add_check("runtime_controls", "ok", "Runtime controls allow a new bull put entry.")

        session_reason = self._entry_session_gate_reason(evaluated_at)
        if session_reason is not None:
            add_check("entry_window", "blocked", session_reason, blocking=True)
        else:
            add_check("entry_window", "ok", "Current time is inside the configured bull put entry window.")

        if any(check.blocking for check in checks):
            return self._build_readiness_result(
                external_account_id=external_account_id,
                mode=mode,
                evaluated_at=evaluated_at,
                checks=checks,
                previews=previews,
                next_action="Resolve the blocking checks before previewing or executing a bull put spread.",
            )

        eligible_previews: list[BullPutSpreadScanResult] = []
        capacity_block: str | None = None
        preview_errors: list[str] = []
        for symbol in target_symbols:
            try:
                preview = self.preview_spread(
                    external_account_id=external_account_id,
                    symbol=symbol,
                    mode=mode,
                    as_of=evaluated_at,
                )
            except Exception as exc:
                preview_errors.append(f"{symbol}: {exc}")
                continue
            previews.append(preview)
            if not preview.eligible:
                continue
            try:
                self._assert_entry_capacity(
                    external_account_id=external_account_id,
                    symbol=symbol,
                    runtime_state=runtime_state,
                )
            except ValueError as exc:
                capacity_block = str(exc)
                continue
            eligible_previews.append(preview)

        if preview_errors:
            add_check(
                "candidate_scan",
                "warning" if previews else "blocked",
                "; ".join(preview_errors),
                blocking=not previews,
            )

        if capacity_block is not None:
            add_check("entry_capacity", "blocked", capacity_block, blocking=True)
        elif eligible_previews:
            add_check(
                "entry_capacity",
                "ok",
                f"Entry capacity is available for {eligible_previews[0].symbol}.",
            )

        if eligible_previews:
            best = eligible_previews[0]
            add_check("candidate", "ok", f"{best.symbol} has an eligible bull put candidate.")
            return self._build_readiness_result(
                external_account_id=external_account_id,
                mode=mode,
                evaluated_at=evaluated_at,
                checks=checks,
                previews=previews,
                preferred_symbol=best.symbol,
                next_action=f"Review the {best.symbol} preview, then execute only if the live quote still matches the candidate.",
            )

        if not any(check.blocking for check in checks):
            add_check(
                "candidate",
                "watching",
                "No configured symbol currently satisfies the bull put liquidity, trend, credit, and risk filters.",
            )
        return self._build_readiness_result(
            external_account_id=external_account_id,
            mode=mode,
            evaluated_at=evaluated_at,
            checks=checks,
            previews=previews,
            next_action="Keep monitoring; do not execute until a readiness check reports an eligible candidate.",
        )

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
        external_account_id: str | None = None,
        allow_fallback: bool = True,
        include_option_overlays: bool = True,
    ) -> PreOpenDownsideAssessment:
        evaluated_at = as_of or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        try:
            return self._build_live_pre_open_downside_assessment(
                evaluated_at,
                include_option_overlays=include_option_overlays,
            )
        except LongbridgeIntegrationError as exc:
            if isinstance(exc, (LongbridgeDependencyError, LongbridgeConfigurationError)):
                raise
            if not allow_fallback or not self._is_transient_longbridge_failure(exc):
                raise
            fallback_run = self._latest_pre_open_run(external_account_id=external_account_id)
            if fallback_run is None:
                return self._build_unavailable_pre_open_assessment(
                    evaluated_at=evaluated_at,
                    error=exc,
                )
            return self._build_stale_pre_open_assessment(
                run=fallback_run,
                error=exc,
            )

    def _build_live_pre_open_downside_assessment(
        self,
        evaluated_at: datetime,
        *,
        include_option_overlays: bool = True,
    ) -> PreOpenDownsideAssessment:
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        session = self._market_session_label(evaluated_at)
        target_session_date = self._target_session_date(evaluated_at, session=session)
        next_regular_open_at = self._next_regular_open_at(
            evaluated_at=evaluated_at,
            session=session,
            target_session_date=target_session_date,
        )
        signal_specs = [
            ("spy", "S&P 500 ETF", self.settings.bull_put_strategy.pre_open_proxy_spy_symbol),
            ("qqq", "Nasdaq 100 ETF", self.settings.bull_put_strategy.pre_open_proxy_qqq_symbol),
            ("semis", "Semiconductor Proxy", self.settings.bull_put_strategy.pre_open_proxy_semis_symbol),
            ("oil", "Oil Proxy", self.settings.bull_put_strategy.pre_open_proxy_oil_symbol),
            ("rates", "Rates Proxy", self.settings.bull_put_strategy.pre_open_proxy_rates_symbol),
        ]

        signals, signal_by_key, missing_signals, proxy_errors = self._load_pre_open_proxy_signals(
            signal_specs=signal_specs,
            session=session,
        )

        if not signal_by_key:
            if proxy_errors:
                raise LongbridgeIntegrationError(proxy_errors[0])
            raise LongbridgeIntegrationError("No pre-open proxy data could be loaded from Longbridge.")

        score = 0
        reasons: list[str] = []
        spy_change = signal_by_key.get("spy").change_pct if signal_by_key.get("spy") is not None else None
        qqq_change = signal_by_key.get("qqq").change_pct if signal_by_key.get("qqq") is not None else None
        semis_change = signal_by_key.get("semis").change_pct if signal_by_key.get("semis") is not None else None
        oil_change = signal_by_key.get("oil").change_pct if signal_by_key.get("oil") is not None else None
        rates_change = signal_by_key.get("rates").change_pct if signal_by_key.get("rates") is not None else None

        if qqq_change is not None and qqq_change <= Decimal("-0.60"):
            score += 2
            reasons.append("QQQ is trading meaningfully below its reference level.")
        if spy_change is not None and spy_change <= Decimal("-0.45"):
            score += 1
            reasons.append("SPY is leaning lower before the regular session.")
        if semis_change is not None and semis_change <= Decimal("-0.90"):
            score += 2
            reasons.append("Semiconductor leadership is weakening faster than the broad market.")
        if oil_change is not None and oil_change >= Decimal("1.25"):
            score += 1
            reasons.append("Oil proxy strength points to fresh inflation and geopolitical pressure.")
        if rates_change is not None and rates_change <= Decimal("-0.60"):
            score += 1
            reasons.append("Long-duration Treasuries are slipping, which implies higher yield pressure.")
        if qqq_change is not None and spy_change is not None and (qqq_change - spy_change) <= Decimal("-0.30"):
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
            semis_underperforming = (
                semis_change is not None
                and spy_change is not None
                and semis_change <= spy_change
            )
            if qqq_change is not None and (spy_change is None or semis_underperforming or qqq_change < spy_change):
                preferred_vehicle = "QQQ"
            elif spy_change is not None:
                preferred_vehicle = "SPY"
        if not reasons:
            reasons.append("No broad bearish proxy cluster is present right now.")
        if missing_signals:
            reasons.append(
                "Proxy data was unavailable for "
                f"{', '.join(missing_signals)}, so cross-market confirmation is incomplete."
            )

        trade_action, trade_action_detail = self._pre_open_trade_action(
            session=session,
            downside_score=score,
            preferred_vehicle=preferred_vehicle,
            qqq_change=qqq_change,
            spy_change=spy_change,
            semis_change=semis_change,
        )
        gap_chase_risk, gap_chase_detail = self._pre_open_gap_risk(
            downside_score=score,
            qqq_change=qqq_change,
            spy_change=spy_change,
            semis_change=semis_change,
        )
        put_snapshots: list[DirectionalPutSnapshot] = []
        chain_analyses: list[OptionChainAnalysis] = []
        missing_put_snapshots: list[str] = []
        missing_chain_analyses: list[str] = []
        overlay_signals = [signal_by_key[key] for key in ("spy", "qqq") if key in signal_by_key]
        if include_option_overlays:
            put_snapshots, missing_put_snapshots = self._build_directional_put_snapshots(
                evaluated_at=evaluated_at,
                signals=overlay_signals,
            )
            chain_analyses, missing_chain_analyses = self._build_option_chain_analyses(
                evaluated_at=evaluated_at,
                signals=overlay_signals,
            )
        missing_overlay_layers: list[str] = []
        if overlay_signals and not include_option_overlays:
            missing_overlay_layers.append("Option overlays skipped for fast macro refresh.")
            reasons.append(
                "Option overlays were skipped so the macro board can refresh without waiting on slow option-chain calls."
            )
        if missing_put_snapshots:
            missing_overlay_layers.append(
                "Directional put snapshots unavailable for "
                f"{', '.join(missing_put_snapshots)}."
            )
            reasons.append(
                "Directional put snapshots were unavailable for "
                f"{', '.join(missing_put_snapshots)}, so put-specific overlays are incomplete."
            )
        if missing_chain_analyses:
            missing_overlay_layers.append(
                "Option-chain analysis unavailable for "
                f"{', '.join(missing_chain_analyses)}."
            )
            reasons.append(
                "Option-chain analysis was unavailable for "
                f"{', '.join(missing_chain_analyses)}, so volatility and liquidity overlays are incomplete."
            )
        checkpoints = self._build_pre_open_checkpoints(
            evaluated_at=evaluated_at,
            session=session,
            trade_action=trade_action,
            preferred_vehicle=preferred_vehicle,
        )

        return PreOpenDownsideAssessment(
            analyzed_at=evaluated_at,
            session=session,
            market_open=session == "regular",
            target_session_date=target_session_date,
            minutes_to_regular_open=self._minutes_to_regular_open(evaluated_at, session),
            next_regular_open_at=next_regular_open_at,
            downside_score=score,
            regime=regime,
            plain_put_view=plain_put_view,
            preferred_vehicle=preferred_vehicle,
            trade_action=trade_action,
            trade_action_detail=trade_action_detail,
            gap_chase_risk=gap_chase_risk,
            gap_chase_detail=gap_chase_detail,
            summary=summary,
            reasons=reasons,
            checkpoints=checkpoints,
            signals=signals,
            put_snapshots=put_snapshots,
            chain_analyses=chain_analyses,
            freshness_status="partial" if missing_signals or missing_overlay_layers else "live",
            freshness_detail=(
                "Live Longbridge proxy data loaded successfully."
                if not missing_signals and not missing_overlay_layers
                else (
                    "Live board loaded with partial coverage. "
                    + " ".join(
                        part
                        for part in [
                            (
                                "Missing signals: "
                                f"{', '.join(missing_signals)}."
                                if missing_signals
                                else ""
                            ),
                            *missing_overlay_layers,
                        ]
                        if part
                    )
                )
            ),
        )

    def _load_pre_open_proxy_signals(
        self,
        *,
        signal_specs: list[tuple[str, str, str]],
        session: str,
    ) -> tuple[
        list[PreOpenProxySignal],
        dict[str, PreOpenProxySignal],
        list[str],
        list[str],
    ]:
        signals: list[PreOpenProxySignal] = []
        signal_by_key: dict[str, PreOpenProxySignal] = {}
        missing_signals: list[str] = []
        proxy_errors: list[str] = []
        symbols = [symbol for _, _, symbol in signal_specs]
        try:
            quotes_by_symbol = self.longbridge_adapter.get_quotes(
                symbols=symbols,
                mode=ExecutionMode.PAPER,
            )
        except LongbridgeIntegrationError as exc:
            return (
                [],
                {},
                [label for _, label, _ in signal_specs],
                [str(exc)],
            )

        for key, label, symbol in signal_specs:
            quote = quotes_by_symbol.get(symbol)
            if quote is None:
                missing_signals.append(label)
                logger.warning(
                    "Pre-open proxy %s (%s) was unavailable from the batch quote response; continuing with partial board when possible.",
                    label,
                    symbol,
                )
                continue
            signal = self._build_pre_open_signal(
                key=key,
                label=label,
                quote=quote,
                session=session,
            )
            signals.append(signal)
            signal_by_key[key] = signal
        return signals, signal_by_key, missing_signals, proxy_errors

    def _default_strategy_symbol(self) -> str:
        configured_symbols = self.settings.bull_put_strategy.symbols
        if configured_symbols:
            return configured_symbols[0]
        return self.settings.bull_put_strategy.pre_open_proxy_qqq_symbol

    def list_pre_open_runs(
        self,
        *,
        external_account_id: str | None = None,
        limit: int = 20,
    ) -> list[PreOpenAssessmentRun]:
        return self.pre_open_runs.list_runs(
            external_account_id=external_account_id,
            limit=limit,
        )

    def capture_pre_open_run(
        self,
        *,
        external_account_id: str,
        as_of: datetime | None = None,
        force: bool = False,
        automatic: bool = False,
        include_option_overlays: bool = False,
    ) -> PreOpenAssessmentCaptureResult:
        broker_account = self.broker_accounts.get_by_external_account_id(external_account_id)
        if broker_account is None or broker_account.broker != BrokerName.LONGBRIDGE:
            raise LookupError(f"No local Longbridge broker account was found for '{external_account_id}'.")

        evaluated_at = as_of or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        if automatic and not force:
            due_reason = self._pre_open_capture_not_due_reason(evaluated_at)
            if due_reason is not None:
                existing = self.pre_open_runs.list_runs(external_account_id=external_account_id, limit=1)
                fallback_run = existing[0] if existing else PreOpenAssessmentRun(
                    external_account_id=external_account_id,
                    target_session_date=self._target_session_date(evaluated_at),
                    assessment=self.get_pre_open_downside_assessment(
                        as_of=evaluated_at,
                        external_account_id=external_account_id,
                        allow_fallback=False,
                        include_option_overlays=include_option_overlays,
                    ),
                )
                return PreOpenAssessmentCaptureResult(
                    run=fallback_run,
                    captured=False,
                    reason=due_reason,
                )

        session = self._market_session_label(evaluated_at)
        target_session_date = self._target_session_date(evaluated_at, session=session)
        existing = self.pre_open_runs.get_by_session_date(
            external_account_id=external_account_id,
            target_session_date=target_session_date,
        )
        if existing is not None and not force:
            return PreOpenAssessmentCaptureResult(
                run=existing,
                captured=False,
                reason="Pre-open assessment already captured for the target session date.",
            )

        assessment = self.get_pre_open_downside_assessment(
            as_of=evaluated_at,
            external_account_id=external_account_id,
            allow_fallback=False,
            include_option_overlays=include_option_overlays,
        )
        run = existing or PreOpenAssessmentRun(
            external_account_id=external_account_id,
            target_session_date=assessment.target_session_date,
            assessment=assessment,
            checkpoints=self._build_review_checkpoints(assessment.target_session_date),
            review_status="awaiting_open",
        )
        run = run.model_copy(
            update={
                "target_session_date": assessment.target_session_date,
                "assessment": assessment,
                "review_status": run.review_status if run.checkpoints else "awaiting_open",
                "updated_at": evaluated_at,
            }
        )
        if not run.checkpoints:
            run = run.model_copy(update={"checkpoints": self._build_review_checkpoints(assessment.target_session_date)})
        stored = self.pre_open_runs.upsert_run(run)
        if not self._pre_open_run_flag(stored, "assessment_logged_at"):
            self._safe_create_journal_entry(
                CreateJournalEntryRequest(
                    external_account_id=external_account_id,
                    symbol=assessment.preferred_vehicle or self._default_strategy_symbol(),
                    entry_type=JournalEntryType.NOTE,
                    title=f"Pre-open downside assessment for {assessment.target_session_date.isoformat()}",
                    notes=self._pre_open_assessment_journal_notes(assessment),
                    tags=["strategy", "pre-open", "assessment", "paper"],
                ),
                context=f"pre-open assessment {stored.id}",
            )
            stored = self._mark_pre_open_run_flag(stored, "assessment_logged_at", evaluated_at)
        return PreOpenAssessmentCaptureResult(run=stored, captured=True)

    def review_pre_open_run(
        self,
        *,
        external_account_id: str,
        as_of: datetime | None = None,
        force: bool = False,
    ) -> PreOpenAssessmentReviewResult:
        evaluated_at = as_of or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        run = self._latest_reviewable_pre_open_run(
            external_account_id=external_account_id,
            as_of=evaluated_at,
        )
        if run is None:
            return PreOpenAssessmentReviewResult(
                reviewed=False,
                reason="No captured pre-open assessment is waiting for opening follow-through review.",
            )

        local_now = evaluated_at.astimezone(self.new_york)
        updated_checkpoint_keys: list[str] = []
        checkpoints: list[PreOpenReviewCheckpoint] = []
        for checkpoint in run.checkpoints:
            due = force or local_now >= checkpoint.scheduled_at.astimezone(self.new_york)
            if checkpoint.captured_at is not None and not force:
                checkpoints.append(checkpoint)
                continue
            if not due:
                checkpoints.append(checkpoint)
                continue
            reviewed_checkpoint = self._capture_pre_open_review_checkpoint(
                checkpoint=checkpoint,
                evaluated_at=evaluated_at,
            )
            checkpoints.append(reviewed_checkpoint)
            updated_checkpoint_keys.append(checkpoint.key)

        if not updated_checkpoint_keys and not force:
            return PreOpenAssessmentReviewResult(
                run=run,
                reviewed=False,
                reason="Pre-open assessment review is not due yet.",
            )

        review_status, review_summary, review_completed_at = self._summarize_pre_open_review(
            run=run,
            checkpoints=checkpoints,
            evaluated_at=evaluated_at,
        )
        updated_run = run.model_copy(
            update={
                "checkpoints": checkpoints,
                "review_status": review_status,
                "review_summary": review_summary,
                "last_reviewed_at": evaluated_at,
                "review_completed_at": review_completed_at,
                "updated_at": evaluated_at,
            }
        )
        stored = self.pre_open_runs.upsert_run(updated_run)
        if review_completed_at is not None and not self._pre_open_run_flag(stored, "review_logged_at"):
            self._safe_create_journal_entry(
                CreateJournalEntryRequest(
                    external_account_id=external_account_id,
                    symbol=stored.assessment.preferred_vehicle or self._default_strategy_symbol(),
                    entry_type=JournalEntryType.REVIEW,
                    title=f"Opening follow-through review for {stored.target_session_date.isoformat()}",
                    notes=stored.review_summary or "Opening follow-through review completed.",
                    tags=["strategy", "pre-open", "opening-review", review_status, "paper"],
                ),
                context=f"pre-open review {stored.id}",
            )
            stored = self._mark_pre_open_run_flag(stored, "review_logged_at", evaluated_at)
        return PreOpenAssessmentReviewResult(
            run=stored,
            reviewed=True,
            updated_checkpoint_keys=updated_checkpoint_keys,
        )

    def preview_spread(
        self,
        *,
        external_account_id: str,
        symbol: str,
        mode: ExecutionMode,
        as_of: datetime | None = None,
    ) -> BullPutSpreadScanResult:
        started_at = time.perf_counter()

        def finish(result: BullPutSpreadScanResult) -> BullPutSpreadScanResult:
            result.timing_ms["total"] = int((time.perf_counter() - started_at) * 1000)
            if result.eligible:
                self._store_preview_cache(result)
            return result

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
            return finish(result)

        if mode != ExecutionMode.PAPER:
            result.reasons.append("paper_bull_put_v1 currently supports paper mode only.")
            return finish(result)

        runtime_reason = self._runtime_entry_block_reason(
            state=runtime_state,
            symbol=symbol,
        )
        if runtime_reason is not None:
            result.reasons.append(runtime_reason)
            return finish(result)

        underlying_quote = self.longbridge_adapter.get_quote(symbol=symbol, mode=mode)
        result.underlying_quote = underlying_quote

        bars = self.longbridge_adapter.get_recent_daily_bars(symbol=symbol, count=60, mode=mode)
        if len(bars) < 50:
            result.reasons.append("At least 50 daily bars are required for trend filtering.")
            return finish(result)

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
            return finish(result)

        expiry_dates = self.longbridge_adapter.list_option_expiry_dates(symbol=symbol, mode=mode)
        selected_expiration_date = self._select_expiration_date(expiry_dates, scanned_at)
        if selected_expiration_date is None:
            result.reasons.append(
                "No listed option expiration date falls inside the configured 28-35 DTE window."
            )
            return finish(result)

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
            return finish(result)

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
            return finish(result)

        last_risk_reasons: list[str] = []
        last_liquidity_reasons: list[str] = []
        for short_put in ranked_short_puts:
            enriched_short = self._with_top_of_book(short_put, mode=mode)
            liquidity_reasons = self._option_leg_liquidity_reasons(
                short_leg=enriched_short,
                long_leg=None,
                scanned_at=scanned_at,
            )
            if liquidity_reasons:
                last_liquidity_reasons = liquidity_reasons
                continue

            long_put = option_quotes_by_strike.get(short_put.strike - width)
            if long_put is None:
                continue

            enriched_long = self._with_top_of_book(long_put, mode=mode)
            if not self._has_tradeable_long_leg(enriched_long):
                continue
            liquidity_reasons = self._option_leg_liquidity_reasons(
                short_leg=enriched_short,
                long_leg=enriched_long,
                scanned_at=scanned_at,
            )
            if liquidity_reasons:
                last_liquidity_reasons = liquidity_reasons
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
            result.candidate_token = self._build_candidate_token(result)
            return finish(result)

        if last_risk_reasons:
            result.reasons.extend(last_risk_reasons)
        elif last_liquidity_reasons:
            result.reasons.extend(last_liquidity_reasons)
        else:
            result.reasons.append(
                "No bull put spread candidate satisfied liquidity, width, credit, and risk filters."
            )
        return finish(result)

    def execute_spread(self, request: ExecuteBullPutSpreadRequest) -> BullPutSpread:
        execution_time = request.as_of or datetime.now(timezone.utc)
        if execution_time.tzinfo is None:
            execution_time = execution_time.replace(tzinfo=timezone.utc)
        session_reason = self._entry_session_gate_reason(execution_time)
        if session_reason is not None:
            raise ValueError(session_reason)

        preview = self._get_cached_preview_for_request(request)
        if preview is not None:
            preview = self._refresh_locked_preview_candidate(preview, as_of=execution_time)
        else:
            preview = self.preview_spread(
                external_account_id=request.external_account_id,
                symbol=request.symbol,
                mode=request.mode,
                as_of=execution_time,
            )
        self._assert_candidate_lock(request=request, preview=preview)
        return self._execute_preview_candidate(request=request, preview=preview)

    def _assert_candidate_lock(
        self,
        *,
        request: ExecuteBullPutSpreadRequest,
        preview: BullPutSpreadScanResult,
    ) -> None:
        if request.candidate_token is not None and preview.candidate_token != request.candidate_token:
            raise ValueError(
                "Bull put candidate changed since preview. Refresh the preview before executing."
            )
        if request.minimum_net_credit is None or preview.candidate is None:
            return
        if preview.candidate.conservative_credit < request.minimum_net_credit:
            raise ValueError(
                "Bull put candidate credit moved below the locked preview floor. Refresh the preview before executing."
            )

    def _get_cached_preview_for_request(
        self,
        request: ExecuteBullPutSpreadRequest,
    ) -> BullPutSpreadScanResult | None:
        if request.candidate_token is None:
            return None
        if self.settings.bull_put_strategy.preview_cache_ttl_seconds <= 0:
            return None
        key = (
            request.external_account_id,
            request.mode.value,
            request.symbol,
            request.candidate_token,
        )
        cached = self._preview_cache.get(key)
        if cached is None:
            return None
        cached_at, preview = cached
        now = datetime.now(timezone.utc)
        if (now - cached_at).total_seconds() > self.settings.bull_put_strategy.preview_cache_ttl_seconds:
            self._preview_cache.pop(key, None)
            return None
        return preview.model_copy(deep=True)

    def _store_preview_cache(self, preview: BullPutSpreadScanResult) -> None:
        if preview.candidate_token is None:
            return
        key = (
            preview.external_account_id,
            preview.mode.value,
            preview.symbol,
            preview.candidate_token,
        )
        self._preview_cache[key] = (datetime.now(timezone.utc), preview.model_copy(deep=True))

    def _refresh_locked_preview_candidate(
        self,
        preview: BullPutSpreadScanResult,
        *,
        as_of: datetime | None,
    ) -> BullPutSpreadScanResult:
        if preview.candidate is None:
            return preview
        started_at = time.perf_counter()
        refreshed_at = as_of or datetime.now(timezone.utc)
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)

        quotes = self.longbridge_adapter.get_option_market_snapshots(
            symbols=[preview.candidate.short_put.symbol, preview.candidate.long_put.symbol],
            mode=preview.mode,
        )
        quote_by_symbol = {quote.symbol: quote for quote in quotes}
        short_leg = quote_by_symbol.get(preview.candidate.short_put.symbol)
        long_leg = quote_by_symbol.get(preview.candidate.long_put.symbol)
        if short_leg is None or long_leg is None:
            raise ValueError("Locked bull put candidate legs could not be refreshed before execution.")

        short_leg = self._with_top_of_book(short_leg, mode=preview.mode)
        long_leg = self._with_top_of_book(long_leg, mode=preview.mode)
        liquidity_reasons = self._option_leg_liquidity_reasons(
            short_leg=short_leg,
            long_leg=long_leg,
            scanned_at=refreshed_at,
        )
        if liquidity_reasons:
            return preview.model_copy(
                update={
                    "scanned_at": refreshed_at,
                    "eligible": False,
                    "reasons": liquidity_reasons,
                    "timing_ms": {
                        **preview.timing_ms,
                        "cache_hit": 1,
                        "locked_refresh": int((time.perf_counter() - started_at) * 1000),
                    },
                },
                deep=True,
            )

        short_mid = self._mid_price(short_leg)
        long_mid = self._mid_price(long_leg)
        if short_mid is None or long_mid is None:
            return preview.model_copy(
                update={
                    "scanned_at": refreshed_at,
                    "eligible": False,
                    "reasons": ["Locked bull put candidate no longer has a valid bid/ask midpoint."],
                },
                deep=True,
            )

        candidate = preview.candidate.model_copy(
            update={
                "short_put": short_leg,
                "long_put": long_leg,
                "short_mid": short_mid,
                "long_mid": long_mid,
                "mid_credit": short_mid - long_mid,
                "conservative_credit": (short_leg.bid or Decimal("0")) - (long_leg.ask or Decimal("0")),
            }
        )
        account_snapshot = self._get_latest_account_snapshot(preview.external_account_id)
        risk = self.risk_service.evaluate_bull_put_candidate(
            candidate=candidate,
            account=account_snapshot,
            strategy=self.settings.bull_put_strategy,
        )
        eligible = risk.status != RiskStatus.BLOCK
        return preview.model_copy(
            update={
                "scanned_at": refreshed_at,
                "eligible": eligible,
                "candidate": candidate,
                "risk": risk,
                "reasons": risk.reasons if not eligible else [],
                "warnings": risk.warnings,
                "timing_ms": {
                    **preview.timing_ms,
                    "cache_hit": 1,
                    "locked_refresh": int((time.perf_counter() - started_at) * 1000),
                },
            },
            deep=True,
        )

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

        actual_risk_updates = self._actual_entry_risk_updates(
            spread=spread,
            entry_net_credit=entry_net_credit,
        )
        opened = self._update_spread(
            spread,
            status=SpreadStatus.OPEN,
            entry_long_price=entry_long_price,
            entry_short_price=entry_short_price,
            entry_net_credit=entry_net_credit,
            **actual_risk_updates,
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
                updates.update(
                    self._actual_entry_risk_updates(
                        spread=spread,
                        entry_net_credit=updates["entry_net_credit"],
                    )
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

        lifecycle_payload = self._lifecycle_payload_for_close_order_state(
            spread=spread,
            status=updates.get("status", spread.status),
            short_exit_order=short_exit_order,
        )
        if lifecycle_payload is not None:
            updates["raw_payload"] = lifecycle_payload

        return self._update_spread(spread, **updates)

    def get_recover_close_eligibility(
        self,
        spread_id: str,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> BullPutRecoverCloseEligibility:
        spread = self._get_spread_or_raise(spread_id)
        return self._build_recover_close_eligibility(
            spread=spread,
            external_account_id=external_account_id,
            mode=mode,
            short_exit_order=self._get_local_order_if_present(spread.short_exit_order_id),
        )

    def recover_close(self, spread_id: str, request: RecoverBullPutCloseRequest) -> BullPutSpread:
        spread = self._get_spread_or_raise(spread_id)
        self._validate_recover_close_request(spread=spread, request=request)
        short_exit_order = self._refresh_if_present(spread.short_exit_order_id)
        if short_exit_order is None:
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="missing_short_close_order",
                detail="Bull put close recovery requires an existing short close order.",
            )
        if self._is_working_order(short_exit_order):
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="working_replacement_exists",
                detail="Bull put close recovery is blocked because the existing short close order is still working.",
                order_ids=[short_exit_order.id],
            )
        if not self._is_failed_or_expired_close_order(spread=spread, order=short_exit_order):
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="short_close_order_not_failed",
                detail="Bull put close recovery requires the previous short close order to be canceled, rejected, or expired.",
                order_ids=[short_exit_order.id],
            )

        short_leg, long_leg = self._load_spread_leg_quotes(spread)
        if short_leg.ask is None:
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="missing_replacement_ask",
                detail=f"Could not recover close because {short_leg.symbol} has no ask price.",
                order_ids=[short_exit_order.id],
            )
        if request.max_debit is not None and short_leg.ask > request.max_debit:
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="max_debit_exceeded",
                detail=f"Replacement close ask {short_leg.ask} exceeds max_debit {request.max_debit}.",
                order_ids=[short_exit_order.id],
            )

        reason = request.note or "manual_recover_close"
        replacement_order = self.order_service.submit_order(
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
            short_exit_order_id=replacement_order.id,
            exit_reason=spread.exit_reason or "manual_recover_close",
            lifecycle_warning_code=None,
            manual_action_required=False,
            latest_close_order_status=replacement_order.status.value,
            updated_at=datetime.now(timezone.utc),
        )
        self._append_recover_close_audit_event(
            spread=spread,
            request=request,
            action="bull_put_recover_close_submitted",
            order_ids=[short_exit_order.id, replacement_order.id],
            before={
                "status": SpreadStatus.OPEN.value,
                "short_exit_order_id": short_exit_order.id,
                "short_exit_order_status": short_exit_order.status.value,
            },
            after={
                "status": spread.status.value,
                "short_exit_order_id": replacement_order.id,
                "limit_price": str(short_leg.ask),
            },
            summary="Manual bull put close recovery submitted a replacement buy-to-close order.",
        )

        replacement_order = self._await_terminal_or_fill(replacement_order)
        if not self._is_filled(replacement_order):
            final_order = self._cancel_if_working(replacement_order) or replacement_order
            lifecycle_payload = self._lifecycle_payload_for_close_order_state(
                spread=spread,
                status=SpreadStatus.OPEN,
                short_exit_order=final_order,
            )
            return self._update_spread(
                spread,
                status=SpreadStatus.OPEN,
                latest_close_order_status=final_order.status.value,
                lifecycle_warning_code=self._close_order_warning_code,
                manual_action_required=True,
                raw_payload=lifecycle_payload,
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        closed = self._close_long_leg(spread, reason=reason, leg=long_leg)
        self._append_recover_close_audit_event(
            spread=closed,
            request=request,
            action="bull_put_recover_close_completed",
            order_ids=[replacement_order.id, closed.long_exit_order_id] if closed.long_exit_order_id else [replacement_order.id],
            before={"status": spread.status.value},
            after={"status": closed.status.value},
            summary="Manual bull put close recovery filled the replacement short close order.",
        )
        return closed

    def _build_recover_close_eligibility(
        self,
        *,
        spread: BullPutSpread,
        external_account_id: str | None,
        mode: ExecutionMode,
        short_exit_order: Order | None,
    ) -> BullPutRecoverCloseEligibility:
        reasons: list[str] = []
        latest_should_close = self._latest_monitor_should_close(spread)
        old_short_close_order_status = (
            short_exit_order.status.value
            if short_exit_order is not None
            else spread.latest_close_order_status
        )
        working_replacement_order_id = (
            short_exit_order.id
            if self._is_working_order(short_exit_order)
            else None
        )

        if mode != ExecutionMode.PAPER:
            reasons.append("mode_not_paper")
        if spread.mode != ExecutionMode.PAPER:
            reasons.append("spread_not_paper")
        if external_account_id is not None and external_account_id != spread.external_account_id:
            reasons.append("account_mismatch")
        if spread.status != SpreadStatus.OPEN:
            reasons.append("spread_not_open")
        if not latest_should_close:
            reasons.append("close_not_required")
        if not spread.short_exit_order_id or short_exit_order is None:
            reasons.append("missing_short_close_order")
        elif working_replacement_order_id is not None:
            reasons.append("working_replacement_exists")
        elif not self._is_failed_or_expired_close_order(spread=spread, order=short_exit_order):
            reasons.append("short_close_order_not_failed")

        return BullPutRecoverCloseEligibility(
            spread_id=spread.id,
            eligible=not reasons,
            reasons=reasons,
            external_account_id=spread.external_account_id,
            mode=spread.mode,
            latest_should_close=latest_should_close,
            old_short_close_order_id=spread.short_exit_order_id,
            old_short_close_order_status=old_short_close_order_status,
            working_replacement_order_id=working_replacement_order_id,
            max_debit_required_hint=self._recover_close_max_debit_hint(spread),
        )

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
        monitor_updates = self._monitor_payload_updates(
            spread=spread,
            evaluated_at=evaluated_at,
            underlying_price=underlying_quote.last_done,
            estimated_exit_debit=estimated_exit_debit,
            estimated_pnl=estimated_pnl,
            days_to_expiration=days_to_expiration,
            exit_reason=exit_reason,
        )

        if exit_reason is None:
            spread = self._update_spread(
                spread,
                **monitor_updates,
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

        spread = self._update_spread(
            spread,
            **monitor_updates,
            last_synced_at=evaluated_at,
            updated_at=evaluated_at,
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

    def _build_readiness_result(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        evaluated_at: datetime,
        checks: list[BullPutStrategyReadinessCheck],
        previews: list[BullPutSpreadScanResult],
        preferred_symbol: str | None = None,
        next_action: str | None = None,
    ) -> BullPutStrategyReadinessResult:
        if any(check.blocking for check in checks):
            status = "blocked"
            ready = False
        elif preferred_symbol is not None:
            status = "ready"
            ready = True
        else:
            status = "watching"
            ready = False
        return BullPutStrategyReadinessResult(
            external_account_id=external_account_id,
            mode=mode,
            evaluated_at=evaluated_at,
            ready=ready,
            status=status,
            checks=checks,
            previews=previews,
            preferred_symbol=preferred_symbol,
            next_action=next_action,
        )

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
            state = self.runtime_states.upsert_runtime_state(state)
            return self._with_runtime_computed_fields(state, as_of=reference_time)

        if state.current_session_date != self._session_date(reference_time):
            state = self._update_runtime_state(
                state,
                current_session_date=self._session_date(reference_time),
                daily_entry_count=0,
                daily_realized_pnl=Decimal("0"),
                last_error=None,
            )
        return self._with_runtime_computed_fields(state, as_of=reference_time)

    def _update_runtime_state(
        self,
        state: BullPutStrategyRuntimeState,
        **updates,
    ) -> BullPutStrategyRuntimeState:
        payload = {"updated_at": datetime.now(timezone.utc), **updates}
        next_state = state.model_copy(update=payload)
        persisted = self.runtime_states.upsert_runtime_state(next_state)
        return self._with_runtime_computed_fields(persisted, as_of=payload["updated_at"])

    def _with_runtime_computed_fields(
        self,
        state: BullPutStrategyRuntimeState,
        *,
        as_of: datetime,
    ) -> BullPutStrategyRuntimeState:
        active_spreads = [
            spread
            for spread in self.spreads.list_spreads(external_account_id=state.external_account_id)
            if spread.status in ACTIVE_SPREAD_STATUSES
        ]
        open_spreads_count = compute_open_spread_count(active_spreads)
        daily_cap_reached = (
            state.daily_entry_count >= self.settings.bull_put_strategy.max_new_spreads_per_day
        )
        entry_block_reason = self._runtime_account_entry_block_reason(state=state)
        next_action = self._runtime_next_action(
            state=state,
            active_spreads=active_spreads,
            entry_block_reason=entry_block_reason,
        )
        return state.model_copy(
            update={
                "holding_open_position": bool(open_spreads_count),
                "daily_entry_cap_reached": daily_cap_reached,
                "entry_block_reason": entry_block_reason,
                "next_action": next_action,
                "active_spread_count": len(active_spreads),
                "open_spread_count": open_spreads_count,
                "next_monitor_after": self._next_monitor_after(active_spreads, as_of=as_of),
            }
        )

    def _runtime_next_action(
        self,
        *,
        state: BullPutStrategyRuntimeState,
        active_spreads: list[BullPutSpread],
        entry_block_reason: str | None,
    ) -> str:
        return compute_runtime_next_action(
            state=state,
            active_spread_count=len(active_spreads),
            max_new_spreads_per_day=self.settings.bull_put_strategy.max_new_spreads_per_day,
            entry_block_reason=entry_block_reason,
        )

    def _next_monitor_after(
        self,
        active_spreads: list[BullPutSpread],
        *,
        as_of: datetime,
    ) -> datetime | None:
        return compute_next_monitor_after(
            active_spreads=active_spreads,
            monitor_interval_seconds=self.settings.bull_put_strategy.monitor_interval_seconds,
            as_of=as_of,
        )

    def _runtime_entry_block_reason(
        self,
        *,
        state: BullPutStrategyRuntimeState,
        symbol: str,
    ) -> str | None:
        return compute_runtime_entry_block_reason(
            state=state,
            symbol=symbol,
            max_new_spreads_per_day=self.settings.bull_put_strategy.max_new_spreads_per_day,
            daily_realized_loss_limit=self.settings.bull_put_strategy.daily_realized_loss_limit,
        )

    def _runtime_account_entry_block_reason(
        self,
        *,
        state: BullPutStrategyRuntimeState,
    ) -> str | None:
        return compute_runtime_account_entry_block_reason(
            state=state,
            max_new_spreads_per_day=self.settings.bull_put_strategy.max_new_spreads_per_day,
            daily_realized_loss_limit=self.settings.bull_put_strategy.daily_realized_loss_limit,
        )

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
        if not self._is_us_options_trading_day(local_time.date()):
            return "Automatic bull put scans only run on U.S. options trading days."

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

    def _pre_open_capture_not_due_reason(self, as_of: datetime) -> str | None:
        local_time = as_of.astimezone(self.new_york)
        if not self._is_us_options_trading_day(local_time.date()):
            return "Automatic pre-open capture only runs on U.S. options trading days."
        if local_time.time() < PRE_OPEN_CAPTURE_START or local_time.time() > PRE_OPEN_CAPTURE_END:
            return "Automatic pre-open capture is outside the configured ET pre-open window."
        return None

    def _entry_session_gate_reason(self, as_of: datetime) -> str | None:
        local_time = as_of.astimezone(self.new_york)
        if not self._is_us_options_trading_day(local_time.date()):
            return "Bull put entries only execute during the regular U.S. options week."
        strategy = self.settings.bull_put_strategy
        session_minutes = (local_time.hour * 60) + local_time.minute
        start_minutes = (strategy.entry_session_start_hour_et * 60) + strategy.entry_session_start_minute_et
        end_minutes = (strategy.entry_session_end_hour_et * 60) + strategy.entry_session_end_minute_et
        if session_minutes < start_minutes or session_minutes >= end_minutes:
            return "Bull put entries only execute during regular U.S. options hours (09:30-16:00 ET)."
        confirmed_start = start_minutes + strategy.entry_open_confirmation_minutes
        if session_minutes < confirmed_start:
            return (
                "Bull put entries wait for the configured opening confirmation window "
                f"({strategy.entry_open_confirmation_minutes} minutes after the regular open)."
            )
        buffered_end = end_minutes - strategy.entry_close_buffer_minutes
        if session_minutes >= buffered_end:
            return (
                "Bull put entries stop before the close so both legs have time to fill "
                f"({strategy.entry_close_buffer_minutes} minute buffer)."
            )
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

    def _build_review_checkpoints(self, target_session_date: date) -> list[PreOpenReviewCheckpoint]:
        checkpoints: list[PreOpenReviewCheckpoint] = []
        for key, label, timing_label, checkpoint_time in PRE_OPEN_REVIEW_CHECKPOINTS:
            scheduled_local = datetime.combine(target_session_date, checkpoint_time, tzinfo=self.new_york)
            checkpoints.append(
                PreOpenReviewCheckpoint(
                    key=key,
                    label=label,
                    timing_label=timing_label,
                    scheduled_at=scheduled_local.astimezone(timezone.utc),
                )
            )
        return checkpoints

    def _latest_reviewable_pre_open_run(
        self,
        *,
        external_account_id: str,
        as_of: datetime,
    ) -> PreOpenAssessmentRun | None:
        target_date = self._session_date(as_of)
        for run in self.pre_open_runs.list_runs(external_account_id=external_account_id, limit=10):
            if run.target_session_date > target_date:
                continue
            if run.review_completed_at is None:
                return run
        return None

    def _latest_pre_open_run(
        self,
        *,
        external_account_id: str | None = None,
    ) -> PreOpenAssessmentRun | None:
        runs = self.pre_open_runs.list_runs(external_account_id=external_account_id, limit=1)
        return runs[0] if runs else None

    def _build_stale_pre_open_assessment(
        self,
        *,
        run: PreOpenAssessmentRun,
        error: LongbridgeIntegrationError,
    ) -> PreOpenDownsideAssessment:
        target_session = run.target_session_date.isoformat()
        analyzed_at = run.assessment.analyzed_at.astimezone(self.new_york).strftime("%Y-%m-%d %H:%M ET")
        return run.assessment.model_copy(
            update={
                "freshness_status": "stale",
                "freshness_detail": (
                    f"Showing the latest stored pre-open board for {target_session}. "
                    f"Last successful board {analyzed_at}."
                ),
                "stale_reason": str(error),
                "source_run_id": run.id,
            }
        )

    def _build_unavailable_pre_open_assessment(
        self,
        *,
        evaluated_at: datetime,
        error: LongbridgeIntegrationError,
    ) -> PreOpenDownsideAssessment:
        session = self._market_session_label(evaluated_at)
        target_session_date = self._target_session_date(evaluated_at, session=session)
        next_regular_open_at = self._next_regular_open_at(
            evaluated_at=evaluated_at,
            session=session,
            target_session_date=target_session_date,
        )
        return PreOpenDownsideAssessment(
            analyzed_at=evaluated_at,
            session=session,
            market_open=session == "regular",
            target_session_date=target_session_date,
            minutes_to_regular_open=self._minutes_to_regular_open(evaluated_at, session),
            next_regular_open_at=next_regular_open_at,
            downside_score=0,
            regime="unavailable",
            plain_put_view="unavailable",
            preferred_vehicle=None,
            trade_action="await_live_snapshot",
            trade_action_detail="Wait for the first successful broker snapshot before acting on the pre-open board.",
            gap_chase_risk="unknown",
            gap_chase_detail="Gap-chase risk cannot be evaluated until live proxy data becomes available.",
            summary="Live pre-open proxy data is unavailable right now.",
            reasons=[
                "No stored pre-open board is available yet, so the first successful Longbridge snapshot is still pending.",
            ],
            checkpoints=[],
            signals=[],
            put_snapshots=[],
            chain_analyses=[],
            freshness_status="error",
            freshness_detail="Live broker data is unavailable and no stored pre-open board is available yet.",
            stale_reason=str(error),
        )

    @staticmethod
    def _is_transient_longbridge_failure(error: Exception) -> bool:
        message = str(error).lower()
        transient_markers = (
            "timed out",
            "timeout",
            "skipping attempt",
            "connectivity failed",
            "client error (connect)",
            "connection refused",
            "connection reset",
            "connection aborted",
            "dns",
            "socket/token",
            "network",
        )
        return any(marker in message for marker in transient_markers)

    def _capture_pre_open_review_checkpoint(
        self,
        *,
        checkpoint: PreOpenReviewCheckpoint,
        evaluated_at: datetime,
    ) -> PreOpenReviewCheckpoint:
        signal_specs = [
            ("qqq", "Nasdaq 100 ETF", self.settings.bull_put_strategy.pre_open_proxy_qqq_symbol),
            ("spy", "S&P 500 ETF", self.settings.bull_put_strategy.pre_open_proxy_spy_symbol),
            ("semis", "Semiconductor Proxy", self.settings.bull_put_strategy.pre_open_proxy_semis_symbol),
        ]
        signal_by_key: dict[str, PreOpenProxySignal] = {}
        missing_signals: list[str] = []
        for key, label, symbol in signal_specs:
            try:
                signal_by_key[key] = self._regular_session_signal(
                    key=key,
                    label=label,
                    symbol=symbol,
                )
            except LongbridgeIntegrationError as exc:
                if not self._is_transient_longbridge_failure(exc):
                    raise
                missing_signals.append(label)
                logger.warning(
                    "Opening review proxy %s (%s) was unavailable; capturing a partial checkpoint when possible. %s",
                    label,
                    symbol,
                    exc,
                )

        qqq_signal = signal_by_key.get("qqq")
        spy_signal = signal_by_key.get("spy")
        semis_signal = signal_by_key.get("semis")
        qqq_vs_spy = self._quantize_optional_pct_difference(qqq_signal, spy_signal)
        semis_vs_qqq = self._quantize_optional_pct_difference(semis_signal, qqq_signal)
        confirmation, detail = self._review_checkpoint_confirmation(
            qqq_change=qqq_signal.change_pct if qqq_signal is not None else None,
            spy_change=spy_signal.change_pct if spy_signal is not None else None,
            semis_change=semis_signal.change_pct if semis_signal is not None else None,
            qqq_vs_spy=qqq_vs_spy,
            semis_vs_qqq=semis_vs_qqq,
            missing_signals=missing_signals,
        )
        return checkpoint.model_copy(
            update={
                "captured_at": evaluated_at,
                "status": "captured",
                "qqq_change_pct": qqq_signal.change_pct if qqq_signal is not None else None,
                "spy_change_pct": spy_signal.change_pct if spy_signal is not None else None,
                "semis_change_pct": semis_signal.change_pct if semis_signal is not None else None,
                "qqq_vs_spy_diff": qqq_vs_spy,
                "semis_vs_qqq_diff": semis_vs_qqq,
                "confirmation": confirmation,
                "detail": detail,
            }
        )

    def _regular_session_signal(
        self,
        *,
        key: str,
        label: str,
        symbol: str,
    ) -> PreOpenProxySignal:
        quote = self.longbridge_adapter.get_quote(symbol=symbol, mode=ExecutionMode.PAPER)
        return self._build_pre_open_signal(
            key=key,
            label=label,
            quote=quote,
            session="regular",
        )

    @staticmethod
    def _review_checkpoint_confirmation(
        *,
        qqq_change: Decimal | None,
        spy_change: Decimal | None,
        semis_change: Decimal | None,
        qqq_vs_spy: Decimal | None,
        semis_vs_qqq: Decimal | None,
        missing_signals: list[str] | None = None,
    ) -> tuple[str, str]:
        missing_signals = missing_signals or []
        missing_detail = ""
        if missing_signals:
            missing_detail = (
                " Live quotes were unavailable for "
                f"{', '.join(missing_signals)}, so this checkpoint is only partially confirmed."
            )

        if (
            qqq_change is not None
            and semis_change is not None
            and qqq_vs_spy is not None
            and qqq_change <= Decimal("-0.60")
            and semis_change <= Decimal("-0.90")
            and qqq_vs_spy <= Decimal("-0.25")
        ):
            return (
                "confirmed",
                (
                    "QQQ and semis are still underperforming the broad tape, "
                    "so the original downside read remains intact."
                ),
            )
        if qqq_change is not None and spy_change is not None and qqq_change < Decimal("0") and spy_change < Decimal("0"):
            return (
                "mixed",
                "Broad tape is still softer, but tech-specific downside confirmation is incomplete." + missing_detail,
            )
        if qqq_change is not None and qqq_change >= Decimal("0"):
            return (
                "failed",
                "QQQ did not stay under downside pressure after the open." + missing_detail,
            )
        if qqq_change is not None and semis_change is not None and qqq_change < Decimal("0") and semis_change >= Decimal("0"):
            return (
                "failed",
                "QQQ stayed softer, but semis did not confirm tech-specific downside pressure." + missing_detail,
            )
        if missing_signals:
            available_labels: list[str] = []
            if qqq_change is not None:
                available_labels.append("QQQ")
            if spy_change is not None:
                available_labels.append("SPY")
            if semis_change is not None:
                available_labels.append("semis")
            if available_labels:
                return (
                    "mixed",
                    (
                        "Opening follow-through is only partially available from "
                        f"{', '.join(available_labels)}." + missing_detail
                    ),
                )
            return (
                "mixed",
                "Opening follow-through could not be evaluated from live proxy quotes." + missing_detail,
            )
        return (
            "failed",
            "The opening tape did not keep enough downside pressure in QQQ and semis to validate the pre-open put bias.",
        )

    @staticmethod
    def _quantize_optional_pct_difference(
        left_signal: PreOpenProxySignal | None,
        right_signal: PreOpenProxySignal | None,
    ) -> Decimal | None:
        if left_signal is None or right_signal is None:
            return None
        return (left_signal.change_pct - right_signal.change_pct).quantize(Decimal("0.01"))

    def _summarize_pre_open_review(
        self,
        *,
        run: PreOpenAssessmentRun,
        checkpoints: list[PreOpenReviewCheckpoint],
        evaluated_at: datetime,
    ) -> tuple[str, str, datetime | None]:
        captured = [checkpoint for checkpoint in checkpoints if checkpoint.captured_at is not None]
        if not captured:
            return (
                run.review_status,
                run.review_summary or "Opening follow-through review is waiting for the first checkpoint.",
                None,
            )
        latest = captured[-1]
        if len(captured) < len(PRE_OPEN_REVIEW_CHECKPOINTS):
            summary = f"{latest.label} review is {latest.confirmation or 'mixed'}. {latest.detail or ''}".strip()
            return "in_progress", summary, None
        confirmed = sum(1 for checkpoint in captured if checkpoint.confirmation == "confirmed")
        failed = sum(1 for checkpoint in captured if checkpoint.confirmation == "failed")
        if confirmed >= 2:
            return (
                "confirmed",
                "Opening follow-through confirmed the bearish pre-open read across the key post-open checkpoints.",
                evaluated_at,
            )
        if failed >= 2:
            return (
                "failed",
                "Opening follow-through failed to confirm the bearish pre-open read by 10:00 ET.",
                evaluated_at,
            )
        return (
            "mixed",
            "Opening follow-through stayed mixed through 10:00 ET, so the pre-open directional edge was incomplete.",
            evaluated_at,
        )

    def _pre_open_assessment_journal_notes(self, assessment: PreOpenDownsideAssessment) -> str:
        open_label = (
            assessment.next_regular_open_at.astimezone(self.new_york).strftime("%Y-%m-%d %H:%M ET")
            if assessment.next_regular_open_at is not None
            else "regular session already open"
        )
        reasons = "; ".join(assessment.reasons[:3]) if assessment.reasons else "No major bearish trigger was active."
        return (
            f"Target session date: {assessment.target_session_date.isoformat()}. Next regular open: {open_label}. "
            f"Summary: {assessment.summary} Preferred vehicle: {assessment.preferred_vehicle or 'none'}. "
            f"Action: {assessment.trade_action}. Gap risk: {assessment.gap_chase_risk}. "
            f"Drivers: {reasons}"
        )

    def _mark_pre_open_run_flag(
        self,
        run: PreOpenAssessmentRun,
        key: str,
        timestamp: datetime | None = None,
    ) -> PreOpenAssessmentRun:
        marker = timestamp or datetime.now(timezone.utc)
        raw_payload = dict(run.raw_payload or {})
        journal_meta = dict(raw_payload.get("journal") or {})
        journal_meta[key] = marker.isoformat()
        raw_payload["journal"] = journal_meta
        updated = run.model_copy(update={"raw_payload": raw_payload, "updated_at": marker})
        return self.pre_open_runs.upsert_run(updated)

    @staticmethod
    def _pre_open_run_flag(run: PreOpenAssessmentRun, key: str) -> bool:
        raw_payload = run.raw_payload or {}
        journal_meta = raw_payload.get("journal") or {}
        return key in journal_meta

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

    @staticmethod
    def _json_decimal(value: Decimal | None) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _build_candidate_token(preview: BullPutSpreadScanResult) -> str | None:
        candidate = preview.candidate
        if candidate is None:
            return None
        parts = [
            preview.strategy_id,
            preview.external_account_id,
            preview.mode.value,
            candidate.underlying_symbol,
            candidate.expiration_date.isoformat(),
            candidate.short_put.symbol,
            candidate.long_put.symbol,
            BullPutStrategyService._decimal_token(candidate.width),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _decimal_token(value: Decimal) -> str:
        return format(value.normalize(), "f")

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
        return compute_session_date(as_of, market_timezone=self.new_york)

    def _is_us_options_trading_day(self, local_date: date) -> bool:
        return compute_is_us_options_trading_day(local_date)

    def _next_us_options_trading_day(self, start_date: date) -> date:
        return compute_next_us_options_trading_day(start_date)

    def _target_session_date(self, as_of: datetime, *, session: str | None = None) -> date:
        return compute_target_session_date(
            as_of,
            market_timezone=self.new_york,
            session=session,
        )

    def _market_session_label(self, as_of: datetime) -> str:
        return compute_market_session_label(as_of, market_timezone=self.new_york)

    def _next_regular_open_at(
        self,
        *,
        evaluated_at: datetime,
        session: str,
        target_session_date: date,
    ) -> datetime | None:
        return compute_next_regular_open_at(
            session=session,
            target_session_date=target_session_date,
            market_timezone=self.new_york,
        )

    def _minutes_to_regular_open(self, as_of: datetime, session: str) -> int | None:
        return compute_minutes_to_regular_open(
            as_of,
            session=session,
            market_timezone=self.new_york,
        )

    def _pre_open_trade_action(
        self,
        *,
        session: str,
        downside_score: int,
        preferred_vehicle: str | None,
        qqq_change: Decimal | None,
        spy_change: Decimal | None,
        semis_change: Decimal | None,
    ) -> tuple[str, str]:
        available_values = [value for value in (qqq_change, spy_change, semis_change) if value is not None]
        proxy_phrase = "the available market proxies"
        if qqq_change is not None and semis_change is not None:
            proxy_phrase = "QQQ and semis"
        elif qqq_change is not None:
            proxy_phrase = "QQQ and the broad tape"
        elif spy_change is not None:
            proxy_phrase = "the broad tape"
        if downside_score >= 5:
            if session == "premarket":
                if available_values and min(available_values) <= Decimal("-1.25"):
                    return (
                        "wait_for_failed_bounce",
                        "Bearish bias is real, but the gap is already stretched. Wait for the first bounce to fail instead of paying up for plain puts into the open.",
                    )
                return (
                    "wait_for_open_confirmation",
                    f"Bias is bearish. Only press {preferred_vehicle or 'index'} puts if {proxy_phrase} stay weak through the open.",
                )
            if session == "regular":
                return (
                    "use_intraday_confirmation",
                    f"Only add {preferred_vehicle or 'index'} puts if the opening bounce fails and the proxy weakness still lines up.",
                )
            return (
                "prepare_next_session",
                "Use the current read to prepare a watchlist, but wait for the next regular session before acting on plain puts.",
            )
        if downside_score >= 3:
            return (
                "selective_probe_only",
                "Downside risk is present, but broad confirmation is incomplete. Any plain-put idea should stay small and highly selective.",
            )
        return (
            "stand_down",
            "The proxy set is too mixed to justify paying premium for a plain downside put setup.",
        )

    def _pre_open_gap_risk(
        self,
        *,
        downside_score: int,
        qqq_change: Decimal | None,
        spy_change: Decimal | None,
        semis_change: Decimal | None,
    ) -> tuple[str, str]:
        gap_values = [value for value in (qqq_change, spy_change, semis_change) if value is not None]
        gap_extension = min(gap_values) if gap_values else Decimal("0")
        if gap_extension <= Decimal("-1.25") or (
            downside_score >= 5 and semis_change is not None and semis_change <= Decimal("-1.50")
        ):
            return (
                "high",
                "The tape is weak enough that a gap-down open could make plain puts expensive immediately. Favor patience over chasing the first downtick.",
            )
        if gap_extension <= Decimal("-0.75") or downside_score >= 5:
            return (
                "medium",
                "The bearish read is usable, but only if the first 5-15 minutes confirm that tech stays weaker than the broad market.",
            )
        return (
            "low",
            "Gap extension is limited. If the open confirms, plain puts are less likely to be immediately overpaid.",
        )

    def _build_pre_open_checkpoints(
        self,
        *,
        evaluated_at: datetime,
        session: str,
        trade_action: str,
        preferred_vehicle: str | None,
    ) -> list[PreOpenCheckpoint]:
        preferred_label = preferred_vehicle or "index"
        details = [
            (
                "Macro pulse",
                "08:30 ET",
                "Recheck futures, rates proxies, and any overnight macro shock before trusting the bearish read.",
                8 * 60 + 30,
            ),
            (
                "Tape confirmation",
                "09:15 ET",
                "Compare QQQ versus SPY and semis versus QQQ. If tech stops underperforming here, plain puts lose edge quickly.",
                9 * 60 + 15,
            ),
            (
                "Opening print",
                "09:30 ET",
                "Do not chase the first print. Watch whether the gap extends or immediately attracts buyers.",
                9 * 60 + 30,
            ),
            (
                "First 15 minutes",
                "09:45 ET",
                f"If the opening bounce fails and {preferred_label} remains the weak vehicle, the downside expression is cleaner.",
                9 * 60 + 45,
            ),
        ]
        local_time = evaluated_at.astimezone(self.new_york)
        current_minutes = (local_time.hour * 60) + local_time.minute
        checkpoints: list[PreOpenCheckpoint] = []
        active_assigned = False
        for label, timing_label, detail, threshold in details:
            status = "pending"
            if session == "weekend":
                status = "pending"
            elif current_minutes >= threshold:
                status = "complete"
            elif not active_assigned:
                status = "active"
                active_assigned = True
            checkpoints.append(
                PreOpenCheckpoint(
                    label=label,
                    timing_label=timing_label,
                    status=status,
                    detail=detail,
                )
            )
        if trade_action == "stand_down" and checkpoints:
            checkpoints[-1] = checkpoints[-1].model_copy(
                update={
                    "detail": "If proxy weakness does not broaden by 09:45 ET, stand down instead of forcing a directional put entry.",
                }
            )
        return checkpoints

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
        signals: list[PreOpenProxySignal],
    ) -> tuple[list[DirectionalPutSnapshot], list[str]]:
        snapshots: list[DirectionalPutSnapshot] = []
        missing_snapshots: list[str] = []
        for signal in signals:
            try:
                snapshot = self._nearest_directional_put_snapshot(
                    symbol=signal.symbol,
                    underlying_price=signal.session_price,
                    evaluated_at=evaluated_at,
                )
            except LongbridgeIntegrationError as exc:
                missing_snapshots.append(signal.symbol)
                logger.warning(
                    "Directional put snapshot for %s was unavailable; continuing without it. %s",
                    signal.symbol,
                    exc,
                )
                continue
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots, missing_snapshots

    def _build_option_chain_analyses(
        self,
        *,
        evaluated_at: datetime,
        signals: list[PreOpenProxySignal],
    ) -> tuple[list[OptionChainAnalysis], list[str]]:
        analyses: list[OptionChainAnalysis] = []
        missing_analyses: list[str] = []
        for signal in signals:
            try:
                analysis = self._option_chain_analysis(
                    symbol=signal.symbol,
                    underlying_price=signal.session_price,
                    evaluated_at=evaluated_at,
                )
            except LongbridgeIntegrationError as exc:
                missing_analyses.append(signal.symbol)
                logger.warning(
                    "Option-chain analysis for %s was unavailable; continuing without it. %s",
                    signal.symbol,
                    exc,
                )
                continue
            if analysis is not None:
                analyses.append(analysis)
        return analyses, missing_analyses

    def _option_chain_analysis(
        self,
        *,
        symbol: str,
        underlying_price: Decimal,
        evaluated_at: datetime,
    ) -> OptionChainAnalysis | None:
        expiry_dates = self.longbridge_adapter.list_option_expiry_dates(
            symbol=symbol,
            mode=ExecutionMode.PAPER,
        )
        expiries = self._select_option_chain_analysis_expirations(expiry_dates, evaluated_at)
        if not expiries:
            return None

        expiry_analyses = [
            analysis
            for expiry_date in expiries
            if (analysis := self._analyze_option_expiration(
                symbol=symbol,
                underlying_price=underlying_price,
                expiry_date=expiry_date,
                evaluated_at=evaluated_at,
            )) is not None
        ]
        if not expiry_analyses:
            return None

        front_expiration = expiry_analyses[0]
        next_expiration = expiry_analyses[1] if len(expiry_analyses) > 1 else None
        term_diff = None
        term_structure_label = None
        if (
            front_expiration.atm_implied_volatility is not None
            and next_expiration is not None
            and next_expiration.atm_implied_volatility is not None
        ):
            term_diff = (next_expiration.atm_implied_volatility - front_expiration.atm_implied_volatility).quantize(
                Decimal("0.0001")
            )
            term_structure_label = self._option_term_structure_label(term_diff)

        return OptionChainAnalysis(
            underlying_symbol=symbol,
            underlying_price=underlying_price,
            analyzed_at=evaluated_at,
            front_expiration=front_expiration,
            next_expiration=next_expiration,
            atm_iv_term_diff=term_diff,
            term_structure_label=term_structure_label,
            sample_note="Liquidity buckets use ATM/skew anchors plus the deepest open-interest puts for each expiry.",
        )

    def _analyze_option_expiration(
        self,
        *,
        symbol: str,
        underlying_price: Decimal,
        expiry_date: date,
        evaluated_at: datetime,
    ) -> OptionChainExpiryAnalysis | None:
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

        atm_quote = min(
            put_quotes,
            key=lambda quote: (abs(quote.strike - underlying_price), quote.strike),
        )
        skew_quote = self._select_skew_put_quote(put_quotes, underlying_price)
        sampled_quotes = self._sample_option_liquidity_quotes(
            quotes=put_quotes,
            anchor_quotes=[atm_quote, skew_quote] if skew_quote is not None else [atm_quote],
            underlying_price=underlying_price,
        )
        enriched_quotes = [
            self._with_top_of_book(quote, mode=ExecutionMode.PAPER)
            for quote in sampled_quotes
        ]
        enriched_by_symbol = {quote.symbol: quote for quote in enriched_quotes}
        atm_quote = enriched_by_symbol.get(atm_quote.symbol, atm_quote)
        if skew_quote is not None:
            skew_quote = enriched_by_symbol.get(skew_quote.symbol, skew_quote)

        spread_pcts = [
            spread_pct
            for quote in enriched_quotes
            if (spread_pct := self._quote_spread_pct(quote)) is not None
        ]
        tight_count = sum(1 for spread_pct in spread_pcts if self._option_liquidity_label(spread_pct) == "tight")
        workable_count = sum(1 for spread_pct in spread_pcts if self._option_liquidity_label(spread_pct) == "workable")
        wide_count = sum(1 for spread_pct in spread_pcts if self._option_liquidity_label(spread_pct) == "wide")
        liquid_strikes = [
            self._build_option_chain_liquid_strike(quote)
            for quote in sorted(
                enriched_quotes,
                key=lambda quote: (
                    -(quote.open_interest or 0),
                    -(quote.volume or 0),
                    abs(quote.strike - underlying_price),
                ),
            )[:3]
        ]

        return OptionChainExpiryAnalysis(
            expiration_date=expiry_date,
            days_to_expiration=self._days_to_expiration(expiry_date, evaluated_at),
            atm_strike=atm_quote.strike,
            atm_put_symbol=atm_quote.symbol,
            atm_implied_volatility=atm_quote.implied_volatility,
            atm_delta=atm_quote.delta,
            atm_mid_price=self._quote_mid_price(atm_quote),
            put_skew_strike=skew_quote.strike if skew_quote is not None else None,
            put_skew_put_symbol=skew_quote.symbol if skew_quote is not None else None,
            put_skew_implied_volatility=skew_quote.implied_volatility if skew_quote is not None else None,
            put_skew_delta=skew_quote.delta if skew_quote is not None else None,
            put_skew_diff=self._quote_iv_diff(skew_quote, atm_quote),
            median_spread_pct=self._median_decimal(spread_pcts),
            tight_count=tight_count,
            workable_count=workable_count,
            wide_count=wide_count,
            liquid_strikes=liquid_strikes,
        )

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
        mid_price = None
        spread_width = None
        spread_pct = None
        if selected.bid is not None and selected.ask is not None:
            spread_width = self._quantize_price(selected.ask - selected.bid)
            mid_price = self._quantize_price((selected.ask + selected.bid) / Decimal("2"))
            if mid_price > Decimal("0"):
                spread_pct = ((selected.ask - selected.bid) / mid_price * Decimal("100")).quantize(Decimal("0.01"))
        elif selected.bid is not None or selected.ask is not None:
            mid_price = self._quantize_price(selected.bid or selected.ask or Decimal("0"))
        distance_from_spot_pct = None
        if underlying_price > Decimal("0"):
            distance_from_spot_pct = (
                ((underlying_price - selected.strike) / underlying_price) * Decimal("100")
            ).quantize(Decimal("0.01"))
        return DirectionalPutSnapshot(
            underlying_symbol=symbol,
            expiration_date=selected.expiration_date,
            days_to_expiration=self._days_to_expiration(selected.expiration_date, evaluated_at),
            strike=selected.strike,
            put_symbol=selected.symbol,
            bid=selected.bid,
            ask=selected.ask,
            mid_price=mid_price,
            spread_width=spread_width,
            spread_pct=spread_pct,
            distance_from_spot_pct=distance_from_spot_pct,
            delta=selected.delta,
            implied_volatility=selected.implied_volatility,
            liquidity_label=self._option_liquidity_label(spread_pct),
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

    def _select_option_chain_analysis_expirations(
        self,
        expiry_dates: list[date],
        evaluated_at: datetime,
    ) -> list[date]:
        strategy = self.settings.bull_put_strategy
        evaluated_date = evaluated_at.astimezone(self.new_york).date()
        candidates = [
            expiry_date
            for expiry_date in expiry_dates
            if (expiry_date - evaluated_date).days >= strategy.pre_open_put_min_dte
        ]
        return sorted(candidates)[:2]

    @staticmethod
    def _option_liquidity_label(spread_pct: Decimal | None) -> str | None:
        if spread_pct is None:
            return None
        if spread_pct <= Decimal("4"):
            return "tight"
        if spread_pct <= Decimal("9"):
            return "workable"
        return "wide"

    @staticmethod
    def _option_term_structure_label(term_diff: Decimal | None) -> str | None:
        if term_diff is None:
            return None
        if term_diff >= Decimal("0.0200"):
            return "next_richer"
        if term_diff <= Decimal("-0.0200"):
            return "front_loaded"
        return "flat"

    @staticmethod
    def _select_skew_put_quote(
        quotes: list[OptionMarketSnapshot],
        underlying_price: Decimal,
    ) -> OptionMarketSnapshot | None:
        delta_quotes = [quote for quote in quotes if quote.delta is not None]
        if not delta_quotes:
            return None
        return min(
            delta_quotes,
            key=lambda quote: (
                abs(abs(quote.delta or Decimal("0")) - Decimal("0.25")),
                abs(quote.strike - underlying_price),
            ),
        )

    @staticmethod
    def _sample_option_liquidity_quotes(
        *,
        quotes: list[OptionMarketSnapshot],
        anchor_quotes: list[OptionMarketSnapshot],
        underlying_price: Decimal,
    ) -> list[OptionMarketSnapshot]:
        ranked_quotes = sorted(
            quotes,
            key=lambda quote: (
                -(quote.open_interest or 0),
                -(quote.volume or 0),
                abs(quote.strike - underlying_price),
            ),
        )
        sampled: list[OptionMarketSnapshot] = []
        seen_symbols: set[str] = set()
        for quote in [*anchor_quotes, *ranked_quotes]:
            if quote.symbol in seen_symbols:
                continue
            sampled.append(quote)
            seen_symbols.add(quote.symbol)
            if len(sampled) >= 6:
                break
        return sampled

    def _build_option_chain_liquid_strike(
        self,
        quote: OptionMarketSnapshot,
    ) -> OptionChainLiquidStrike:
        spread_width = self._quote_spread_width(quote)
        spread_pct = self._quote_spread_pct(quote)
        return OptionChainLiquidStrike(
            strike=quote.strike,
            put_symbol=quote.symbol,
            open_interest=quote.open_interest,
            volume=quote.volume,
            delta=quote.delta,
            bid=quote.bid,
            ask=quote.ask,
            mid_price=self._quote_mid_price(quote),
            spread_width=spread_width,
            spread_pct=spread_pct,
            liquidity_label=self._option_liquidity_label(spread_pct),
        )

    @staticmethod
    def _quote_mid_price(quote: OptionMarketSnapshot) -> Decimal | None:
        if quote.bid is not None and quote.ask is not None:
            return ((quote.bid + quote.ask) / Decimal("2")).quantize(Decimal("0.01"))
        if quote.bid is not None:
            return quote.bid.quantize(Decimal("0.01"))
        if quote.ask is not None:
            return quote.ask.quantize(Decimal("0.01"))
        return None

    @staticmethod
    def _quote_spread_width(quote: OptionMarketSnapshot) -> Decimal | None:
        if quote.bid is None or quote.ask is None:
            return None
        if quote.ask <= quote.bid:
            return None
        return (quote.ask - quote.bid).quantize(Decimal("0.01"))

    def _quote_spread_pct(self, quote: OptionMarketSnapshot) -> Decimal | None:
        spread_width = self._quote_spread_width(quote)
        mid_price = self._quote_mid_price(quote)
        if spread_width is None or mid_price is None or mid_price <= Decimal("0"):
            return None
        return ((spread_width / mid_price) * Decimal("100")).quantize(Decimal("0.01"))

    @staticmethod
    def _quote_iv_diff(
        left: OptionMarketSnapshot | None,
        right: OptionMarketSnapshot | None,
    ) -> Decimal | None:
        if left is None or right is None:
            return None
        if left.implied_volatility is None or right.implied_volatility is None:
            return None
        return (left.implied_volatility - right.implied_volatility).quantize(Decimal("0.0001"))

    @staticmethod
    def _median_decimal(values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[middle].quantize(Decimal("0.01"))
        return ((ordered[middle - 1] + ordered[middle]) / Decimal("2")).quantize(Decimal("0.01"))

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

    def _validate_recover_close_request(
        self,
        *,
        spread: BullPutSpread,
        request: RecoverBullPutCloseRequest,
    ) -> None:
        if request.mode != ExecutionMode.PAPER:
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="live_recovery_blocked",
                detail="Bull put close recovery is paper-only.",
            )
        if spread.mode != ExecutionMode.PAPER:
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="spread_not_paper",
                detail="Bull put close recovery is only available for paper spreads.",
            )
        if not request.confirm_paper_order:
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="paper_order_not_confirmed",
                detail="Set confirm_paper_order=true before submitting a paper recovery order.",
            )
        if request.external_account_id != spread.external_account_id:
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="account_mismatch",
                detail=(
                    f"Request account '{request.external_account_id}' does not match spread account "
                    f"'{spread.external_account_id}'."
                ),
            )
        if spread.status != SpreadStatus.OPEN:
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="spread_not_open",
                detail="Bull put close recovery only applies to an open spread waiting for close recovery.",
            )
        if not self._latest_monitor_should_close(spread):
            self._reject_recover_close(
                spread=spread,
                request=request,
                warning_code="close_not_required",
                detail="Bull put close recovery is blocked because the latest monitor does not require close.",
            )

    def _reject_recover_close(
        self,
        *,
        spread: BullPutSpread,
        request: RecoverBullPutCloseRequest,
        warning_code: str,
        detail: str,
        order_ids: list[str] | None = None,
    ) -> None:
        self._append_recover_close_audit_event(
            spread=spread,
            request=request,
            action="bull_put_recover_close_rejected",
            order_ids=order_ids or ([spread.short_exit_order_id] if spread.short_exit_order_id else []),
            before={
                "status": spread.status.value,
                "short_exit_order_id": spread.short_exit_order_id,
                "latest_monitor_should_close": spread.latest_monitor_should_close,
                "latest_close_order_status": spread.latest_close_order_status,
            },
            after=None,
            warning_code=warning_code,
            summary=detail,
        )
        raise ValueError(detail)

    def _append_recover_close_audit_event(
        self,
        *,
        spread: BullPutSpread,
        request: RecoverBullPutCloseRequest,
        action: str,
        order_ids: list[str],
        before: dict | None,
        after: dict | None,
        summary: str,
        warning_code: str | None = None,
    ) -> None:
        if self.audit_events is None:
            return
        try:
            self.audit_events.create_event(
                CreateStrategyAuditEventRequest(
                    external_account_id=spread.external_account_id,
                    mode=spread.mode,
                    actor=request.actor,
                    source="manual_recovery",
                    strategy=spread.strategy_id,
                    action=action,
                    before=before,
                    after=after,
                    order_ids=[order_id for order_id in order_ids if order_id],
                    warning_code=warning_code,
                    summary=summary,
                    detail=request.note,
                    payload={
                        "spread_id": spread.id,
                        "underlying_symbol": spread.underlying_symbol,
                        "confirm_paper_order": request.confirm_paper_order,
                        "max_debit": str(request.max_debit) if request.max_debit is not None else None,
                    },
                )
            )
        except Exception:
            logger.exception("Failed to append bull put recover-close audit event '%s'.", action)

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
        if "raw_payload" in updates:
            updates.update(bull_put_lifecycle_summary(updates["raw_payload"]))
        next_spread = spread.model_copy(update=updates)
        return self.spreads.update_spread(next_spread)

    def _lifecycle_payload_for_close_order_state(
        self,
        *,
        spread: BullPutSpread,
        status: SpreadStatus,
        short_exit_order: Order | None,
    ) -> dict | None:
        warning = bull_put_close_order_warning(
            spread_status=status,
            short_exit_order_id=spread.short_exit_order_id,
            short_exit_order_status=short_exit_order.status if short_exit_order is not None else None,
            short_symbol=spread.short_symbol,
            raw_payload=spread.raw_payload,
            exit_reason=spread.exit_reason,
        )
        return bull_put_close_order_lifecycle_payload(
            raw_payload=spread.raw_payload,
            warning=warning,
        )

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

    def _monitor_payload_updates(
        self,
        *,
        spread: BullPutSpread,
        evaluated_at: datetime,
        underlying_price: Decimal,
        estimated_exit_debit: Decimal | None,
        estimated_pnl: Decimal | None,
        days_to_expiration: int,
        exit_reason: str | None,
    ) -> dict:
        raw_payload = dict(spread.raw_payload or {})
        take_profit_debit = None
        stop_loss_debit = None
        distance_to_take_profit = None
        distance_to_stop_loss = None
        if spread.entry_net_credit is not None:
            strategy = self.settings.bull_put_strategy
            take_profit_debit = spread.entry_net_credit * strategy.take_profit_exit_ratio
            stop_loss_debit = spread.entry_net_credit * strategy.stop_loss_exit_multiple
            if estimated_exit_debit is not None:
                distance_to_take_profit = estimated_exit_debit - take_profit_debit
                distance_to_stop_loss = stop_loss_debit - estimated_exit_debit

        raw_payload["monitor"] = {
            "evaluated_at": evaluated_at.isoformat(),
            "next_monitor_after": (
                evaluated_at + timedelta(seconds=self.settings.bull_put_strategy.monitor_interval_seconds)
            ).isoformat(),
            "underlying_price": self._json_decimal(underlying_price),
            "estimated_exit_debit": self._json_decimal(estimated_exit_debit),
            "estimated_pnl": self._json_decimal(estimated_pnl),
            "days_to_expiration": days_to_expiration,
            "exit_reason": exit_reason,
            "should_close": exit_reason is not None,
            "take_profit_debit": self._json_decimal(take_profit_debit),
            "stop_loss_debit": self._json_decimal(stop_loss_debit),
            "distance_to_take_profit_debit": self._json_decimal(distance_to_take_profit),
            "distance_to_stop_loss_debit": self._json_decimal(distance_to_stop_loss),
            "short_strike_distance": self._json_decimal(underlying_price - spread.short_strike),
        }
        return {"raw_payload": raw_payload}

    def _determine_exit_reason(
        self,
        *,
        spread: BullPutSpread,
        underlying_price: Decimal,
        estimated_exit_debit: Decimal | None,
        days_to_expiration: int,
    ) -> str | None:
        strategy = self.settings.bull_put_strategy
        return compute_exit_reason(
            spread=spread,
            underlying_price=underlying_price,
            estimated_exit_debit=estimated_exit_debit,
            days_to_expiration=days_to_expiration,
            close_days_to_expiration=strategy.close_days_to_expiration,
            stop_loss_exit_multiple=strategy.stop_loss_exit_multiple,
            take_profit_exit_ratio=strategy.take_profit_exit_ratio,
        )

    @staticmethod
    def _estimated_exit_debit(
        *,
        short_leg: OptionMarketSnapshot,
        long_leg: OptionMarketSnapshot,
    ) -> Decimal | None:
        return compute_estimated_exit_debit(short_leg=short_leg, long_leg=long_leg)

    @staticmethod
    def _estimated_pnl(
        *,
        spread: BullPutSpread,
        estimated_exit_debit: Decimal | None,
    ) -> Decimal | None:
        return compute_estimated_pnl(spread=spread, estimated_exit_debit=estimated_exit_debit)

    def _actual_entry_risk_updates(
        self,
        *,
        spread: BullPutSpread,
        entry_net_credit: Decimal | None,
    ) -> dict:
        if entry_net_credit is None:
            return {}

        contract_multiplier = Decimal("100")
        max_profit = entry_net_credit * Decimal(spread.contracts) * contract_multiplier
        max_loss = (
            max(Decimal("0"), spread.width - entry_net_credit)
            * Decimal(spread.contracts)
            * contract_multiplier
        )
        break_even = spread.short_strike - entry_net_credit
        account_risk_pct = spread.account_risk_pct
        try:
            account = self._get_latest_account_snapshot(spread.external_account_id)
        except LookupError:
            account = None
        if account is not None and account.net_liquidation > 0:
            account_risk_pct = max_loss / account.net_liquidation
        return {
            "max_profit": max_profit,
            "max_loss": max_loss,
            "break_even": break_even,
            "account_risk_pct": account_risk_pct,
        }

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
    def _is_working_order(order: Order | None) -> bool:
        return order is not None and order.status in {
            OrderStatus.CREATED,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIALLY_FILLED,
        }

    @staticmethod
    def _is_terminal(order: Order | None) -> bool:
        return order is not None and order.status in {
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
        }

    @staticmethod
    def _is_failed_or_expired_close_order(*, spread: BullPutSpread, order: Order | None) -> bool:
        if order is not None and order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
            return True
        status_text = str(spread.latest_close_order_status or "").strip().lower()
        return status_text in {"canceled", "cancelled", "rejected", "expired"}

    @staticmethod
    def _latest_monitor_should_close(spread: BullPutSpread) -> bool:
        if spread.latest_monitor_should_close is not None:
            return bool(spread.latest_monitor_should_close)
        raw_payload = spread.raw_payload if isinstance(spread.raw_payload, dict) else {}
        monitor = raw_payload.get("monitor") if isinstance(raw_payload.get("monitor"), dict) else {}
        value = monitor.get("should_close")
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"

    @staticmethod
    def _recover_close_max_debit_hint(spread: BullPutSpread) -> Decimal | None:
        raw_payload = spread.raw_payload if isinstance(spread.raw_payload, dict) else {}
        monitor = raw_payload.get("monitor") if isinstance(raw_payload.get("monitor"), dict) else {}
        value = monitor.get("estimated_exit_debit")
        if value in {None, ""}:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    def _select_expiration_date(
        self,
        expiry_dates: list[date],
        scanned_at: datetime,
    ) -> date | None:
        strategy = self.settings.bull_put_strategy
        return compute_select_expiration_date(
            expiry_dates=expiry_dates,
            scanned_at=scanned_at,
            min_dte=strategy.min_dte,
            max_dte=strategy.max_dte,
            market_timezone=self.new_york,
        )

    def _days_to_expiration(self, expiry_date: date, scanned_at: datetime) -> int:
        return compute_days_to_expiration(
            expiry_date=expiry_date,
            scanned_at=scanned_at,
            market_timezone=self.new_york,
        )

    def _is_short_put_candidate(self, quote: OptionMarketSnapshot) -> bool:
        strategy = self.settings.bull_put_strategy
        return compute_is_short_put_candidate(
            quote,
            min_open_interest=strategy.min_open_interest,
            short_delta_min=strategy.short_delta_min,
            short_delta_max=strategy.short_delta_max,
        )

    def _with_top_of_book(
        self,
        quote: OptionMarketSnapshot,
        *,
        mode: ExecutionMode,
    ) -> OptionMarketSnapshot:
        if quote.bid is not None and quote.ask is not None:
            return quote
        bid, ask = self.longbridge_adapter.get_best_bid_ask(symbol=quote.symbol, mode=mode)
        return quote.model_copy(update={"bid": bid, "ask": ask})

    def _passes_top_of_book_filters(self, quote: OptionMarketSnapshot) -> bool:
        strategy = self.settings.bull_put_strategy
        return compute_passes_top_of_book_filters(
            quote,
            max_bid_ask_spread_pct=strategy.max_bid_ask_spread_pct,
        )

    def _option_leg_liquidity_reasons(
        self,
        *,
        short_leg: OptionMarketSnapshot,
        long_leg: OptionMarketSnapshot | None,
        scanned_at: datetime,
    ) -> list[str]:
        strategy = self.settings.bull_put_strategy
        return compute_option_leg_liquidity_reasons(
            short_leg=short_leg,
            long_leg=long_leg,
            scanned_at=scanned_at,
            max_bid_ask_spread_pct=strategy.max_bid_ask_spread_pct,
            min_short_leg_volume=strategy.min_short_leg_volume,
            min_long_leg_volume=strategy.min_long_leg_volume,
            max_option_quote_age_seconds=strategy.max_option_quote_age_seconds,
        )

    def _is_option_quote_fresh(
        self,
        quote: OptionMarketSnapshot,
        *,
        scanned_at: datetime,
    ) -> bool:
        return compute_is_option_quote_fresh(
            quote,
            scanned_at=scanned_at,
            max_option_quote_age_seconds=self.settings.bull_put_strategy.max_option_quote_age_seconds,
        )

    @staticmethod
    def _has_tradeable_long_leg(quote: OptionMarketSnapshot) -> bool:
        return compute_has_tradeable_long_leg(quote)

    def _entry_long_limit_price(
        self,
        *,
        long_leg: OptionMarketSnapshot,
        short_leg: OptionMarketSnapshot,
        width: Decimal,
    ) -> Decimal | None:
        strategy = self.settings.bull_put_strategy
        return compute_entry_long_limit_price(
            long_leg=long_leg,
            short_leg=short_leg,
            width=width,
            entry_long_limit_buffer=strategy.entry_long_limit_buffer,
            min_conservative_credit_per_width_ratio=strategy.min_conservative_credit_per_width_ratio,
        )

    def _entry_long_price_ladder(
        self,
        *,
        ask_price: Decimal | None,
        capped_price: Decimal | None,
    ) -> list[Decimal | None]:
        strategy = self.settings.bull_put_strategy
        return compute_entry_long_price_ladder(
            ask_price=ask_price,
            capped_price=capped_price,
            entry_reprice_increment=strategy.entry_reprice_increment,
            entry_reprice_max_steps=strategy.entry_reprice_max_steps,
        )

    def _entry_short_price_ladder(
        self,
        *,
        bid_price: Decimal | None,
        filled_long_price: Decimal | None,
        width: Decimal,
    ) -> list[Decimal | None]:
        strategy = self.settings.bull_put_strategy
        return compute_entry_short_price_ladder(
            bid_price=bid_price,
            filled_long_price=filled_long_price,
            width=width,
            entry_reprice_increment=strategy.entry_reprice_increment,
            entry_reprice_max_steps=strategy.entry_reprice_max_steps,
            min_conservative_credit_per_width_ratio=strategy.min_conservative_credit_per_width_ratio,
        )

    def _price_ladder(
        self,
        *,
        start: Decimal,
        end: Decimal,
        ascending: bool,
    ) -> list[Decimal]:
        strategy = self.settings.bull_put_strategy
        return compute_price_ladder(
            start=start,
            end=end,
            ascending=ascending,
            entry_reprice_increment=strategy.entry_reprice_increment,
            entry_reprice_max_steps=strategy.entry_reprice_max_steps,
        )

    @staticmethod
    def _quantize_price(value: Decimal) -> Decimal:
        return compute_quantize_price(value)

    @staticmethod
    def _mid_price(quote: OptionMarketSnapshot) -> Decimal | None:
        return compute_mid_price(quote)
