"""Persistence adapter for durable research screens and cases."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord, StrategyAdvisorRunRecord, StrategyProposalRecord
from stocks_tool.db.research_models import ResearchCaseRecord, ResearchScreenRecord
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.pagination import CursorError, CursorPage, decode_cursor, encode_cursor, normalize_page_limit
from stocks_tool.domain.research_records import (
    ResearchCase,
    ResearchCasePage,
    ResearchScreen,
    ResearchScreenPage,
    ResearchScreenNameConflictError,
)


class SQLAlchemyResearchRepository:
    """Store immutable case snapshots and mutable screen definitions.

    This adapter deliberately has no broker dependency.  Account and reference
    checks are local database lookups; the capture service owns the explicit
    read-service call that produces a point-in-time snapshot.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_screen(self, screen: ResearchScreen) -> ResearchScreen:
        record = ResearchScreenRecord(
            id=screen.id,
            external_account_id=screen.external_account_id,
            execution_mode=screen.mode.value,
            name=screen.name,
            description=screen.description,
            configuration=dict(screen.configuration),
            symbols=list(screen.symbols),
            created_at=screen.created_at,
            updated_at=screen.updated_at,
        )
        self.session.add(record)
        self._commit_screen(screen.name)
        self.session.refresh(record)
        return self._to_screen(record)

    def list_screens(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
    ) -> list[ResearchScreen]:
        query = select(ResearchScreenRecord).order_by(
            ResearchScreenRecord.updated_at.desc(),
            ResearchScreenRecord.created_at.desc(),
            ResearchScreenRecord.id.desc(),
        )
        if external_account_id is not None:
            query = query.where(ResearchScreenRecord.external_account_id == external_account_id)
        if mode is not None:
            query = query.where(ResearchScreenRecord.execution_mode == mode.value)
        return [self._to_screen(record) for record in self.session.execute(query).scalars().all()]

    def list_screens_page(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResearchScreenPage:
        page_limit = normalize_page_limit(limit)
        scope = {"external_account_id": external_account_id, "mode": mode.value}
        position = decode_cursor(cursor, resource="research-screens", scope=scope) if cursor else None
        query = select(ResearchScreenRecord).where(
            ResearchScreenRecord.external_account_id == external_account_id,
            ResearchScreenRecord.execution_mode == mode.value,
        )
        query = self._apply_screen_cursor(query, position)
        query = query.order_by(
            ResearchScreenRecord.updated_at.desc(),
            ResearchScreenRecord.created_at.desc(),
            ResearchScreenRecord.id.desc(),
        ).limit(page_limit + 1)
        records = self.session.execute(query).scalars().all()
        has_more = len(records) > page_limit
        records = records[:page_limit]
        next_cursor = None
        if has_more and records:
            last = records[-1]
            next_cursor = encode_cursor(
                resource="research-screens",
                scope=scope,
                position={
                    "updated_at": last.updated_at.isoformat(),
                    "created_at": last.created_at.isoformat(),
                    "id": last.id,
                },
            )
        return ResearchScreenPage(
            items=[self._to_screen(record) for record in records],
            next_cursor=next_cursor,
            has_more=has_more,
            limit=page_limit,
        )

    def get_screen(self, screen_id: str) -> ResearchScreen | None:
        record = self.session.get(ResearchScreenRecord, screen_id)
        return self._to_screen(record) if record is not None else None

    def update_screen(self, screen: ResearchScreen) -> ResearchScreen:
        record = self.session.get(ResearchScreenRecord, screen.id)
        if record is None:
            return None  # type: ignore[return-value]
        record.name = screen.name
        record.description = screen.description
        record.configuration = dict(screen.configuration)
        record.symbols = list(screen.symbols)
        record.updated_at = screen.updated_at
        self._commit_screen(screen.name)
        self.session.refresh(record)
        return self._to_screen(record)

    def create_case(self, case: ResearchCase) -> ResearchCase:
        record = ResearchCaseRecord(
            id=case.id,
            screen_id=case.screen_id,
            external_account_id=case.external_account_id,
            execution_mode=case.mode.value,
            title=case.title,
            notes=case.notes,
            next_action=case.next_action,
            configuration=dict(case.configuration),
            universe=case.universe,
            symbols=list(case.symbols),
            primary_symbol=case.primary_symbol,
            as_of=case.as_of,
            data_quality=case.data_quality,
            warnings=list(case.warnings),
            source=case.source,
            proposal_ids=list(case.proposal_ids),
            advisor_run_ids=list(case.advisor_run_ids),
            created_at=case.created_at,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_case(record)

    def list_cases(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        screen_id: str | None = None,
        symbol: str | None = None,
    ) -> list[ResearchCase]:
        query = select(ResearchCaseRecord).order_by(
            ResearchCaseRecord.as_of.desc(),
            ResearchCaseRecord.created_at.desc(),
            ResearchCaseRecord.id.desc(),
        )
        if external_account_id is not None:
            query = query.where(ResearchCaseRecord.external_account_id == external_account_id)
        if mode is not None:
            query = query.where(ResearchCaseRecord.execution_mode == mode.value)
        if screen_id is not None:
            query = query.where(ResearchCaseRecord.screen_id == screen_id)
        if symbol is not None and symbol.strip():
            query = query.where(ResearchCaseRecord.symbols.contains([symbol.strip().upper()]))
        return [self._to_case(record) for record in self.session.execute(query).scalars().all()]

    def list_cases_page(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        screen_id: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResearchCasePage:
        page_limit = normalize_page_limit(limit)
        normalized_symbol = symbol.strip().upper() if symbol and symbol.strip() else None
        scope = {
            "external_account_id": external_account_id,
            "mode": mode.value,
            "screen_id": screen_id,
            "symbol": normalized_symbol,
        }
        position = decode_cursor(cursor, resource="research-cases", scope=scope) if cursor else None
        query = select(ResearchCaseRecord).where(
            ResearchCaseRecord.external_account_id == external_account_id,
            ResearchCaseRecord.execution_mode == mode.value,
        )
        if screen_id is not None:
            query = query.where(ResearchCaseRecord.screen_id == screen_id)
        if normalized_symbol is not None:
            # JSONB containment is evaluated by PostgreSQL.  SQLite's JSON
            # comparator is also SQL-side, so paging never materializes all
            # cases merely to apply a symbol filter in Python.
            query = query.where(ResearchCaseRecord.symbols.contains([normalized_symbol]))
        query = self._apply_case_cursor(query, position)
        query = query.order_by(
            ResearchCaseRecord.as_of.desc(),
            ResearchCaseRecord.created_at.desc(),
            ResearchCaseRecord.id.desc(),
        ).limit(page_limit + 1)
        records = self.session.execute(query).scalars().all()
        has_more = len(records) > page_limit
        records = records[:page_limit]
        next_cursor = None
        if has_more and records:
            last = records[-1]
            next_cursor = encode_cursor(
                resource="research-cases",
                scope=scope,
                position={
                    "as_of": last.as_of.isoformat(),
                    "created_at": last.created_at.isoformat(),
                    "id": last.id,
                },
            )
        return ResearchCasePage(
            items=[self._to_case(record) for record in records],
            next_cursor=next_cursor,
            has_more=has_more,
            limit=page_limit,
        )

    def get_case(self, case_id: str) -> ResearchCase | None:
        record = self.session.get(ResearchCaseRecord, case_id)
        return self._to_case(record) if record is not None else None

    def account_exists(self, external_account_id: str) -> bool:
        return (
            self.session.execute(
                select(BrokerAccountRecord.id)
                .where(BrokerAccountRecord.external_account_id == external_account_id)
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def missing_proposal_ids(
        self,
        proposal_ids: Collection[str],
        *,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> list[str]:
        normalized = list(dict.fromkeys(proposal_ids))
        if not normalized:
            return []
        rows = self.session.execute(
            select(StrategyProposalRecord.id).where(
                StrategyProposalRecord.id.in_(normalized),
                StrategyProposalRecord.external_account_id == external_account_id,
                StrategyProposalRecord.execution_mode == mode.value,
            )
        ).scalars().all()
        found = set(rows)
        return [item for item in normalized if item not in found]

    def missing_advisor_run_ids(
        self,
        advisor_run_ids: Collection[str],
        *,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> list[str]:
        normalized = list(dict.fromkeys(advisor_run_ids))
        if not normalized:
            return []
        rows = self.session.execute(
            select(StrategyAdvisorRunRecord.id).where(
                StrategyAdvisorRunRecord.id.in_(normalized),
                StrategyAdvisorRunRecord.external_account_id == external_account_id,
                StrategyAdvisorRunRecord.execution_mode == mode.value,
            )
        ).scalars().all()
        found = set(rows)
        return [item for item in normalized if item not in found]

    def _commit_screen(self, name: str) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if "uq_research_screens_account_mode_name" in str(exc.orig).lower():
                raise ResearchScreenNameConflictError(name) from exc
            raise

    @staticmethod
    def _parse_cursor_datetime(position: dict[str, object], key: str) -> datetime:
        value = position.get(key)
        if not isinstance(value, str):
            raise CursorError("Invalid pagination cursor position.")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise CursorError("Invalid pagination cursor position.") from exc

    @classmethod
    def _apply_screen_cursor(cls, query, position: dict[str, object] | None):
        if position is None:
            return query
        updated_at = cls._parse_cursor_datetime(position, "updated_at")
        created_at = cls._parse_cursor_datetime(position, "created_at")
        cursor_id = position.get("id")
        if not isinstance(cursor_id, str):
            raise CursorError("Invalid pagination cursor position.")
        return query.where(
            or_(
                ResearchScreenRecord.updated_at < updated_at,
                and_(
                    ResearchScreenRecord.updated_at == updated_at,
                    ResearchScreenRecord.created_at < created_at,
                ),
                and_(
                    ResearchScreenRecord.updated_at == updated_at,
                    ResearchScreenRecord.created_at == created_at,
                    ResearchScreenRecord.id < cursor_id,
                ),
            )
        )

    @classmethod
    def _apply_case_cursor(cls, query, position: dict[str, object] | None):
        if position is None:
            return query
        as_of = cls._parse_cursor_datetime(position, "as_of")
        created_at = cls._parse_cursor_datetime(position, "created_at")
        cursor_id = position.get("id")
        if not isinstance(cursor_id, str):
            raise CursorError("Invalid pagination cursor position.")
        return query.where(
            or_(
                ResearchCaseRecord.as_of < as_of,
                and_(
                    ResearchCaseRecord.as_of == as_of,
                    ResearchCaseRecord.created_at < created_at,
                ),
                and_(
                    ResearchCaseRecord.as_of == as_of,
                    ResearchCaseRecord.created_at == created_at,
                    ResearchCaseRecord.id < cursor_id,
                ),
            )
        )

    @staticmethod
    def _to_screen(record: ResearchScreenRecord) -> ResearchScreen:
        return ResearchScreen(
            id=record.id,
            external_account_id=record.external_account_id,
            mode=ExecutionMode(record.execution_mode),
            name=record.name,
            description=record.description,
            configuration=dict(record.configuration or {}),
            symbols=list(record.symbols or []),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_case(record: ResearchCaseRecord) -> ResearchCase:
        return ResearchCase(
            id=record.id,
            screen_id=record.screen_id,
            external_account_id=record.external_account_id,
            mode=ExecutionMode(record.execution_mode),
            title=record.title,
            notes=record.notes,
            next_action=record.next_action,
            configuration=dict(record.configuration or {}),
            universe=record.universe or {},
            symbols=list(record.symbols or []),
            primary_symbol=record.primary_symbol,
            as_of=record.as_of,
            data_quality=record.data_quality,
            warnings=list(record.warnings or []),
            source=record.source,
            proposal_ids=list(record.proposal_ids or []),
            advisor_run_ids=list(record.advisor_run_ids or []),
            created_at=record.created_at,
        )
