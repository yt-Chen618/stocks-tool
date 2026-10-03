"""Persistence adapter for immutable market-session comparisons."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord
from stocks_tool.db.market_session_models import MarketSessionComparisonRecord
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.pagination import CursorError, decode_cursor, encode_cursor, normalize_page_limit
from stocks_tool.domain.market_session_comparisons import (
    MarketSessionComparison,
    MarketSessionComparisonPage,
)


class SQLAlchemyMarketSessionComparisonRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_account_context(self, external_account_id: str) -> tuple[str, str | None] | None:
        record = self.session.execute(
            select(BrokerAccountRecord.id, BrokerAccountRecord.base_currency)
            .where(BrokerAccountRecord.external_account_id == external_account_id)
            .limit(1)
        ).one_or_none()
        if record is None:
            return None
        currency = record[1].strip().upper() if record[1] else None
        return record[0], currency

    def create_comparison(self, comparison: MarketSessionComparison) -> MarketSessionComparison:
        account_context = self.get_account_context(comparison.external_account_id)
        record = MarketSessionComparisonRecord(
            id=comparison.id,
            broker_account_id=account_context[0] if account_context else None,
            external_account_id=comparison.external_account_id,
            execution_mode=comparison.mode.value,
            symbol=comparison.symbol,
            currency=comparison.currency,
            account_currency=comparison.account_currency,
            quote_currency=comparison.quote_currency,
            pre_open_run_id=comparison.pre_open_run_id,
            baseline_session_date=comparison.baseline_session_date,
            target_trading_day=comparison.target_trading_day,
            status=comparison.status,
            data_quality=comparison.data_quality,
            reason_codes=list(comparison.reason_codes),
            reason_detail=comparison.reason_detail,
            field_explanations=dict(comparison.field_explanations),
            baseline_price=comparison.baseline_price,
            regular_close_price=comparison.regular_close_price,
            after_hours_price=comparison.after_hours_price,
            pre_to_regular_close_pct=comparison.pre_to_regular_close_pct,
            regular_close_to_after_hours_pct=comparison.regular_close_to_after_hours_pct,
            baseline_evidence=(
                comparison.baseline_evidence.model_dump(mode="json")
                if comparison.baseline_evidence is not None
                else None
            ),
            regular_close_evidence=(
                comparison.regular_close_evidence.model_dump(mode="json")
                if comparison.regular_close_evidence is not None
                else None
            ),
            post_market_evidence=(
                comparison.post_market_evidence.model_dump(mode="json")
                if comparison.post_market_evidence is not None
                else None
            ),
            raw_evidence=dict(comparison.raw_evidence),
            source=comparison.source,
            idempotency_key=comparison.idempotency_key,
            evidence_as_of=comparison.evidence_as_of,
            created_at=comparison.created_at,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.get_by_idempotency_key(comparison.idempotency_key)
            if existing is not None:
                return existing
            raise
        self.session.refresh(record)
        return self._to_domain(record)

    def get_by_idempotency_key(self, idempotency_key: str) -> MarketSessionComparison | None:
        record = self.session.execute(
            select(MarketSessionComparisonRecord)
            .where(MarketSessionComparisonRecord.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        return self._to_domain(record) if record is not None else None

    def get_comparison(self, comparison_id: str) -> MarketSessionComparison | None:
        record = self.session.get(MarketSessionComparisonRecord, comparison_id)
        return self._to_domain(record) if record is not None else None

    def list_comparisons(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        symbol: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> MarketSessionComparisonPage:
        page_limit = normalize_page_limit(limit)
        normalized_symbol = symbol.strip().upper() if symbol and symbol.strip() else None
        scope = {
            "external_account_id": external_account_id,
            "mode": mode.value,
            "symbol": normalized_symbol,
        }
        position = decode_cursor(cursor, resource="market-session-comparisons", scope=scope) if cursor else None
        query = (
            select(MarketSessionComparisonRecord)
            .where(
                MarketSessionComparisonRecord.external_account_id == external_account_id,
                MarketSessionComparisonRecord.execution_mode == mode.value,
            )
            .order_by(
                MarketSessionComparisonRecord.created_at.desc(),
                MarketSessionComparisonRecord.id.desc(),
            )
        )
        if normalized_symbol is not None:
            query = query.where(MarketSessionComparisonRecord.symbol == normalized_symbol)
        if position is not None:
            created_at = self._cursor_datetime(position, "created_at")
            cursor_id = position.get("id")
            if not isinstance(cursor_id, str):
                raise CursorError("Invalid pagination cursor position.")
            query = query.where(
                or_(
                    MarketSessionComparisonRecord.created_at < created_at,
                    and_(
                        MarketSessionComparisonRecord.created_at == created_at,
                        MarketSessionComparisonRecord.id < cursor_id,
                    ),
                )
            )
        query = query.limit(page_limit + 1)
        records = self.session.execute(query).scalars().all()
        has_more = len(records) > page_limit
        page_records = records[:page_limit]
        next_cursor = None
        if has_more and page_records:
            last = page_records[-1]
            next_cursor = encode_cursor(
                resource="market-session-comparisons",
                scope=scope,
                position={"created_at": last.created_at.isoformat(), "id": last.id},
            )
        return MarketSessionComparisonPage(
            items=[self._to_domain(record) for record in page_records],
            limit=page_limit,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    def latest_comparison(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        symbol: str,
    ) -> MarketSessionComparison | None:
        record = self.session.execute(
            select(MarketSessionComparisonRecord)
            .where(
                MarketSessionComparisonRecord.external_account_id == external_account_id,
                MarketSessionComparisonRecord.execution_mode == mode.value,
                MarketSessionComparisonRecord.symbol == symbol.strip().upper(),
            )
            .order_by(
                MarketSessionComparisonRecord.created_at.desc(),
                MarketSessionComparisonRecord.id.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        return self._to_domain(record) if record is not None else None

    @staticmethod
    def _to_domain(record: MarketSessionComparisonRecord) -> MarketSessionComparison:
        return MarketSessionComparison(
            id=record.id,
            external_account_id=record.external_account_id,
            mode=ExecutionMode(record.execution_mode),
            symbol=record.symbol,
            currency=record.currency,
            account_currency=record.account_currency,
            quote_currency=record.quote_currency,
            pre_open_run_id=record.pre_open_run_id,
            baseline_session_date=record.baseline_session_date,
            target_trading_day=record.target_trading_day,
            status=record.status,
            data_quality=record.data_quality,
            reason_codes=list(record.reason_codes or []),
            reason_detail=record.reason_detail,
            field_explanations=dict(record.field_explanations or {}),
            baseline_price=record.baseline_price,
            regular_close_price=record.regular_close_price,
            after_hours_price=record.after_hours_price,
            pre_to_regular_close_pct=record.pre_to_regular_close_pct,
            regular_close_to_after_hours_pct=record.regular_close_to_after_hours_pct,
            baseline_evidence=record.baseline_evidence,
            regular_close_evidence=record.regular_close_evidence,
            post_market_evidence=record.post_market_evidence,
            raw_evidence=dict(record.raw_evidence or {}),
            source=record.source,
            idempotency_key=record.idempotency_key,
            evidence_as_of=record.evidence_as_of,
            created_at=record.created_at,
        )

    @staticmethod
    def _cursor_datetime(position: dict[str, object], key: str):
        value = position.get(key)
        if not isinstance(value, str):
            raise CursorError("Invalid pagination cursor position.")
        try:
            from datetime import datetime

            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise CursorError("Invalid pagination cursor position.") from exc
