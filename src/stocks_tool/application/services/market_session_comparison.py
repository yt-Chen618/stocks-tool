"""Capture and read immutable market-session comparisons."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from stocks_tool.adapters.brokers.longbridge import LongbridgeIntegrationError
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.market_session_comparisons import (
    CaptureMarketSessionComparisonRequest,
    CaptureMarketSessionComparisonResult,
    DEFAULT_FIELD_EXPLANATIONS,
    MarketSessionComparison,
    MarketSessionComparisonAccountNotFoundError,
    MarketSessionComparisonIdempotencyConflictError,
    MarketSessionComparisonNotFoundError,
    MarketSessionComparisonPage,
    MarketSessionComparisonScopeError,
    MarketSessionEvidence,
)
from stocks_tool.domain.models import PreOpenAssessmentRun


class MarketSessionComparisonRepository(Protocol):
    def get_account_context(self, external_account_id: str) -> tuple[str, str | None] | None: ...

    def create_comparison(self, comparison: MarketSessionComparison) -> MarketSessionComparison: ...

    def get_by_idempotency_key(self, idempotency_key: str) -> MarketSessionComparison | None: ...

    def get_comparison(self, comparison_id: str) -> MarketSessionComparison | None: ...

    def list_comparisons(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        symbol: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> MarketSessionComparisonPage: ...

    def latest_comparison(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        symbol: str,
    ) -> MarketSessionComparison | None: ...


class PreOpenRunRepository(Protocol):
    def get_run(self, run_id: str) -> PreOpenAssessmentRun | None: ...

    def list_runs(
        self,
        *,
        external_account_id: str | None = None,
        limit: int = 20,
    ) -> list[PreOpenAssessmentRun]: ...


class MarketDataGateway(Protocol):
    def get_us_market_calendar(self, local_date: date, mode: ExecutionMode) -> tuple[bool, bool]: ...

    def get_quote(self, symbol: str, mode: ExecutionMode) -> Any: ...

    def get_recent_daily_bars(self, symbol: str, *, count: int, mode: ExecutionMode) -> list[Any]: ...


class MarketSessionComparisonService:
    NEW_YORK = ZoneInfo("America/New_York")
    STALE_AFTER_SECONDS = 5 * 60

    def __init__(
        self,
        *,
        comparisons: MarketSessionComparisonRepository,
        pre_open_runs: PreOpenRunRepository,
        market_data: MarketDataGateway,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.comparisons = comparisons
        self.pre_open_runs = pre_open_runs
        self.market_data = market_data
        self._now = now or (lambda: datetime.now(timezone.utc))

    def capture(
        self,
        request: CaptureMarketSessionComparisonRequest,
    ) -> CaptureMarketSessionComparisonResult:
        account_context = self.comparisons.get_account_context(request.external_account_id)
        if account_context is None:
            raise MarketSessionComparisonAccountNotFoundError(request.external_account_id)

        idempotency_key = self._idempotency_key(request)
        fingerprint = self._capture_fingerprint(request)
        existing = self.comparisons.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            existing_fingerprint = (existing.raw_evidence or {}).get("capture_request")
            if existing_fingerprint != fingerprint:
                raise MarketSessionComparisonIdempotencyConflictError(request.capture_key or idempotency_key)
            return CaptureMarketSessionComparisonResult(
                comparison=existing,
                captured=False,
                duplicate=True,
                reason="This capture key already has an immutable comparison.",
            )

        baseline_run, baseline_signal, baseline_reason = self._resolve_baseline(request)
        _, account_currency = account_context
        if request.mode is not ExecutionMode.PAPER:
            comparison = self._unavailable_comparison(
                request=request,
                idempotency_key=idempotency_key,
                account_currency=account_currency,
                baseline_run=baseline_run,
                baseline_signal=baseline_signal,
                reason_codes=["mode_unsupported"],
                reason_detail="当前盘前基线只属于模拟盘，实盘模式不生成市场对照证据。",
            )
            return self._persist(comparison, fingerprint=fingerprint)

        if baseline_run is None or baseline_signal is None:
            comparison = self._unavailable_comparison(
                request=request,
                idempotency_key=idempotency_key,
                account_currency=account_currency,
                baseline_run=baseline_run,
                baseline_signal=baseline_signal,
                reason_codes=[baseline_reason or "baseline_missing"],
                reason_detail="没有与该标的和账户匹配的盘前基线，因此无法计算盘前到收盘变化。",
            )
            return self._persist(comparison, fingerprint=fingerprint)

        return self._capture_with_market_data(
            request=request,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            account_currency=account_currency,
            baseline_run=baseline_run,
            baseline_signal=baseline_signal,
        )

    def get(
        self,
        comparison_id: str,
        *,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> MarketSessionComparison:
        comparison = self.comparisons.get_comparison(comparison_id)
        if comparison is None:
            raise MarketSessionComparisonNotFoundError(comparison_id)
        self._ensure_scope(comparison, external_account_id, mode)
        return comparison

    def list(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        symbol: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> MarketSessionComparisonPage:
        self._ensure_account(external_account_id)
        return self.comparisons.list_comparisons(
            external_account_id=external_account_id,
            mode=mode,
            symbol=symbol,
            limit=limit,
            cursor=cursor,
        )

    def latest(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        symbol: str,
    ) -> MarketSessionComparison:
        self._ensure_account(external_account_id)
        comparison = self.comparisons.latest_comparison(
            external_account_id=external_account_id,
            mode=mode,
            symbol=symbol,
        )
        if comparison is None:
            raise MarketSessionComparisonNotFoundError(f"latest:{external_account_id}:{mode.value}:{symbol}")
        return comparison

    def _capture_with_market_data(
        self,
        *,
        request: CaptureMarketSessionComparisonRequest,
        idempotency_key: str,
        fingerprint: dict[str, Any],
        account_currency: str | None,
        baseline_run: PreOpenAssessmentRun,
        baseline_signal: Any,
    ) -> CaptureMarketSessionComparisonResult:
        symbol = request.symbol
        try:
            quote = self.market_data.get_quote(symbol, request.mode)
        except (LongbridgeIntegrationError, TimeoutError, ConnectionError) as exc:
            comparison = self._unavailable_comparison(
                request=request,
                idempotency_key=idempotency_key,
                account_currency=account_currency,
                baseline_run=baseline_run,
                baseline_signal=baseline_signal,
                reason_codes=["provider_unavailable"],
                reason_detail="Longbridge 行情暂时不可用，保留盘前基线但不把缺失行情当作零。",
                raw_evidence={"provider_error": type(exc).__name__},
            )
            return self._persist(comparison, fingerprint=fingerprint)

        raw_quote = self._model_dump(quote)
        if str(getattr(quote, "symbol", "")).strip().upper() != symbol:
            comparison = self._unavailable_comparison(
                request=request, idempotency_key=idempotency_key,
                account_currency=account_currency, baseline_run=baseline_run,
                baseline_signal=baseline_signal, reason_codes=["quote_symbol_mismatch"],
                reason_detail="行情返回的标的与请求不一致，已保留原始证据但不计算变化。",
                raw_evidence={"quote": raw_quote},
            )
            return self._persist(comparison, fingerprint=fingerprint)
        post_quote = getattr(quote, "post_market_quote", None)
        calendar_method = getattr(self.market_data, "get_us_market_calendar", None)
        is_trading_day = False
        is_half_trading_day = False
        calendar_error: str | None = None
        if calendar_method is None:
            calendar_error = "calendar_method_missing"
        else:
            try:
                is_trading_day, is_half_trading_day = calendar_method(
                    baseline_run.target_session_date,
                    request.mode,
                )
            except (LongbridgeIntegrationError, TimeoutError, ConnectionError) as exc:
                calendar_error = type(exc).__name__
        session_close_at = (
            self._session_close_at(
                baseline_run.target_session_date,
                is_half_trading_day=is_half_trading_day,
            )
            if calendar_error is None and is_trading_day
            else None
        )
        daily_bars: list[Any] = []
        daily_error: str | None = None
        get_bars = getattr(self.market_data, "get_recent_daily_bars", None)
        if get_bars is not None:
            try:
                daily_bars = [
                    bar for bar in (get_bars(symbol, count=1, mode=request.mode) or [])
                    if str(getattr(bar, "symbol", "")).strip().upper() == symbol
                ]
            except (LongbridgeIntegrationError, TimeoutError, ConnectionError) as exc:
                daily_error = type(exc).__name__

        baseline_date = baseline_run.target_session_date
        baseline_timestamp = self._optional_datetime(baseline_run.assessment.analyzed_at)
        baseline_price = self._positive_decimal(getattr(baseline_signal, "session_price", None))
        baseline_evidence = MarketSessionEvidence(
            session="pre_open",
            symbol=symbol,
            price=baseline_price,
            timestamp=baseline_timestamp,
            trading_date=baseline_date,
            currency="USD" if symbol.endswith(".US") else None,
            source="pre_open_assessment_run",
            source_field="assessment.signals[].session_price",
            raw_payload={
                "pre_open_run_id": baseline_run.id,
                "signal": self._model_dump(baseline_signal),
            },
        )

        quote_timestamp = self._optional_datetime(getattr(quote, "timestamp", None))
        quote_date = self._ny_date(quote_timestamp)
        post_timestamp = self._optional_datetime(getattr(post_quote, "timestamp", None))
        post_date = self._ny_date(post_timestamp)
        quote_currency = "USD" if symbol.endswith(".US") else None
        reasons: list[str] = []
        now_timestamp = self._timestamp()
        if session_close_at is not None and now_timestamp < session_close_at:
            reasons.append("capture_before_session_close")
            reasons.append("regular_close_not_complete")
        if baseline_timestamp is None:
            reasons.append("timestamp_timezone_unknown")
        elif baseline_date > now_timestamp.astimezone(self.NEW_YORK).date():
            reasons.append("baseline_future")
        if quote_timestamp is None:
            reasons.append("timestamp_timezone_unknown")
        if post_quote is not None and post_timestamp is None:
            reasons.append("timestamp_timezone_unknown")
        raw_evidence: dict[str, Any] = {
            "pre_open_run": self._model_dump(baseline_run),
            "quote": raw_quote,
            "daily_bars": [self._model_dump(bar) for bar in daily_bars],
            "market_calendar": {
                "is_trading_day": is_trading_day,
                "is_half_trading_day": is_half_trading_day,
                "session_close_at": session_close_at.isoformat() if session_close_at else None,
            },
        }
        if daily_error:
            raw_evidence["daily_bar_provider_error"] = daily_error
        if calendar_error:
            raw_evidence["market_calendar_error"] = calendar_error

        regular_price: Decimal | None = None
        regular_evidence: MarketSessionEvidence | None = None
        if (
            post_quote is not None
            and self._positive_decimal(getattr(post_quote, "prev_close", None)) is not None
            and post_timestamp is not None
            and session_close_at is not None
            and session_close_at <= post_timestamp <= now_timestamp
        ):
            regular_price = self._positive_decimal(getattr(post_quote, "prev_close", None))
            regular_evidence = MarketSessionEvidence(
                session="regular_close",
                symbol=symbol,
                price=regular_price,
                timestamp=post_timestamp,
                session_close_at=session_close_at,
                trading_date=post_date,
                currency=quote_currency,
                source="longbridge_quote",
                source_field="post_market_quote.prev_close",
                raw_payload=self._model_dump(post_quote),
            )
        else:
            # Prefer a verified regular quote observed at/after the calendar
            # close. A daily candle timestamp is usually the bar start (09:30
            # ET), so it must never hide a valid close-time quote.
            if (
                quote_date == baseline_date
                and quote_timestamp is not None
                and session_close_at is not None
                and session_close_at <= quote_timestamp <= now_timestamp
            ):
                regular_price = self._positive_decimal(getattr(quote, "last_done", None))
                regular_evidence = MarketSessionEvidence(
                    session="regular_close",
                    symbol=symbol,
                    price=regular_price,
                    timestamp=quote_timestamp,
                    session_close_at=session_close_at,
                    trading_date=quote_date,
                    currency=quote_currency,
                    source="longbridge_quote",
                    source_field="last_done_at_or_after_session_close",
                    raw_payload=raw_quote,
                )
            else:
                daily_bar = self._latest_matching_daily_bar(daily_bars, baseline_date)
                if daily_bar is not None:
                    regular_price = self._positive_decimal(getattr(daily_bar, "close", None))
                    bar_timestamp = self._optional_datetime(getattr(daily_bar, "timestamp", None))
                    regular_evidence = MarketSessionEvidence(
                        session="regular_close",
                        symbol=symbol,
                        price=regular_price,
                        timestamp=bar_timestamp,
                        session_close_at=session_close_at,
                        trading_date=self._ny_date(bar_timestamp),
                        currency=quote_currency,
                        source="longbridge_daily_bar",
                        source_field="close",
                        raw_payload=self._model_dump(daily_bar),
                    )

        post_price: Decimal | None = None
        post_evidence: MarketSessionEvidence | None = None
        if post_quote is not None:
            post_price = self._positive_decimal(getattr(post_quote, "last_done", None))
            post_evidence = MarketSessionEvidence(
                session="post_market",
                symbol=symbol,
                price=post_price,
                timestamp=post_timestamp,
                session_close_at=session_close_at,
                trading_date=post_date,
                currency=quote_currency,
                source="longbridge_quote",
                source_field="post_market_quote.last_done",
                raw_payload=self._model_dump(post_quote),
            )
        else:
            reasons.append("post_market_quote_missing")

        if regular_evidence is None or regular_price is None:
            reasons.append("regular_close_missing")
        if calendar_error:
            reasons.append("market_calendar_unavailable")
        elif not is_trading_day:
            reasons.append("target_not_trading_day")
        elif session_close_at is None:
            reasons.append("regular_close_not_complete")
        if quote_date is not None and quote_date != baseline_date and post_date != baseline_date:
            reasons.append("different_trading_day")
        if post_date is not None and post_date != baseline_date:
            reasons.append("different_trading_day")
        if regular_evidence is not None and regular_evidence.trading_date not in {None, baseline_date}:
            reasons.append("different_trading_day")
        if regular_evidence is not None and regular_evidence.timestamp is not None:
            if baseline_timestamp is not None and regular_evidence.timestamp < baseline_timestamp:
                reasons.append("evidence_before_baseline")
            if session_close_at is None or regular_evidence.timestamp < session_close_at:
                reasons.append("regular_close_not_complete")

        for evidence_timestamp in (baseline_timestamp, quote_timestamp, post_timestamp):
            if evidence_timestamp is not None and evidence_timestamp > now_timestamp:
                reasons.append("future_evidence_timestamp")
        if regular_evidence is not None and regular_evidence.timestamp is not None:
            if regular_evidence.timestamp > now_timestamp:
                reasons.append("future_evidence_timestamp")

        quote_quality = str(getattr(quote, "data_quality", "live") or "unknown").lower()
        cache_age = getattr(quote, "cache_age_seconds", None)
        if quote_quality != "live" or getattr(quote, "warning_code", None) or (
            cache_age is not None and cache_age > self.STALE_AFTER_SECONDS
        ):
            reasons.append("quote_stale")

        if quote_currency is None or baseline_evidence.currency is None:
            reasons.append("currency_unknown")
        elif baseline_evidence.currency != quote_currency:
            reasons.append("currency_mismatch")

        reasons = list(dict.fromkeys(reasons))
        valid_regular = (
            regular_price is not None
            and baseline_price is not None
            and not {
                "different_trading_day",
                "evidence_before_baseline",
                "quote_stale",
                "currency_mismatch",
                "currency_unknown",
                "timestamp_timezone_unknown",
                "market_calendar_unavailable",
                "target_not_trading_day",
                "regular_close_not_complete",
                "future_evidence_timestamp",
                "baseline_future",
                "capture_before_session_close",
            }.intersection(reasons)
        )
        pre_to_regular = self._pct_change(baseline_price, regular_price) if valid_regular else None
        valid_after_hours = valid_regular and post_price is not None and post_date == baseline_date
        regular_to_after = self._pct_change(regular_price, post_price) if valid_after_hours else None
        if not valid_regular:
            status = "not_available"
            quality = "unavailable"
        elif regular_to_after is None:
            status = "partial"
            quality = "partial"
            if "post_market_quote_missing" not in reasons:
                reasons.append("after_hours_price_missing")
        else:
            status = "valid"
            quality = "verified"

        comparison = MarketSessionComparison(
            external_account_id=request.external_account_id,
            mode=request.mode,
            symbol=symbol,
            currency=quote_currency,
            account_currency=account_currency,
            quote_currency=quote_currency,
            pre_open_run_id=baseline_run.id,
            baseline_session_date=baseline_date,
            target_trading_day=baseline_date,
            status=status,
            data_quality=quality,
            reason_codes=reasons,
            reason_detail=self._reason_detail(reasons),
            field_explanations=dict(DEFAULT_FIELD_EXPLANATIONS),
            baseline_price=baseline_price,
            regular_close_price=regular_price,
            after_hours_price=post_price,
            pre_to_regular_close_pct=pre_to_regular,
            regular_close_to_after_hours_pct=regular_to_after,
            baseline_evidence=baseline_evidence,
            regular_close_evidence=regular_evidence,
            post_market_evidence=post_evidence,
            raw_evidence=raw_evidence,
            idempotency_key=idempotency_key,
            evidence_as_of=max(
                [timestamp for timestamp in (baseline_timestamp, quote_timestamp, post_timestamp) if timestamp is not None],
                default=self._timestamp(),
            ),
            created_at=self._timestamp(),
        )
        return self._persist(comparison, fingerprint=fingerprint)

    def _persist(
        self,
        comparison: MarketSessionComparison,
        *,
        fingerprint: dict[str, Any] | None = None,
    ) -> CaptureMarketSessionComparisonResult:
        if fingerprint is not None:
            comparison = comparison.model_copy(
                update={
                    "raw_evidence": {
                        **comparison.raw_evidence,
                        "capture_request": fingerprint,
                    }
                }
            )
        stored = self.comparisons.create_comparison(comparison)
        # Another request may have won the unique-key race after our read.
        # Verify its original request, not the mutable server-selected baseline.
        if (stored.raw_evidence or {}).get("capture_request") != fingerprint:
            raise MarketSessionComparisonIdempotencyConflictError(comparison.idempotency_key)
        duplicate = stored.id != comparison.id
        return CaptureMarketSessionComparisonResult(
            comparison=stored, captured=not duplicate, duplicate=duplicate,
            reason="This capture key already has an immutable comparison." if duplicate else None,
        )

    def _ensure_account(self, external_account_id: str) -> tuple[str, str | None]:
        context = self.comparisons.get_account_context(external_account_id)
        if context is None:
            raise MarketSessionComparisonAccountNotFoundError(external_account_id)
        return context

    def _resolve_baseline(self, request: CaptureMarketSessionComparisonRequest):
        if request.mode is not ExecutionMode.PAPER:
            return None, None, "mode_unsupported"
        if request.pre_open_run_id:
            run = self.pre_open_runs.get_run(request.pre_open_run_id)
            if run is None or run.external_account_id != request.external_account_id:
                return None, None, "baseline_missing"
        else:
            runs = self.pre_open_runs.list_runs(
                external_account_id=request.external_account_id,
                limit=100,
            )
            matching_runs = [
                candidate for candidate in runs
                if candidate.external_account_id == request.external_account_id
                and any(signal.symbol.strip().upper() == request.symbol for signal in candidate.assessment.signals)
            ]
            run = next(
                (candidate for candidate in matching_runs if self._is_true_pre_open_run(candidate)),
                matching_runs[0] if matching_runs else None,
            )
            if run is None:
                return None, None, "baseline_missing"
        if not self._is_true_pre_open_run(run):
            return run, None, "baseline_not_preopen"
        signal = next(
            (
                item
                for item in run.assessment.signals
                if item.symbol.strip().upper() == request.symbol
            ),
            None,
        )
        if signal is None:
            return run, None, "baseline_symbol_missing"
        return run, signal, ""

    @classmethod
    def _is_true_pre_open_run(cls, run: PreOpenAssessmentRun) -> bool:
        assessment = run.assessment
        if assessment.session.strip().lower() != "premarket" or assessment.market_open:
            return False
        analyzed_at = cls._optional_datetime(assessment.analyzed_at)
        if analyzed_at is None:
            return False
        local = analyzed_at.astimezone(cls.NEW_YORK)
        return local.date() == run.target_session_date and local.time() < time(9, 30)

    @staticmethod
    def _idempotency_key(
        request: CaptureMarketSessionComparisonRequest,
    ) -> str:
        # An explicit client token identifies one intent in its account/mode.
        # Hashing bounds the database key regardless of allowed field lengths.
        # A missing token means a new observation, including missing evidence.
        scope = [request.external_account_id, request.mode.value, request.capture_key or str(uuid4())]
        digest = hashlib.sha256(json.dumps(scope, ensure_ascii=False).encode("utf-8")).hexdigest()
        return f"market-session-v2:{digest}"

    @staticmethod
    def _capture_fingerprint(
        request: CaptureMarketSessionComparisonRequest,
    ) -> dict[str, Any]:
        return {
            "external_account_id": request.external_account_id,
            "mode": request.mode.value,
            "symbol": request.symbol,
            "pre_open_run_id": request.pre_open_run_id,
            "capture_key": request.capture_key,
        }

    def _unavailable_comparison(
        self,
        *,
        request: CaptureMarketSessionComparisonRequest,
        idempotency_key: str,
        account_currency: str | None,
        baseline_run: PreOpenAssessmentRun | None,
        baseline_signal: Any | None,
        reason_codes: list[str],
        reason_detail: str,
        raw_evidence: dict[str, Any] | None = None,
    ) -> MarketSessionComparison:
        baseline_evidence = None
        if baseline_run is not None and baseline_signal is not None:
            baseline_evidence = MarketSessionEvidence(
                session="pre_open",
                symbol=request.symbol,
                price=self._positive_decimal(getattr(baseline_signal, "session_price", None)),
                timestamp=self._optional_datetime(baseline_run.assessment.analyzed_at),
                trading_date=baseline_run.target_session_date,
                currency="USD" if request.symbol.endswith(".US") else None,
                source="pre_open_assessment_run",
                source_field="assessment.signals[].session_price",
                raw_payload={"pre_open_run_id": baseline_run.id, "signal": self._model_dump(baseline_signal)},
            )
        return MarketSessionComparison(
            external_account_id=request.external_account_id,
            mode=request.mode,
            symbol=request.symbol,
            currency="USD" if request.symbol.endswith(".US") else None,
            account_currency=account_currency,
            quote_currency="USD" if request.symbol.endswith(".US") else None,
            pre_open_run_id=baseline_run.id if baseline_run is not None else request.pre_open_run_id,
            baseline_session_date=baseline_run.target_session_date if baseline_run is not None else None,
            target_trading_day=baseline_run.target_session_date if baseline_run is not None else None,
            status="not_available",
            data_quality="unavailable",
            reason_codes=list(dict.fromkeys(reason_codes)),
            reason_detail=reason_detail,
            field_explanations=dict(DEFAULT_FIELD_EXPLANATIONS),
            baseline_price=(
                self._positive_decimal(getattr(baseline_signal, "session_price", None))
                if baseline_signal is not None
                else None
            ),
            baseline_evidence=baseline_evidence,
            raw_evidence=raw_evidence or {},
            idempotency_key=idempotency_key,
            evidence_as_of=self._timestamp(),
            created_at=self._timestamp(),
        )

    @staticmethod
    def _ensure_scope(
        comparison: MarketSessionComparison,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> None:
        if comparison.external_account_id != external_account_id or comparison.mode != mode:
            raise MarketSessionComparisonScopeError(comparison.id, external_account_id, mode)

    @classmethod
    def _latest_matching_daily_bar(cls, bars: list[Any], target_date: date) -> Any | None:
        matching = [
            bar
            for bar in bars
            if cls._ny_date(cls._optional_datetime(getattr(bar, "timestamp", None))) == target_date
        ]
        return max(
            matching,
            key=lambda bar: cls._optional_datetime(getattr(bar, "timestamp", None)) or datetime.min.replace(tzinfo=timezone.utc),
            default=None,
        )

    @staticmethod
    def _pct_change(start: Decimal | None, end: Decimal | None) -> Decimal | None:
        if start is None or end is None or start <= 0:
            return None
        return (((end - start) / start) * Decimal("100")).quantize(Decimal("0.01"))

    @staticmethod
    def _positive_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return decimal if decimal > 0 else None

    @staticmethod
    def _optional_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return None
            return value.astimezone(timezone.utc)
        return None

    @classmethod
    def _ny_date(cls, value: datetime | None) -> date | None:
        return value.astimezone(cls.NEW_YORK).date() if value is not None else None

    @classmethod
    def _session_close_at(cls, local_date: date, *, is_half_trading_day: bool) -> datetime:
        close_time = time(13, 0) if is_half_trading_day else time(16, 0)
        return datetime.combine(local_date, close_time, tzinfo=cls.NEW_YORK).astimezone(timezone.utc)

    def _timestamp(self) -> datetime:
        value = self._now()
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _model_dump(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return dict(value)
        return {"value": str(value)}

    @staticmethod
    def _reason_detail(reason_codes: list[str]) -> str:
        labels = {
            "post_market_quote_missing": "没有盘后行情，因此盘后变化保持为空。",
            "regular_close_missing": "没有同交易日的有效常规收盘参考。",
            "different_trading_day": "盘前基线与收盘或盘后证据不属于同一交易日。",
            "evidence_before_baseline": "收盘证据早于盘前基线，无法形成时间顺序。",
            "quote_stale": "Longbridge 返回的行情带有陈旧或降级标记，不作为有效比较。",
            "currency_mismatch": "盘前基准与后续行情的报价币种不一致，不计算比较结果。",
            "currency_unknown": "行情币种没有被明确证明，无法确认两段价格可直接比较。",
            "after_hours_price_missing": "常规收盘存在，但盘后最后价缺失。",
            "timestamp_timezone_unknown": "证据时间没有明确时区，无法确认同一交易日，因此不计算比较。",
            "market_calendar_unavailable": "无法核对该交易日的官方市场日历和收盘时间，因此不计算比较。",
            "target_not_trading_day": "盘前基线对应的日期不是已确认的美股交易日。",
            "regular_close_not_complete": "行情观察发生在该交易日正式收盘前，不能当作收盘参考。",
            "future_evidence_timestamp": "行情证据时间晚于本次捕获时间，无法作为当前可核对证据。",
            "baseline_future": "盘前基线目标交易日尚未到达，不能作为当前市场对照基线。",
            "capture_before_session_close": "捕获发生在该交易日正式收盘前，不能生成收盘对照。",
        }
        return " ".join(labels.get(code, code) for code in reason_codes) or "市场对照证据完整。"
