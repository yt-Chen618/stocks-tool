"""Application service for durable research screens, cases, and timelines."""

from __future__ import annotations

from collections.abc import Callable, Collection
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import PreOpenAssessmentRun
from stocks_tool.domain.pagination import CursorError, decode_cursor, encode_cursor, normalize_page_limit
from stocks_tool.domain.research_records import (
    CopyResearchScreenRequest,
    CreateResearchScreenRequest,
    ResearchAccountNotFoundError,
    ResearchCase,
    ResearchCaseCaptureRequest,
    ResearchCaptureUnavailableError,
    ResearchCasePage,
    ResearchReferenceError,
    ResearchScreen,
    ResearchScopeError,
    ResearchSnapshot,
    ResearchTimelineItem,
    ResearchTimelinePreOpenLink,
    ResearchTimelineResponse,
    ResearchTimelinePage,
    ResearchScreenPage,
    ResearchRecordNotFoundError,
    UpdateResearchScreenRequest,
)


class ResearchRepository(Protocol):
    def create_screen(self, screen: ResearchScreen) -> ResearchScreen: ...

    def list_screens(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
    ) -> list[ResearchScreen]: ...

    def get_screen(self, screen_id: str) -> ResearchScreen | None: ...

    def list_screens_page(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResearchScreenPage: ...

    def update_screen(self, screen: ResearchScreen) -> ResearchScreen: ...

    def create_case(self, case: ResearchCase) -> ResearchCase: ...

    def list_cases(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        screen_id: str | None = None,
        symbol: str | None = None,
    ) -> list[ResearchCase]: ...

    def get_case(self, case_id: str) -> ResearchCase | None: ...

    def list_cases_page(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        screen_id: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResearchCasePage: ...


class MarketEvents(Protocol):
    def list_events(self, **kwargs: Any) -> list[Any]: ...


class PreOpenRuns(Protocol):
    def list_runs(self, *, external_account_id: str | None = None, limit: int | None = None) -> list[PreOpenAssessmentRun]: ...


class ResearchSnapshotProvider(Protocol):
    def __call__(
        self,
        *,
        screen: ResearchScreen,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> ResearchSnapshot | Any: ...


class ResearchRecordsService:
    """Coordinate persistence without making broker calls on page reads."""

    def __init__(
        self,
        *,
        repository: ResearchRepository,
        market_events: MarketEvents | None = None,
        pre_open_runs: PreOpenRuns | None = None,
        snapshot_provider: ResearchSnapshotProvider | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.market_events = market_events
        self.pre_open_runs = pre_open_runs
        self.snapshot_provider = snapshot_provider
        self._now = now or (lambda: datetime.now(timezone.utc))

    def create_screen(self, request: CreateResearchScreenRequest) -> ResearchScreen:
        self._ensure_account(request.external_account_id)
        screen = ResearchScreen(**request.model_dump())
        return self.repository.create_screen(screen)

    def list_screens(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> list[ResearchScreen]:
        return self.repository.list_screens(external_account_id=external_account_id, mode=mode)

    def get_screen(
        self,
        screen_id: str,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> ResearchScreen:
        screen = self.repository.get_screen(screen_id)
        if screen is None:
            raise ResearchRecordNotFoundError("screen", screen_id)
        self._ensure_scope(screen, screen_id, external_account_id, mode, "screen")
        return screen

    def update_screen(
        self,
        screen_id: str,
        request: UpdateResearchScreenRequest,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> ResearchScreen:
        screen = self.get_screen(
            screen_id,
            external_account_id=external_account_id,
            mode=mode,
        )
        update = request.model_dump(exclude_unset=True)
        updated = screen.model_copy(update={**update, "updated_at": self._timestamp()})
        return self.repository.update_screen(updated)

    def copy_screen(
        self,
        screen_id: str,
        request: CopyResearchScreenRequest | None = None,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> ResearchScreen:
        source = self.get_screen(
            screen_id,
            external_account_id=external_account_id,
            mode=mode,
        )
        request = request or CopyResearchScreenRequest()
        target_account = request.external_account_id or source.external_account_id
        target_mode = request.mode or source.mode
        self._ensure_account(target_account)
        name = request.name or f"{source.name} copy"
        copied = ResearchScreen(
            external_account_id=target_account,
            mode=target_mode,
            name=name,
            description=source.description,
            configuration=dict(source.configuration),
            symbols=list(source.symbols),
            created_at=self._timestamp(),
            updated_at=self._timestamp(),
        )
        return self.repository.create_screen(copied)

    def capture_case(
        self,
        request: ResearchCaseCaptureRequest,
        *,
        snapshot: ResearchSnapshot | Any | None = None,
    ) -> ResearchCase:
        """Capture one case from the existing read service.

        ``snapshot`` is an internal injection seam for tests and offline
        verification.  The HTTP route never accepts it from the client.  The
        normal path calls ``snapshot_provider`` only for this explicit POST.
        """

        screen = self.repository.get_screen(request.screen_id)
        if screen is None:
            raise ResearchRecordNotFoundError("screen", request.screen_id)
        account_id = request.external_account_id or screen.external_account_id
        mode = request.mode or screen.mode
        self._ensure_scope(screen, request.screen_id, account_id, mode, "screen")
        self._ensure_account(account_id)
        capture_screen = screen
        if request.configuration is not None or request.symbols is not None:
            capture_screen = screen.model_copy(
                update={
                    **(
                        {"configuration": dict(request.configuration)}
                        if request.configuration is not None
                        else {}
                    ),
                    **({"symbols": list(request.symbols)} if request.symbols is not None else {}),
                }
            )
        self._validate_references(
            request.proposal_ids,
            request.advisor_run_ids,
            external_account_id=account_id,
            mode=mode,
        )

        if snapshot is None:
            if self.snapshot_provider is None:
                raise ResearchCaptureUnavailableError(
                    "A research read-service snapshot provider is not configured."
                )
            snapshot = self.snapshot_provider(
                screen=capture_screen,
                external_account_id=account_id,
                mode=mode,
            )
        frozen = self._coerce_snapshot(snapshot, screen=capture_screen)
        case = ResearchCase(
            screen_id=screen.id,
            external_account_id=account_id,
            mode=mode,
            title=request.title,
            notes=request.notes,
            next_action=request.next_action,
            configuration=dict(frozen.configuration),
            universe=frozen.universe,
            symbols=list(frozen.symbols),
            primary_symbol=frozen.primary_symbol,
            as_of=frozen.as_of,
            data_quality=frozen.data_quality,
            warnings=list(frozen.warnings),
            source=frozen.source,
            proposal_ids=list(request.proposal_ids),
            advisor_run_ids=list(request.advisor_run_ids),
            created_at=self._timestamp(),
        )
        return self.repository.create_case(case)

    def list_cases(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
        screen_id: str | None = None,
        symbol: str | None = None,
    ) -> list[ResearchCase]:
        return self.repository.list_cases(
            external_account_id=external_account_id,
            mode=mode,
            screen_id=screen_id,
            symbol=symbol,
        )

    def list_screens_page(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResearchScreenPage:
        return self.repository.list_screens_page(
            external_account_id=external_account_id,
            mode=mode,
            limit=limit,
            cursor=cursor,
        )

    def list_cases_page(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        screen_id: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResearchCasePage:
        return self.repository.list_cases_page(
            external_account_id=external_account_id,
            mode=mode,
            screen_id=screen_id,
            symbol=symbol,
            limit=limit,
            cursor=cursor,
        )

    def get_case(
        self,
        case_id: str,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> ResearchCase:
        case = self.repository.get_case(case_id)
        if case is None:
            raise ResearchRecordNotFoundError("case", case_id)
        self._ensure_scope(case, case_id, external_account_id, mode, "case")
        return case

    def get_event_timeline(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        start: datetime | None = None,
        end: datetime | None = None,
        symbols: Collection[str] | None = None,
    ) -> ResearchTimelineResponse:
        end_value = self._timestamp() if end is None else self._aware(end)
        start_value = end_value - timedelta(days=30) if start is None else self._aware(start)
        self._validate_timeline_window(start_value, end_value)
        normalized_symbols = sorted(
            {
                symbol.strip().upper()
                for symbol in (symbols or [])
                if symbol and symbol.strip()
            }
        )

        events: list[Any] = []
        if self.market_events is not None:
            events = self.market_events.list_events(
                symbols=normalized_symbols or None,
                start=start_value,
                end=end_value,
                limit=None,
            )

        links: list[ResearchTimelinePreOpenLink] = []
        if self.pre_open_runs is not None and mode is ExecutionMode.PAPER:
            # ``limit=None`` is supported by the SQLAlchemy adapter and is
            # intentional: timeline reads must not silently drop older links.
            runs = self.pre_open_runs.list_runs(
                external_account_id=external_account_id,
                limit=None,
            )
            for run in runs:
                if not self._run_in_range(run, start_value, end_value):
                    continue
                if normalized_symbols and not self._run_matches_symbols(run, normalized_symbols):
                    continue
                analyzed_at = self._aware(run.assessment.analyzed_at)
                links.append(
                    ResearchTimelinePreOpenLink(
                        run_id=run.id,
                        external_account_id=run.external_account_id,
                        target_session_date=run.target_session_date,
                        scheduled_at=analyzed_at,
                        preferred_vehicle=run.assessment.preferred_vehicle,
                        summary=run.assessment.summary,
                        review_status=run.review_status,
                    )
                )

        items: list[ResearchTimelineItem] = []
        for event in events:
            items.append(
                ResearchTimelineItem(
                    kind="market_event",
                    scheduled_at=self._aware(event.scheduled_at),
                    symbol=event.symbol,
                    title=event.title,
                    source=event.source,
                    severity=event.severity,
                    event_type=event.event_type,
                    event_id=event.id,
                    payload=event.model_dump(mode="json"),
                )
            )
        for link in links:
            items.append(
                ResearchTimelineItem(
                    kind="pre_open",
                    scheduled_at=link.scheduled_at,
                    symbol=link.preferred_vehicle,
                    title=link.summary or "Pre-open research capture",
                    source=link.source,
                    pre_open_run_id=link.run_id,
                    payload=link.model_dump(mode="json"),
                )
            )
        items.sort(key=lambda item: (item.scheduled_at, item.kind, item.event_id or item.pre_open_run_id or ""))
        return ResearchTimelineResponse(
            external_account_id=external_account_id,
            mode=mode,
            start=start_value,
            end=end_value,
            symbols=normalized_symbols,
            events=events,
            pre_open_links=links,
            items=items,
        )

    def get_event_timeline_page(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        start: datetime | None = None,
        end: datetime | None = None,
        symbols: Collection[str] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResearchTimelinePage:
        """Return a bounded, keyset-like page of timeline items.

        Production repositories may expose specialized page methods.  The
        fallback still passes a bounded ``limit + 1`` to each source and never
        uses the old unlimited timeline read.
        """

        page_limit = normalize_page_limit(limit)
        end_value = self._timestamp() if end is None else self._aware(end)
        start_value = end_value - timedelta(days=30) if start is None else self._aware(start)
        self._validate_timeline_window(start_value, end_value)
        normalized_symbols = sorted(
            {
                symbol.strip().upper()
                for symbol in (symbols or [])
                if symbol and symbol.strip()
            }
        )
        scope = {
            "external_account_id": external_account_id,
            "mode": mode.value,
            "start": start_value.isoformat(),
            "end": end_value.isoformat(),
            "symbols": normalized_symbols,
        }
        position = decode_cursor(cursor, resource="research-timeline", scope=scope) if cursor else None
        cursor_key = self._timeline_cursor_key(position)

        events: list[Any] = []
        if self.market_events is not None:
            page_method = getattr(self.market_events, "list_events_page", None)
            if page_method is not None:
                events = list(
                    page_method(
                        symbols=normalized_symbols or None,
                        start=start_value,
                        end=end_value,
                        cursor_scheduled_at=cursor_key[0] if cursor_key else None,
                        cursor_id=cursor_key[2] if cursor_key and cursor_key[1] == "market_event" else None,
                        limit=page_limit + 1,
                    ).items
                )
            else:
                source_start = cursor_key[0] if cursor_key else start_value
                events = list(
                    self.market_events.list_events(
                        symbols=normalized_symbols or None,
                        start=source_start,
                        end=end_value,
                        limit=page_limit + 1,
                    )
                )

        runs: list[PreOpenAssessmentRun] = []
        if self.pre_open_runs is not None and mode is ExecutionMode.PAPER:
            runs = list(
                self.pre_open_runs.list_runs(
                    external_account_id=external_account_id,
                    limit=page_limit + 1,
                )
            )

        items: list[ResearchTimelineItem] = []
        for event in events:
            item = ResearchTimelineItem(
                kind="market_event",
                scheduled_at=self._aware(event.scheduled_at),
                symbol=event.symbol,
                title=event.title,
                source=event.source,
                severity=event.severity,
                event_type=event.event_type,
                event_id=event.id,
                payload=event.model_dump(mode="json"),
            )
            if cursor_key and self._timeline_item_key(item) <= cursor_key:
                continue
            items.append(item)
        links: list[ResearchTimelinePreOpenLink] = []
        for run in runs:
            if not self._run_in_range(run, start_value, end_value):
                continue
            if normalized_symbols and not self._run_matches_symbols(run, normalized_symbols):
                continue
            analyzed_at = self._aware(run.assessment.analyzed_at)
            link = ResearchTimelinePreOpenLink(
                run_id=run.id,
                external_account_id=run.external_account_id,
                target_session_date=run.target_session_date,
                scheduled_at=analyzed_at,
                preferred_vehicle=run.assessment.preferred_vehicle,
                summary=run.assessment.summary,
                review_status=run.review_status,
            )
            item = ResearchTimelineItem(
                kind="pre_open",
                scheduled_at=link.scheduled_at,
                symbol=link.preferred_vehicle,
                title=link.summary or "Pre-open research capture",
                source=link.source,
                pre_open_run_id=link.run_id,
                payload=link.model_dump(mode="json"),
            )
            if cursor_key and self._timeline_item_key(item) <= cursor_key:
                continue
            items.append(item)
            links.append(link)

        items.sort(key=self._timeline_item_key)
        has_more = len(items) > page_limit
        page_items = items[:page_limit]
        next_cursor = None
        if has_more and page_items:
            last = page_items[-1]
            next_cursor = encode_cursor(
                resource="research-timeline",
                scope=scope,
                position={
                    "scheduled_at": last.scheduled_at.isoformat(),
                    "kind": last.kind,
                    "id": last.event_id or last.pre_open_run_id or "",
                },
            )
        page_event_ids = {item.event_id for item in page_items if item.event_id}
        page_run_ids = {item.pre_open_run_id for item in page_items if item.pre_open_run_id}
        return ResearchTimelinePage(
            external_account_id=external_account_id,
            mode=mode,
            start=start_value,
            end=end_value,
            symbols=normalized_symbols,
            events=[event for event in events if event.id in page_event_ids],
            pre_open_links=[link for link in links if link.run_id in page_run_ids],
            items=page_items,
            next_cursor=next_cursor,
            has_more=has_more,
            limit=page_limit,
        )

    def _ensure_account(self, external_account_id: str) -> None:
        checker = getattr(self.repository, "account_exists", None)
        if checker is not None and not checker(external_account_id):
            raise ResearchAccountNotFoundError(external_account_id)

    @staticmethod
    def _ensure_scope(
        record: ResearchScreen | ResearchCase,
        record_id: str,
        external_account_id: str | None,
        mode: ExecutionMode,
        record_type: str,
    ) -> None:
        if external_account_id is not None and record.external_account_id != external_account_id:
            raise ResearchScopeError(record_type, record_id, external_account_id, mode)
        if record.mode != mode:
            raise ResearchScopeError(record_type, record_id, external_account_id or record.external_account_id, mode)

    def _validate_references(
        self,
        proposal_ids: Collection[str],
        advisor_run_ids: Collection[str],
        *,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> None:
        missing_proposals = self._missing_reference_ids(
            "missing_proposal_ids", proposal_ids, external_account_id=external_account_id, mode=mode
        )
        if missing_proposals:
            raise ResearchReferenceError("proposal", missing_proposals)
        missing_runs = self._missing_reference_ids(
            "missing_advisor_run_ids", advisor_run_ids, external_account_id=external_account_id, mode=mode
        )
        if missing_runs:
            raise ResearchReferenceError("advisor run", missing_runs)

    def _missing_reference_ids(
        self,
        method_name: str,
        values: Collection[str],
        *,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> list[str]:
        checker = getattr(self.repository, method_name, None)
        if checker is None:
            return []
        return list(
            checker(
                values,
                external_account_id=external_account_id,
                mode=mode,
            )
        )

    @staticmethod
    def _coerce_snapshot(raw: ResearchSnapshot | Any, *, screen: ResearchScreen) -> ResearchSnapshot:
        if isinstance(raw, ResearchSnapshot):
            return raw
        if hasattr(raw, "model_dump"):
            payload = raw.model_dump(mode="json")
        elif isinstance(raw, dict):
            payload = dict(raw)
        else:
            raise ResearchCaptureUnavailableError("The research read service returned an unsupported snapshot.")

        if "symbols" not in payload:
            rows = payload.get("rows") or []
            payload["symbols"] = [row.get("symbol") for row in rows if isinstance(row, dict) and row.get("symbol")]
        payload.setdefault("configuration", dict(screen.configuration))
        payload.setdefault("universe", payload.copy())
        payload.setdefault("as_of", payload.get("generated_at"))
        payload.setdefault("data_quality", "unknown")
        payload.setdefault("warnings", [])
        payload.setdefault("source", "research_workspace")
        return ResearchSnapshot.model_validate(payload)

    @staticmethod
    def _run_in_range(run: PreOpenAssessmentRun, start: datetime, end: datetime) -> bool:
        timestamp = ResearchRecordsService._aware(run.assessment.analyzed_at)
        return start <= timestamp <= end

    @staticmethod
    def _run_matches_symbols(run: PreOpenAssessmentRun, symbols: Collection[str]) -> bool:
        selected = set(symbols)
        if run.assessment.preferred_vehicle and run.assessment.preferred_vehicle.upper() in selected:
            return True
        return any(signal.symbol.upper() in selected for signal in run.assessment.signals)

    @staticmethod
    def _validate_timeline_window(start: datetime, end: datetime) -> None:
        if start > end:
            raise ValueError("timeline start must be before or equal to end")
        if end - start > timedelta(days=366):
            raise ValueError("timeline range cannot exceed 366 days")

    @staticmethod
    def _timeline_cursor_key(position: dict[str, object] | None):
        if position is None:
            return None
        timestamp = position.get("scheduled_at")
        kind = position.get("kind")
        record_id = position.get("id")
        if not isinstance(timestamp, str) or not isinstance(kind, str) or not isinstance(record_id, str):
            raise CursorError("Invalid pagination cursor position.")
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise CursorError("Invalid pagination cursor position.") from exc
        return (parsed, kind, record_id)

    @staticmethod
    def _timeline_item_key(item: ResearchTimelineItem):
        return (
            item.scheduled_at,
            item.kind,
            item.event_id or item.pre_open_run_id or "",
        )

    def _timestamp(self) -> datetime:
        return self._aware(self._now())

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


# Singular alias keeps dependency names readable for callers that prefer the
# route's ``research_record_service`` wording.
ResearchRecordService = ResearchRecordsService
