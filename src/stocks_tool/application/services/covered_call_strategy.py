from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.application.services.orders import OrderService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderType,
    RiskStatus,
    StrategyProposalStatus,
    StrategyRunStatus,
    StrategySignalType,
    TimeInForce,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    CoveredCallCandidate,
    CoveredCallExecutionResult,
    CoveredCallMonitorResult,
    CoveredCallPreviewResult,
    CoveredCallProposalResult,
    CoveredCallRiskSummary,
    CreateOrderRequest,
    CreateStrategyProposalRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    ExecuteCoveredCallProposalRequest,
    OptionContractRef,
    OptionMarketSnapshot,
    PositionSnapshot,
)
from stocks_tool.ports.repository import (
    AccountSnapshotRepository,
    BrokerAccountRepository,
    StrategyExperimentRepository,
)


class CoveredCallStrategyService:
    strategy_id = "covered_call_v1"

    def __init__(
        self,
        *,
        settings: Settings,
        broker_accounts: BrokerAccountRepository,
        account_snapshots: AccountSnapshotRepository,
        experiments: StrategyExperimentRepository,
        longbridge_adapter: LongbridgeBrokerAdapter,
        order_service: OrderService | None = None,
    ) -> None:
        self.settings = settings
        self.broker_accounts = broker_accounts
        self.account_snapshots = account_snapshots
        self.experiments = experiments
        self.longbridge_adapter = longbridge_adapter
        self.order_service = order_service
        self.new_york = ZoneInfo("America/New_York")

    def preview(
        self,
        *,
        external_account_id: str,
        symbol: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
    ) -> CoveredCallPreviewResult:
        evaluated_at = self._reference_time(as_of)
        self._ensure_account(external_account_id)
        account_snapshot = self._get_latest_account_snapshot(external_account_id)
        position = self._select_position(account_snapshot, symbol=symbol)
        if position is None:
            return CoveredCallPreviewResult(
                external_account_id=external_account_id,
                mode=mode,
                evaluated_at=evaluated_at,
                eligible=False,
                symbol=self._normalize_symbol(symbol) if symbol else None,
                reasons=[
                    "No stock or ETF position with at least 100 shares was found in the latest local account snapshot."
                ],
            )

        normalized_symbol = position.symbol.strip().upper()
        share_quantity = int(position.quantity)
        if share_quantity < self.settings.covered_call_strategy.min_shares:
            return CoveredCallPreviewResult(
                external_account_id=external_account_id,
                mode=mode,
                evaluated_at=evaluated_at,
                eligible=False,
                symbol=normalized_symbol,
                reasons=[
                    f"{normalized_symbol} has {position.quantity} shares; covered calls require at least 100 shares."
                ],
            )

        underlying_quote = self.longbridge_adapter.get_quote(symbol=normalized_symbol, mode=mode)
        expiry_date = self._select_expiration(
            self.longbridge_adapter.list_option_expiry_dates(symbol=normalized_symbol, mode=mode),
            evaluated_at,
        )
        if expiry_date is None:
            return CoveredCallPreviewResult(
                external_account_id=external_account_id,
                mode=mode,
                evaluated_at=evaluated_at,
                eligible=False,
                symbol=normalized_symbol,
                reasons=["No covered-call expiration was available inside the configured DTE window."],
            )

        chain = self.longbridge_adapter.list_option_chain(
            symbol=normalized_symbol,
            expiry_date=expiry_date,
            mode=mode,
        )
        call_symbols = [entry.call_symbol for entry in chain if entry.standard and entry.call_symbol]
        if not call_symbols:
            return CoveredCallPreviewResult(
                external_account_id=external_account_id,
                mode=mode,
                evaluated_at=evaluated_at,
                eligible=False,
                symbol=normalized_symbol,
                selected_expiration_date=expiry_date,
                days_to_expiration=self._days_to_expiration(expiry_date, evaluated_at),
                reasons=["The selected option chain did not include standard call contracts."],
            )

        option_quotes = self.longbridge_adapter.get_option_market_snapshots(
            symbols=call_symbols,
            mode=mode,
        )
        candidate_quote = self._select_call_quote(
            quotes=option_quotes,
            underlying_price=underlying_quote.last_done,
            evaluated_at=evaluated_at,
            mode=mode,
        )
        if candidate_quote is None:
            return CoveredCallPreviewResult(
                external_account_id=external_account_id,
                mode=mode,
                evaluated_at=evaluated_at,
                eligible=False,
                symbol=normalized_symbol,
                selected_expiration_date=expiry_date,
                days_to_expiration=self._days_to_expiration(expiry_date, evaluated_at),
                reasons=[
                    "No liquid out-of-the-money call passed the configured delta, OI, volume, and bid/ask filters."
                ],
            )

        contracts = min(
            share_quantity // 100,
            self.settings.covered_call_strategy.max_contracts_per_symbol,
        )
        candidate = self._build_candidate(
            position=position,
            quote=candidate_quote,
            underlying_price=underlying_quote.last_done,
            contracts=contracts,
            evaluated_at=evaluated_at,
        )
        risk = self._build_risk_summary(position=position, candidate=candidate)
        return CoveredCallPreviewResult(
            external_account_id=external_account_id,
            mode=mode,
            evaluated_at=evaluated_at,
            eligible=risk.status != RiskStatus.BLOCK,
            symbol=normalized_symbol,
            selected_expiration_date=expiry_date,
            days_to_expiration=candidate.days_to_expiration,
            warnings=risk.warnings,
            candidate=candidate,
            risk=risk,
        )

    def create_proposal(
        self,
        *,
        external_account_id: str,
        symbol: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
    ) -> CoveredCallProposalResult:
        preview = self.preview(
            external_account_id=external_account_id,
            symbol=symbol,
            mode=mode,
            as_of=as_of,
        )
        run = self.experiments.create_run(
            CreateStrategyRunRequest(
                strategy_id=self.strategy_id,
                external_account_id=external_account_id,
                mode=mode,
                run_type="proposal_preview",
                status=StrategyRunStatus.EXECUTED if preview.eligible else StrategyRunStatus.SKIPPED,
                symbol=preview.symbol,
                summary=(
                    f"Covered call proposal candidate found for {preview.symbol}."
                    if preview.eligible
                    else "Covered call proposal scan did not find an eligible candidate."
                ),
                reason="; ".join(preview.reasons) if preview.reasons else None,
                started_at=preview.evaluated_at,
                completed_at=datetime.now(timezone.utc),
                metrics_payload=preview.model_dump(mode="json"),
            )
        )
        signal = self.experiments.create_signal(
            CreateStrategySignalRequest(
                strategy_id=self.strategy_id,
                external_account_id=external_account_id,
                mode=mode,
                signal_type=StrategySignalType.CANDIDATE if preview.eligible else StrategySignalType.RISK_CHECK,
                symbol=preview.symbol,
                run_id=run.id,
                strength=self._signal_strength(preview),
                summary=(
                    f"Covered call candidate: sell {preview.candidate.call_symbol}."
                    if preview.candidate is not None
                    else "Covered call candidate blocked by readiness filters."
                ),
                detail="; ".join([*preview.reasons, *preview.warnings]) or None,
                source="covered_call_v1",
                signal_payload=preview.model_dump(mode="json"),
                emitted_at=preview.evaluated_at,
            )
        )
        if not preview.eligible or preview.candidate is None or preview.risk is None:
            return CoveredCallProposalResult(preview=preview, run=run, signal=signal)

        proposal = self.experiments.create_proposal(
            CreateStrategyProposalRequest(
                strategy_id=self.strategy_id,
                external_account_id=external_account_id,
                mode=mode,
                symbol=preview.symbol,
                title=f"Sell covered call on {preview.symbol}",
                proposed_action="sell_covered_call",
                thesis="Harvest option premium against an existing 100-share lot without adding naked short-call exposure.",
                rationale=self._proposal_rationale(preview),
                confidence=self._proposal_confidence(preview),
                expected_max_loss=preview.risk.max_loss_if_zero,
                expected_max_profit=preview.risk.max_assignment_profit,
                approval_required=True,
                source="covered_call_v1",
                source_run_id=run.id,
                candidate_payload=preview.candidate.model_dump(mode="json"),
                risk_payload=preview.risk.model_dump(mode="json"),
                checks=[
                    "local_position_covered",
                    "otm_call",
                    "delta_window",
                    "liquidity_filter",
                    "manual_approval_required",
                ],
            )
        )
        return CoveredCallProposalResult(
            preview=preview,
            proposal=proposal,
            run=run,
            signal=signal,
        )

    def execute_approved_proposal(
        self,
        proposal_id: str,
        request: ExecuteCoveredCallProposalRequest,
    ) -> CoveredCallExecutionResult:
        if self.order_service is None:
            raise RuntimeError("Covered call execution requires an order service.")
        proposal = self.experiments.get_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Strategy proposal '{proposal_id}' was not found.")
        if proposal.strategy_id != self.strategy_id:
            raise ValueError(f"Strategy proposal '{proposal_id}' is not a covered call proposal.")
        if proposal.status != StrategyProposalStatus.APPROVED:
            raise ValueError(f"Strategy proposal '{proposal_id}' must be approved before execution.")
        if proposal.candidate_payload is None:
            raise ValueError(f"Strategy proposal '{proposal_id}' does not include a covered call candidate payload.")

        candidate = CoveredCallCandidate.model_validate(proposal.candidate_payload)
        self._ensure_latest_position_still_covers(
            external_account_id=proposal.external_account_id,
            candidate=candidate,
        )
        limit_price = request.limit_price or candidate.call_bid
        if limit_price <= Decimal("0"):
            raise ValueError(f"Strategy proposal '{proposal_id}' has no positive limit price.")

        order = self.order_service.submit_order(
            CreateOrderRequest(
                external_account_id=proposal.external_account_id,
                broker=BrokerName.LONGBRIDGE,
                symbol=candidate.call_symbol,
                asset_type=AssetType.OPTION,
                side=OrderSide.SELL,
                quantity=candidate.contracts,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                mode=proposal.mode,
                limit_price=limit_price,
                option_contract=OptionContractRef(
                    underlying_symbol=candidate.underlying_symbol,
                    expiration_date=candidate.expiration_date,
                    strike=candidate.call_strike,
                    right=OptionRight.CALL,
                ),
                remark=request.remark or "covered-call",
            )
        )
        run = self.experiments.create_run(
            CreateStrategyRunRequest(
                strategy_id=self.strategy_id,
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                run_type="proposal_execution",
                status=StrategyRunStatus.EXECUTED,
                symbol=proposal.symbol,
                proposal_id=proposal.id,
                order_id=order.id,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                summary=f"Submitted covered call sell order for {candidate.call_symbol}.",
                metrics_payload={
                    "proposal_id": proposal.id,
                    "order_id": order.id,
                    "limit_price": str(limit_price),
                    "candidate": candidate.model_dump(mode="json"),
                },
            )
        )
        signal = self.experiments.create_signal(
            CreateStrategySignalRequest(
                strategy_id=self.strategy_id,
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                signal_type=StrategySignalType.EXECUTION,
                symbol=proposal.symbol,
                run_id=run.id,
                proposal_id=proposal.id,
                summary=f"Covered call order submitted for {candidate.call_symbol}.",
                source="covered_call_v1",
                signal_payload={"order_id": order.id, "candidate": candidate.model_dump(mode="json")},
            )
        )
        executed_proposal = self.experiments.update_proposal_status(
            proposal.id,
            status=StrategyProposalStatus.EXECUTED,
        )
        return CoveredCallExecutionResult(
            proposal=executed_proposal,
            order=order,
            run=run,
            signal=signal,
        )

    def monitor_proposal(
        self,
        proposal_id: str,
        *,
        as_of: datetime | None = None,
        record_signal: bool = True,
    ) -> CoveredCallMonitorResult:
        evaluated_at = self._reference_time(as_of)
        proposal = self.experiments.get_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Strategy proposal '{proposal_id}' was not found.")
        if proposal.strategy_id != self.strategy_id:
            raise ValueError(f"Strategy proposal '{proposal_id}' is not a covered call proposal.")
        if proposal.candidate_payload is None:
            raise ValueError(f"Strategy proposal '{proposal_id}' does not include a covered call candidate payload.")

        candidate = CoveredCallCandidate.model_validate(proposal.candidate_payload)
        underlying_quote = self.longbridge_adapter.get_quote(
            symbol=candidate.underlying_symbol,
            mode=proposal.mode,
        )
        call_quotes = self.longbridge_adapter.get_option_market_snapshots(
            symbols=[candidate.call_symbol],
            mode=proposal.mode,
        )
        call_quote = call_quotes[0] if call_quotes else None
        if call_quote is not None:
            call_quote = self._with_top_of_book(call_quote, mode=proposal.mode)
        call_mark = self._quote_mid(call_quote) if call_quote is not None else None
        estimated_buyback_debit = (
            (call_mark * Decimal(candidate.covered_shares)).quantize(Decimal("0.01"))
            if call_mark is not None
            else None
        )
        estimated_open_pnl = (
            (candidate.premium_income - estimated_buyback_debit).quantize(Decimal("0.01"))
            if estimated_buyback_debit is not None
            else None
        )
        premium_capture_pct = self._safe_pct(estimated_open_pnl, candidate.premium_income)
        days_to_expiration = self._days_to_expiration(candidate.expiration_date, evaluated_at)
        action, reasons = self._covered_call_monitor_action(
            candidate=candidate,
            underlying_price=underlying_quote.last_done,
            premium_capture_pct=premium_capture_pct,
            days_to_expiration=days_to_expiration,
        )
        signal = None
        if record_signal:
            signal = self.experiments.create_signal(
                CreateStrategySignalRequest(
                    strategy_id=self.strategy_id,
                    external_account_id=proposal.external_account_id,
                    mode=proposal.mode,
                    signal_type=StrategySignalType.MONITOR,
                    symbol=proposal.symbol,
                    proposal_id=proposal.id,
                    summary=f"Covered call monitor action: {action}.",
                    detail="; ".join(reasons),
                    source="covered_call_v1",
                    signal_payload={
                        "proposal_id": proposal.id,
                        "underlying_price": str(underlying_quote.last_done),
                        "call_mark": str(call_mark) if call_mark is not None else None,
                        "premium_capture_pct": str(premium_capture_pct)
                        if premium_capture_pct is not None
                        else None,
                        "days_to_expiration": days_to_expiration,
                        "action": action,
                    },
                    emitted_at=evaluated_at,
                )
            )
        return CoveredCallMonitorResult(
            proposal_id=proposal.id,
            external_account_id=proposal.external_account_id,
            symbol=candidate.underlying_symbol,
            evaluated_at=evaluated_at,
            candidate=candidate,
            underlying_price=underlying_quote.last_done,
            call_mark=call_mark,
            estimated_buyback_debit=estimated_buyback_debit,
            estimated_open_pnl=estimated_open_pnl,
            premium_capture_pct=premium_capture_pct,
            days_to_expiration=days_to_expiration,
            action=action,
            reasons=reasons,
            signal=signal,
        )

    def _ensure_account(self, external_account_id: str) -> None:
        account = self.broker_accounts.get_by_external_account_id(external_account_id)
        if account is None or account.broker != BrokerName.LONGBRIDGE:
            raise LookupError(f"No local Longbridge broker account was found for '{external_account_id}'.")

    def _get_latest_account_snapshot(self, external_account_id: str) -> AccountSnapshot:
        snapshot = self.account_snapshots.get_latest_account_snapshot(external_account_id)
        if snapshot is None:
            raise LookupError(
                f"No local account snapshot was found for '{external_account_id}'. Run account sync first."
            )
        return snapshot

    def _select_position(
        self,
        account_snapshot: AccountSnapshot,
        *,
        symbol: str | None,
    ) -> PositionSnapshot | None:
        normalized_symbol = self._normalize_symbol(symbol) if symbol else None
        eligible_positions = [
            position
            for position in account_snapshot.positions
            if position.asset_type in {AssetType.STOCK, AssetType.ETF}
            and int(position.quantity) >= self.settings.covered_call_strategy.min_shares
        ]
        if normalized_symbol is not None:
            return next(
                (position for position in eligible_positions if position.symbol.upper() == normalized_symbol),
                None,
            )
        if not eligible_positions:
            return None
        return max(eligible_positions, key=lambda position: position.market_value)

    def _ensure_latest_position_still_covers(
        self,
        *,
        external_account_id: str,
        candidate: CoveredCallCandidate,
    ) -> None:
        snapshot = self._get_latest_account_snapshot(external_account_id)
        position = next(
            (
                position
                for position in snapshot.positions
                if position.symbol.upper() == candidate.underlying_symbol.upper()
                and position.asset_type in {AssetType.STOCK, AssetType.ETF}
            ),
            None,
        )
        if position is None or int(position.quantity) < candidate.covered_shares:
            raise ValueError(
                f"Latest local snapshot no longer covers {candidate.covered_shares} shares of "
                f"{candidate.underlying_symbol}."
            )

    def _select_expiration(self, expiry_dates: list[date], evaluated_at: datetime) -> date | None:
        strategy = self.settings.covered_call_strategy
        evaluated_date = evaluated_at.astimezone(self.new_york).date()
        candidates = [
            expiry_date
            for expiry_date in expiry_dates
            if strategy.min_dte <= (expiry_date - evaluated_date).days <= strategy.max_dte
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda expiry_date: (expiry_date - evaluated_date).days)

    def _select_call_quote(
        self,
        *,
        quotes: list[OptionMarketSnapshot],
        underlying_price: Decimal,
        evaluated_at: datetime,
        mode: ExecutionMode,
    ) -> OptionMarketSnapshot | None:
        strategy = self.settings.covered_call_strategy
        min_strike = underlying_price * (Decimal("1") + strategy.min_otm_pct)
        max_strike = underlying_price * (Decimal("1") + strategy.max_otm_pct)
        prelim = [
            quote
            for quote in quotes
            if quote.right == OptionRight.CALL
            and min_strike <= quote.strike <= max_strike
            and quote.delta is not None
            and strategy.delta_min <= quote.delta <= strategy.delta_max
            and (quote.open_interest or 0) >= strategy.min_open_interest
            and quote.volume >= strategy.min_volume
            and self._is_option_quote_fresh(quote, evaluated_at=evaluated_at)
        ]
        ranked = sorted(
            prelim,
            key=lambda quote: (
                abs((quote.delta or Decimal("0")) - strategy.delta_target),
                abs(quote.strike - underlying_price),
                -(quote.open_interest or 0),
                -quote.volume,
            ),
        )
        for quote in ranked[:12]:
            enriched = self._with_top_of_book(quote, mode=mode)
            if self._passes_liquidity_filter(enriched):
                return enriched
        return None

    def _build_candidate(
        self,
        *,
        position: PositionSnapshot,
        quote: OptionMarketSnapshot,
        underlying_price: Decimal,
        contracts: int,
        evaluated_at: datetime,
    ) -> CoveredCallCandidate:
        covered_shares = contracts * 100
        call_mid = self._quote_mid(quote)
        premium_income = (quote.bid or Decimal("0")) * Decimal(covered_shares)
        cost_basis = position.average_cost * Decimal(covered_shares)
        income_yield = self._safe_pct(premium_income, underlying_price * Decimal(covered_shares))
        assignment_profit = ((quote.strike - position.average_cost) * Decimal(covered_shares)) + premium_income
        if_called_return = self._safe_pct(assignment_profit, cost_basis)
        return CoveredCallCandidate(
            underlying_symbol=position.symbol.upper(),
            expiration_date=quote.expiration_date,
            days_to_expiration=self._days_to_expiration(quote.expiration_date, evaluated_at),
            contracts=contracts,
            covered_shares=covered_shares,
            share_quantity=position.quantity,
            average_cost=position.average_cost,
            underlying_price=underlying_price,
            call_symbol=quote.symbol,
            call_strike=quote.strike,
            call_bid=quote.bid or Decimal("0"),
            call_ask=quote.ask or Decimal("0"),
            call_mid=call_mid,
            premium_income=premium_income.quantize(Decimal("0.01")),
            annualized_income_yield=self._annualize(income_yield, quote.expiration_date, evaluated_at),
            if_called_return_pct=if_called_return,
            delta=quote.delta,
            open_interest=quote.open_interest,
            volume=quote.volume,
            quote_timestamp=quote.timestamp,
        )

    def _build_risk_summary(
        self,
        *,
        position: PositionSnapshot,
        candidate: CoveredCallCandidate,
    ) -> CoveredCallRiskSummary:
        warnings: list[str] = []
        if candidate.call_strike < position.average_cost:
            warnings.append("Selected call strike is below the current average cost and may lock in a realized loss if assigned.")
        shares_not_covered = position.quantity - Decimal(candidate.covered_shares)
        if shares_not_covered > 0:
            warnings.append(f"{shares_not_covered} shares remain uncovered by this one-contract proposal.")

        assignment_profit = (
            (candidate.call_strike - position.average_cost) * Decimal(candidate.covered_shares)
        ) + candidate.premium_income
        max_loss_if_zero = (position.average_cost * Decimal(candidate.covered_shares)) - candidate.premium_income
        break_even = position.average_cost - (candidate.premium_income / Decimal(candidate.covered_shares))
        return CoveredCallRiskSummary(
            status=RiskStatus.WARN if warnings else RiskStatus.PASS,
            warnings=warnings,
            max_income=candidate.premium_income,
            max_assignment_profit=assignment_profit.quantize(Decimal("0.01")),
            max_loss_if_zero=max_loss_if_zero.quantize(Decimal("0.01")),
            break_even=break_even.quantize(Decimal("0.01")),
            shares_not_covered=shares_not_covered,
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

    def _passes_liquidity_filter(self, quote: OptionMarketSnapshot) -> bool:
        strategy = self.settings.covered_call_strategy
        if quote.bid is None or quote.ask is None:
            return False
        if quote.bid < strategy.min_bid or quote.ask <= quote.bid:
            return False
        mid = self._quote_mid(quote)
        if mid <= Decimal("0"):
            return False
        return ((quote.ask - quote.bid) / mid) <= strategy.max_bid_ask_spread_pct

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
        return age_seconds <= self.settings.covered_call_strategy.max_option_quote_age_seconds

    def _proposal_rationale(self, preview: CoveredCallPreviewResult) -> str:
        candidate = preview.candidate
        if candidate is None:
            return "Covered call filters did not produce a candidate."
        return (
            f"Sell {candidate.contracts} {candidate.call_symbol} against {candidate.covered_shares} existing "
            f"{candidate.underlying_symbol} shares. Bid premium is ${candidate.call_bid} with "
            f"{candidate.days_to_expiration} DTE and delta {candidate.delta}."
        )

    def _proposal_confidence(self, preview: CoveredCallPreviewResult) -> Decimal:
        if preview.candidate is None or preview.risk is None:
            return Decimal("0")
        confidence = Decimal("0.60")
        if preview.risk.status == RiskStatus.PASS:
            confidence += Decimal("0.05")
        if preview.candidate.open_interest and preview.candidate.open_interest >= 500:
            confidence += Decimal("0.03")
        return min(confidence, Decimal("0.75"))

    def _covered_call_monitor_action(
        self,
        *,
        candidate: CoveredCallCandidate,
        underlying_price: Decimal,
        premium_capture_pct: Decimal | None,
        days_to_expiration: int,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        if premium_capture_pct is not None and premium_capture_pct >= Decimal("50"):
            reasons.append("At least 50% of the original premium is captured.")
            return "consider_buyback_take_profit", reasons
        if underlying_price >= candidate.call_strike:
            reasons.append("Underlying is trading at or above the short call strike.")
            return "assignment_or_roll_review", reasons
        if underlying_price >= candidate.call_strike * Decimal("0.995"):
            reasons.append("Underlying is within 0.5% of the short call strike.")
            return "watch_assignment_pressure", reasons
        if days_to_expiration <= 7:
            reasons.append("Covered call is inside the final 7 DTE management window.")
            return "expiration_week_review", reasons
        reasons.append("No take-profit, assignment-pressure, or expiration-week trigger is active.")
        return "hold", reasons

    def _signal_strength(self, preview: CoveredCallPreviewResult) -> Decimal:
        if not preview.eligible or preview.candidate is None:
            return Decimal("0")
        if preview.risk and preview.risk.status == RiskStatus.PASS:
            return Decimal("0.35")
        return Decimal("0.20")

    def _days_to_expiration(self, expiry_date: date, evaluated_at: datetime) -> int:
        evaluated_date = evaluated_at.astimezone(self.new_york).date()
        return (expiry_date - evaluated_date).days

    @staticmethod
    def _quote_mid(quote: OptionMarketSnapshot) -> Decimal:
        if quote.bid is not None and quote.ask is not None:
            return ((quote.bid + quote.ask) / Decimal("2")).quantize(Decimal("0.01"))
        if quote.bid is not None:
            return quote.bid.quantize(Decimal("0.01"))
        if quote.ask is not None:
            return quote.ask.quantize(Decimal("0.01"))
        return Decimal("0")

    @staticmethod
    def _safe_pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
        if denominator == 0:
            return None
        return ((numerator / denominator) * Decimal("100")).quantize(Decimal("0.01"))

    def _annualize(
        self,
        income_yield: Decimal | None,
        expiration_date: date,
        evaluated_at: datetime,
    ) -> Decimal | None:
        if income_yield is None:
            return None
        days = self._days_to_expiration(expiration_date, evaluated_at)
        if days <= 0:
            return None
        return ((income_yield / Decimal(days)) * Decimal("365")).quantize(Decimal("0.01"))

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
