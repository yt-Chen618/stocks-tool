from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.application.services.orders import OrderService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    StrategyRunStatus,
    StrategySignalType,
    TimeInForce,
)
from stocks_tool.domain.models import (
    CreateOrderRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    ExecuteZeroDteLotteryRequest,
    OptionChainEntry,
    OptionContractRef,
    OptionMarketSnapshot,
    Order,
    SecurityQuoteSnapshot,
    UpdateZeroDteLotteryRuntimeRequest,
    ZeroDteLotteryCandidate,
    ZeroDteLotteryExecutionResult,
    ZeroDteLotteryPreviewResult,
    ZeroDteLotteryRuntimeState,
    ZeroDteLotteryScanResult,
)
from stocks_tool.ports.repository import BrokerAccountRepository, StrategyExperimentRepository
from stocks_tool.ports.broker_gateway import BrokerMarketDataGateway


class ZeroDteLotteryStrategyService:
    strategy_id = "zero_dte_lottery_v1"

    def __init__(
        self,
        *,
        settings: Settings,
        broker_accounts: BrokerAccountRepository,
        longbridge_adapter: BrokerMarketDataGateway,
        order_service: OrderService | None = None,
        experiments: StrategyExperimentRepository | None = None,
    ) -> None:
        self.settings = settings
        self.broker_accounts = broker_accounts
        self.longbridge_adapter = longbridge_adapter
        self.order_service = order_service
        self.experiments = experiments
        self.new_york = ZoneInfo("America/New_York")

    def get_runtime_state(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> ZeroDteLotteryRuntimeState:
        if mode != ExecutionMode.PAPER:
            raise ValueError("Zero-DTE lottery automation is paper-only in the current implementation.")
        self._ensure_account(external_account_id)
        return self._runtime_state(external_account_id=external_account_id, mode=mode)

    def update_runtime_state(
        self,
        *,
        external_account_id: str,
        request: UpdateZeroDteLotteryRuntimeRequest,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> ZeroDteLotteryRuntimeState:
        if mode != ExecutionMode.PAPER:
            raise ValueError("Zero-DTE lottery automation is paper-only in the current implementation.")
        self._ensure_account(external_account_id)
        if request.auto_execute_enabled is not None:
            self.settings.zero_dte_lottery_strategy.auto_execute_enabled = request.auto_execute_enabled
        return self._runtime_state(external_account_id=external_account_id, mode=mode)

    def preview(
        self,
        *,
        external_account_id: str,
        symbol: str | None = None,
        direction: str = "auto",
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
    ) -> ZeroDteLotteryPreviewResult:
        evaluated_at = self._reference_time(as_of)
        strategy = self.settings.zero_dte_lottery_strategy
        normalized_symbol = self._normalize_symbol(symbol) if symbol else strategy.symbols[0]
        base_result = {
            "external_account_id": external_account_id,
            "mode": mode,
            "evaluated_at": evaluated_at,
            "symbol": normalized_symbol,
            "max_premium_per_trade": strategy.max_premium_per_trade,
        }

        if mode != ExecutionMode.PAPER:
            return ZeroDteLotteryPreviewResult(
                **base_result,
                eligible=False,
                reasons=["Zero-DTE lottery preview is paper-only in the current implementation."],
            )
        if not strategy.enabled:
            return ZeroDteLotteryPreviewResult(
                **base_result,
                eligible=False,
                reasons=["Zero-DTE lottery strategy is disabled by configuration."],
            )
        if normalized_symbol not in {item.upper() for item in strategy.symbols}:
            return ZeroDteLotteryPreviewResult(
                **base_result,
                eligible=False,
                reasons=[f"{normalized_symbol} is not configured for zero-DTE lottery previews."],
            )
        self._ensure_account(external_account_id)

        underlying_quote = self.longbridge_adapter.get_quote(symbol=normalized_symbol, mode=mode)
        underlying_change_pct = self._change_pct(underlying_quote)
        selected_direction = self._resolve_direction(
            requested=direction,
            underlying_change_pct=underlying_change_pct,
        )
        if selected_direction is None:
            return ZeroDteLotteryPreviewResult(
                **base_result,
                eligible=False,
                underlying_price=underlying_quote.last_done,
                underlying_change_pct=underlying_change_pct,
                reasons=[
                    "Zero-DTE lottery auto direction is unclear; underlying change is inside the configured threshold."
                ],
            )

        expiry_date = self._select_today_expiration(
            self.longbridge_adapter.list_option_expiry_dates(symbol=normalized_symbol, mode=mode),
            evaluated_at=evaluated_at,
        )
        if expiry_date is None:
            return ZeroDteLotteryPreviewResult(
                **base_result,
                eligible=False,
                direction=selected_direction,
                underlying_price=underlying_quote.last_done,
                underlying_change_pct=underlying_change_pct,
                reasons=["No same-day option expiration is available for the selected symbol."],
            )

        chain = self.longbridge_adapter.list_option_chain(
            symbol=normalized_symbol,
            expiry_date=expiry_date,
            mode=mode,
        )
        symbols = self._option_symbols_for_snapshot(
            chain=chain,
            direction=selected_direction,
            underlying_price=underlying_quote.last_done,
        )
        if not symbols:
            return ZeroDteLotteryPreviewResult(
                **base_result,
                eligible=False,
                direction=selected_direction,
                selected_expiration_date=expiry_date,
                days_to_expiration=0,
                underlying_price=underlying_quote.last_done,
                underlying_change_pct=underlying_change_pct,
                reasons=["The same-day option chain did not include standard contracts for the selected direction."],
            )

        quotes = self.longbridge_adapter.get_option_market_snapshots(symbols=symbols, mode=mode)
        candidate = self._select_candidate_quote(
            quotes=quotes,
            direction=selected_direction,
            underlying_quote=underlying_quote,
            evaluated_at=evaluated_at,
            mode=mode,
        )
        if candidate is None:
            return ZeroDteLotteryPreviewResult(
                **base_result,
                eligible=False,
                direction=selected_direction,
                selected_expiration_date=expiry_date,
                days_to_expiration=0,
                underlying_price=underlying_quote.last_done,
                underlying_change_pct=underlying_change_pct,
                reasons=[
                    "No same-day option candidate passed delta, liquidity, freshness, volume/OI, and $150 premium filters."
                ],
            )

        return ZeroDteLotteryPreviewResult(
            **base_result,
            eligible=True,
            direction=selected_direction,
            selected_expiration_date=expiry_date,
            days_to_expiration=0,
            underlying_price=underlying_quote.last_done,
            underlying_change_pct=underlying_change_pct,
            candidate=candidate,
        )

    def execute(self, request: ExecuteZeroDteLotteryRequest) -> ZeroDteLotteryExecutionResult:
        if request.mode != ExecutionMode.PAPER:
            raise ValueError("Zero-DTE lottery execution is paper-only in the current implementation.")
        if not request.confirm_paper_order:
            raise ValueError("Zero-DTE lottery execution requires confirm_paper_order=true.")
        if self.order_service is None:
            raise ValueError("Zero-DTE lottery execution requires an order service.")
        preview = self.preview(
            external_account_id=request.external_account_id,
            symbol=request.symbol,
            direction=request.direction,
            mode=request.mode,
            as_of=request.as_of,
        )
        if not preview.eligible or preview.candidate is None:
            reason = preview.reasons[0] if preview.reasons else "Zero-DTE lottery preview did not produce a candidate."
            raise ValueError(reason)

        self._assert_daily_trade_capacity(
            external_account_id=request.external_account_id,
            mode=request.mode,
            evaluated_at=preview.evaluated_at,
        )
        candidate = preview.candidate
        limit_price = request.limit_price or candidate.option_ask
        premium_at_limit = (
            limit_price
            * Decimal(candidate.contracts)
            * Decimal("100")
        ).quantize(Decimal("0.01"))
        if premium_at_limit > self.settings.zero_dte_lottery_strategy.max_premium_per_trade:
            raise ValueError("Zero-DTE lottery limit price exceeds the configured $150 premium cap.")

        order = self.order_service.submit_order(
            CreateOrderRequest(
                external_account_id=request.external_account_id,
                broker=BrokerName.LONGBRIDGE,
                symbol=candidate.option_symbol,
                asset_type=AssetType.OPTION,
                side=OrderSide.BUY,
                quantity=candidate.contracts,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                mode=request.mode,
                limit_price=limit_price,
                option_contract=OptionContractRef(
                    underlying_symbol=candidate.underlying_symbol,
                    expiration_date=candidate.expiration_date,
                    strike=candidate.strike,
                    right=candidate.direction,
                ),
                remark=self._order_remark(request.remark),
            )
        )
        return ZeroDteLotteryExecutionResult(
            preview=preview,
            order=order,
        )

    def run_scan(
        self,
        *,
        external_account_id: str,
        symbol: str | None = None,
        direction: str = "auto",
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
        force: bool = False,
    ) -> ZeroDteLotteryScanResult:
        scanned_at = self._reference_time(as_of)
        if mode != ExecutionMode.PAPER:
            raise ValueError("Zero-DTE lottery automation is paper-only in the current implementation.")
        not_due_reason = None if force else self._scan_not_due_reason(scanned_at)
        if not_due_reason is not None:
            return ZeroDteLotteryScanResult(
                external_account_id=external_account_id,
                mode=mode,
                scanned_at=scanned_at,
                reason=not_due_reason,
            )

        preview = self.preview(
            external_account_id=external_account_id,
            symbol=symbol,
            direction=direction,
            mode=mode,
            as_of=scanned_at,
        )
        if not preview.eligible or preview.candidate is None:
            reason = preview.reasons[0] if preview.reasons else "Zero-DTE lottery preview did not produce a candidate."
            run = self._record_scan_run(
                external_account_id=external_account_id,
                mode=mode,
                preview=preview,
                status=StrategyRunStatus.SKIPPED,
                summary="Zero-DTE lottery scan did not find an eligible candidate.",
                reason=reason,
                order_id=None,
            )
            signal = self._record_scan_signal(
                external_account_id=external_account_id,
                mode=mode,
                preview=preview,
                run_id=run.id if run is not None else None,
                signal_type=StrategySignalType.RISK_CHECK,
                summary="Zero-DTE lottery scan skipped.",
                detail=reason,
            )
            return ZeroDteLotteryScanResult(
                external_account_id=external_account_id,
                mode=mode,
                scanned_at=scanned_at,
                preview=preview,
                run=run,
                signal=signal,
                reason=reason,
            )

        execution = self.execute(
            ExecuteZeroDteLotteryRequest(
                external_account_id=external_account_id,
                symbol=preview.symbol,
                direction=preview.direction.value if preview.direction is not None else direction,
                mode=mode,
                as_of=scanned_at,
                confirm_paper_order=True,
                remark="auto-scan" if not force else "manual-scan",
            )
        )
        run = self._record_scan_run(
            external_account_id=external_account_id,
            mode=mode,
            preview=execution.preview,
            status=StrategyRunStatus.EXECUTED,
            summary=f"Zero-DTE lottery paper order submitted for {execution.order.symbol}.",
            reason=None,
            order_id=execution.order.id,
        )
        signal = self._record_scan_signal(
            external_account_id=external_account_id,
            mode=mode,
            preview=execution.preview,
            run_id=run.id if run is not None else None,
            signal_type=StrategySignalType.EXECUTION,
            summary=f"Zero-DTE lottery paper order submitted for {execution.order.symbol}.",
            detail=None,
        )
        return ZeroDteLotteryScanResult(
            external_account_id=external_account_id,
            mode=mode,
            scanned_at=scanned_at,
            executed=True,
            preview=execution.preview,
            execution=execution,
            run=run,
            signal=signal,
        )

    def _select_candidate_quote(
        self,
        *,
        quotes: list[OptionMarketSnapshot],
        direction: OptionRight,
        underlying_quote: SecurityQuoteSnapshot,
        evaluated_at: datetime,
        mode: ExecutionMode,
    ) -> ZeroDteLotteryCandidate | None:
        strategy = self.settings.zero_dte_lottery_strategy
        ranked = sorted(
            [
                quote
                for quote in quotes
                if quote.right == direction
                and quote.delta is not None
                and strategy.delta_min <= abs(quote.delta) <= strategy.delta_max
                and (quote.open_interest or 0) >= strategy.min_open_interest
                and quote.volume >= strategy.min_volume
                and self._is_option_quote_fresh(quote, evaluated_at=evaluated_at)
            ],
            key=lambda quote: (
                abs(abs(quote.delta or Decimal("0")) - strategy.delta_target),
                abs(quote.strike - underlying_quote.last_done),
                -(quote.open_interest or 0),
                -quote.volume,
            ),
        )
        candidates: list[ZeroDteLotteryCandidate] = []
        for quote in ranked[:12]:
            enriched = self._with_top_of_book(quote, mode=mode)
            candidate = self._build_candidate(
                quote=enriched,
                underlying_price=underlying_quote.last_done,
                evaluated_at=evaluated_at,
            )
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda candidate: (
                abs(abs(candidate.delta or Decimal("0")) - strategy.delta_target),
                candidate.premium_at_ask,
                abs(candidate.strike - candidate.underlying_price),
            ),
        )

    def _build_candidate(
        self,
        *,
        quote: OptionMarketSnapshot,
        underlying_price: Decimal,
        evaluated_at: datetime,
    ) -> ZeroDteLotteryCandidate | None:
        strategy = self.settings.zero_dte_lottery_strategy
        if quote.bid is None or quote.ask is None:
            return None
        if quote.bid < strategy.min_bid or quote.ask <= quote.bid:
            return None
        mid = self._quote_mid(quote)
        if mid <= Decimal("0"):
            return None
        if ((quote.ask - quote.bid) / mid) > strategy.max_bid_ask_spread_pct:
            return None
        premium_at_ask = (
            quote.ask * quote.contract_multiplier * Decimal(strategy.contracts_per_trade)
        ).quantize(Decimal("0.01"))
        if premium_at_ask > strategy.max_premium_per_trade:
            return None
        return ZeroDteLotteryCandidate(
            underlying_symbol=quote.underlying_symbol,
            direction=quote.right,
            expiration_date=quote.expiration_date,
            days_to_expiration=self._days_to_expiration(quote.expiration_date, evaluated_at),
            contracts=strategy.contracts_per_trade,
            option_symbol=quote.symbol,
            strike=quote.strike,
            option_bid=quote.bid,
            option_ask=quote.ask,
            option_mid=mid,
            premium_at_ask=premium_at_ask,
            max_loss=premium_at_ask,
            underlying_price=underlying_price,
            delta=quote.delta,
            open_interest=quote.open_interest,
            volume=quote.volume,
            quote_timestamp=quote.timestamp,
        )

    def _option_symbols_for_snapshot(
        self,
        *,
        chain: list[OptionChainEntry],
        direction: OptionRight,
        underlying_price: Decimal,
    ) -> list[str]:
        if direction == OptionRight.CALL:
            candidates = [
                entry
                for entry in chain
                if entry.standard and entry.call_symbol and entry.strike >= underlying_price
            ]
            ranked = sorted(candidates, key=lambda entry: (abs(entry.strike - underlying_price), entry.strike))
            return [entry.call_symbol for entry in ranked[: self.settings.zero_dte_lottery_strategy.max_candidate_symbols]]
        candidates = [
            entry
            for entry in chain
            if entry.standard and entry.put_symbol and entry.strike <= underlying_price
        ]
        ranked = sorted(candidates, key=lambda entry: (abs(entry.strike - underlying_price), -entry.strike))
        return [entry.put_symbol for entry in ranked[: self.settings.zero_dte_lottery_strategy.max_candidate_symbols]]

    def _resolve_direction(
        self,
        *,
        requested: str,
        underlying_change_pct: Decimal | None,
    ) -> OptionRight | None:
        normalized = requested.strip().lower()
        if normalized in {"call", "calls", "c"}:
            return OptionRight.CALL
        if normalized in {"put", "puts", "p"}:
            return OptionRight.PUT
        if normalized != "auto":
            raise ValueError("direction must be one of auto, call, or put.")
        if underlying_change_pct is None:
            return None
        threshold = self.settings.zero_dte_lottery_strategy.min_direction_change_pct
        if underlying_change_pct >= threshold:
            return OptionRight.CALL
        if underlying_change_pct <= -threshold:
            return OptionRight.PUT
        return None

    def _select_today_expiration(
        self,
        expiry_dates: list[date],
        *,
        evaluated_at: datetime,
    ) -> date | None:
        today = evaluated_at.astimezone(self.new_york).date()
        return today if today in expiry_dates else None

    def _scan_not_due_reason(self, scanned_at: datetime) -> str | None:
        strategy = self.settings.zero_dte_lottery_strategy
        if not strategy.enabled:
            return "Zero-DTE lottery strategy is disabled by configuration."
        if not strategy.auto_execute_enabled:
            return "Zero-DTE lottery auto-execution is disabled by configuration."
        local_time = scanned_at.astimezone(self.new_york)
        if local_time.weekday() >= 5:
            return "Zero-DTE lottery scans only run on U.S. options weekdays."
        window_minutes = (local_time.hour * 60) + local_time.minute
        start_minutes = (strategy.scan_window_start_hour_et * 60) + strategy.scan_window_start_minute_et
        end_minutes = (strategy.scan_window_end_hour_et * 60) + strategy.scan_window_end_minute_et
        if window_minutes < start_minutes or window_minutes > end_minutes:
            return "Zero-DTE lottery scan is outside the configured ET automation window."
        return None

    def _assert_daily_trade_capacity(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        evaluated_at: datetime,
    ) -> None:
        existing_orders = self.order_service.list_orders(external_account_id=external_account_id)
        session_date = evaluated_at.astimezone(self.new_york).date()
        count = sum(
            1
            for order in existing_orders
            if self._is_same_day_lottery_order(order, mode=mode, session_date=session_date)
        )
        if count >= self.settings.zero_dte_lottery_strategy.max_trades_per_day:
            raise ValueError("Zero-DTE lottery daily trade cap has already been reached.")

    def _record_scan_run(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        preview: ZeroDteLotteryPreviewResult,
        status: StrategyRunStatus,
        summary: str,
        reason: str | None,
        order_id: str | None,
    ):
        if self.experiments is None:
            return None
        return self.experiments.create_run(
            CreateStrategyRunRequest(
                strategy_id=self.strategy_id,
                external_account_id=external_account_id,
                mode=mode,
                run_type="auto_scan",
                status=status,
                symbol=preview.symbol,
                order_id=order_id,
                started_at=preview.evaluated_at,
                completed_at=datetime.now(timezone.utc),
                summary=summary,
                reason=reason,
                metrics_payload=preview.model_dump(mode="json"),
            )
        )

    def _record_scan_signal(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        preview: ZeroDteLotteryPreviewResult,
        run_id: str | None,
        signal_type: StrategySignalType,
        summary: str,
        detail: str | None,
    ):
        if self.experiments is None:
            return None
        return self.experiments.create_signal(
            CreateStrategySignalRequest(
                strategy_id=self.strategy_id,
                external_account_id=external_account_id,
                mode=mode,
                signal_type=signal_type,
                symbol=preview.symbol,
                run_id=run_id,
                strength=Decimal("0.20") if preview.eligible else Decimal("0"),
                summary=summary,
                detail=detail,
                source=self.strategy_id,
                signal_payload=preview.model_dump(mode="json"),
                emitted_at=datetime.now(timezone.utc),
            )
        )

    def _is_same_day_lottery_order(
        self,
        order: Order,
        *,
        mode: ExecutionMode,
        session_date: date,
    ) -> bool:
        if order.mode != mode or order.submitted_at is None:
            return False
        if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
            return False
        if order.asset_type != AssetType.OPTION or order.side != OrderSide.BUY:
            return False
        submitted_date = order.submitted_at.astimezone(self.new_york).date()
        if submitted_date != session_date:
            return False
        payload = order.raw_payload or {}
        request_payload = payload.get("submission_request") if isinstance(payload, dict) else None
        if not isinstance(request_payload, dict):
            return False
        remark = request_payload.get("remark")
        return isinstance(remark, str) and remark.startswith(self.strategy_id)

    def _order_remark(self, requested_remark: str | None) -> str:
        if not requested_remark:
            return self.strategy_id
        return f"{self.strategy_id}:{requested_remark}"[:64]

    def _runtime_state(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> ZeroDteLotteryRuntimeState:
        strategy = self.settings.zero_dte_lottery_strategy
        return ZeroDteLotteryRuntimeState(
            external_account_id=external_account_id,
            mode=mode,
            enabled=strategy.enabled,
            auto_execute_enabled=strategy.auto_execute_enabled,
            scan_interval_seconds=strategy.scan_interval_seconds,
            scan_window_start=self._format_scan_window_time(
                hour=strategy.scan_window_start_hour_et,
                minute=strategy.scan_window_start_minute_et,
            ),
            scan_window_end=self._format_scan_window_time(
                hour=strategy.scan_window_end_hour_et,
                minute=strategy.scan_window_end_minute_et,
            ),
            max_premium_per_trade=strategy.max_premium_per_trade,
            contracts_per_trade=strategy.contracts_per_trade,
            max_trades_per_day=strategy.max_trades_per_day,
            symbols=list(strategy.symbols),
        )

    @staticmethod
    def _format_scan_window_time(*, hour: int, minute: int) -> str:
        return f"{hour:02d}:{minute:02d} ET"

    def _ensure_account(self, external_account_id: str) -> None:
        account = self.broker_accounts.get_by_external_account_id(external_account_id)
        if account is None:
            raise LookupError(f"Broker account '{external_account_id}' was not found.")
        if not account.is_active:
            raise ValueError(f"Broker account '{external_account_id}' is not active.")

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

    def _is_option_quote_fresh(
        self,
        quote: OptionMarketSnapshot,
        *,
        evaluated_at: datetime,
    ) -> bool:
        quote_time = quote.timestamp
        if quote_time.tzinfo is None:
            quote_time = quote_time.replace(tzinfo=timezone.utc)
        age_seconds = (
            evaluated_at.astimezone(timezone.utc) - quote_time.astimezone(timezone.utc)
        ).total_seconds()
        if age_seconds < -300:
            return False
        return age_seconds <= self.settings.zero_dte_lottery_strategy.max_option_quote_age_seconds

    def _days_to_expiration(self, expiry_date: date, evaluated_at: datetime) -> int:
        return (expiry_date - evaluated_at.astimezone(self.new_york).date()).days

    @staticmethod
    def _quote_mid(quote: OptionMarketSnapshot) -> Decimal:
        return ((quote.bid + quote.ask) / Decimal("2")).quantize(Decimal("0.01"))

    @staticmethod
    def _change_pct(quote: SecurityQuoteSnapshot) -> Decimal | None:
        if quote.prev_close == 0:
            return None
        return (((quote.last_done - quote.prev_close) / quote.prev_close) * Decimal("100")).quantize(Decimal("0.01"))

    @staticmethod
    def _reference_time(as_of: datetime | None) -> datetime:
        reference = as_of or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            return reference.replace(tzinfo=timezone.utc)
        return reference

    @staticmethod
    def _normalize_symbol(symbol: str | None) -> str:
        if symbol is None:
            return ""
        return symbol.strip().upper()
