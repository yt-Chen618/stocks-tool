from __future__ import annotations

import logging
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.application.services.bull_put.calendar import (
    is_us_options_trading_day as compute_is_us_options_trading_day,
    market_session_label as compute_market_session_label,
    minutes_to_regular_open as compute_minutes_to_regular_open,
    next_regular_open_at as compute_next_regular_open_at,
    session_date as compute_session_date,
    target_session_date as compute_target_session_date,
)
from stocks_tool.application.services.bull_put.candidate import (
    quantize_price as compute_quantize_price,
)
from stocks_tool.application.services.bull_put.monitor import (
    days_to_expiration as compute_days_to_expiration,
)
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import BrokerName, ExecutionMode, JournalEntryType
from stocks_tool.domain.models import (
    CreateJournalEntryRequest,
    DirectionalPutSnapshot,
    OptionChainAnalysis,
    OptionChainExpiryAnalysis,
    OptionChainLiquidStrike,
    OptionMarketSnapshot,
    PreOpenAssessmentCaptureResult,
    PreOpenAssessmentReviewResult,
    PreOpenAssessmentRun,
    PreOpenCheckpoint,
    PreOpenDownsideAssessment,
    PreOpenProxySignal,
    PreOpenReviewCheckpoint,
    SecurityQuoteSnapshot,
)
from stocks_tool.ports.broker_gateway import BrokerMarketDataGateway
from stocks_tool.ports.repository import (
    BrokerAccountRepository,
    PreOpenAssessmentRunRepository,
)

logger = logging.getLogger(__name__)


class PreOpenJournalWriter(Protocol):
    def __call__(self, request: CreateJournalEntryRequest, *, context: str) -> None: ...

PRE_OPEN_CAPTURE_START = datetime_time(hour=8, minute=30)
PRE_OPEN_CAPTURE_END = datetime_time(hour=9, minute=15)
PRE_OPEN_REVIEW_CHECKPOINTS = (
    ("open", "Opening Print", "09:30 ET", datetime_time(hour=9, minute=30)),
    ("first_15", "First 15 Minutes", "09:45 ET", datetime_time(hour=9, minute=45)),
    ("first_30", "First 30 Minutes", "10:00 ET", datetime_time(hour=10, minute=0)),
)


class BullPutPreOpenResearch:
    """Pre-open proxy research, overlays, and persisted follow-through review.

    The strategy service composes this collaborator explicitly. It has no order,
    risk, or web-layer dependency, so the research contract can be tested directly.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        broker_accounts: BrokerAccountRepository,
        pre_open_runs: PreOpenAssessmentRunRepository,
        longbridge_adapter: BrokerMarketDataGateway,
        journal_writer: PreOpenJournalWriter,
    ) -> None:
        self.settings = settings
        self.broker_accounts = broker_accounts
        self.pre_open_runs = pre_open_runs
        self.longbridge_adapter = longbridge_adapter
        self.journal_writer = journal_writer
        self.new_york = ZoneInfo("America/New_York")

    def _session_date(self, as_of: datetime) -> date:
        return compute_session_date(as_of, market_timezone=self.new_york)

    def _is_us_options_trading_day(self, local_date: date) -> bool:
        return compute_is_us_options_trading_day(local_date)

    def _days_to_expiration(self, expiry_date: date, evaluated_at: datetime) -> int:
        return compute_days_to_expiration(
            expiry_date=expiry_date,
            scanned_at=evaluated_at,
            market_timezone=self.new_york,
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

    @staticmethod
    def _quantize_price(value: Decimal) -> Decimal:
        return compute_quantize_price(value)

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
            self.journal_writer(
                CreateJournalEntryRequest(
                    external_account_id=external_account_id,
                    mode=ExecutionMode.PAPER,
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
            self.journal_writer(
                CreateJournalEntryRequest(
                    external_account_id=external_account_id,
                    mode=ExecutionMode.PAPER,
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

    def _pre_open_capture_not_due_reason(self, as_of: datetime) -> str | None:
        local_time = as_of.astimezone(self.new_york)
        if not self._is_us_options_trading_day(local_time.date()):
            return "Automatic pre-open capture only runs on U.S. options trading days."
        if local_time.time() < PRE_OPEN_CAPTURE_START or local_time.time() > PRE_OPEN_CAPTURE_END:
            return "Automatic pre-open capture is outside the configured ET pre-open window."
        return None

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
