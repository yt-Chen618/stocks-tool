from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from stocks_tool.application.services.research_records import ResearchRecordsService
from stocks_tool.db.base import Base
from stocks_tool.db.research_models import ResearchCaseRecord, ResearchScreenRecord
from stocks_tool.domain.enums import ExecutionMode, MarketEventSeverity, MarketEventType
from stocks_tool.domain.models import (
    MarketEvent,
    ResearchHistoryResponse,
    ResearchTechnicalSnapshot,
    ResearchTechnicalsResponse,
    ResearchUniverseResponse,
    ResearchUniverseRow,
)
from stocks_tool.domain.research_records import (
    CreateResearchScreenRequest,
    ResearchAccountNotFoundError,
    ResearchCase,
    ResearchCaseCaptureRequest,
    ResearchCaptureConfigurationError,
    ResearchReferenceError,
    ResearchScreen,
    ResearchScopeError,
    ResearchSnapshot,
    UpdateResearchScreenRequest,
)
from stocks_tool.api.routes.research_records import _workspace_snapshot_provider
from stocks_tool.application.services.research_workspace import ResearchWatchlistNotFoundError
from stocks_tool.repositories.sqlalchemy_research_repository import SQLAlchemyResearchRepository


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class FakeResearchRepository:
    def __init__(self) -> None:
        self.accounts = {"LBPT10087357", "other-account"}
        self.screens = {}
        self.cases = {}
        self.proposals = {("LBPT10087357", "paper", "proposal-1")}
        self.advisor_runs = {("LBPT10087357", "paper", "advisor-1")}

    def account_exists(self, external_account_id: str) -> bool:
        return external_account_id in self.accounts

    def create_screen(self, screen):
        self.screens[screen.id] = screen
        return screen

    def list_screens(self, *, external_account_id=None, mode=None):
        return [
            screen
            for screen in self.screens.values()
            if (external_account_id is None or screen.external_account_id == external_account_id)
            and (mode is None or screen.mode == mode)
        ]

    def get_screen(self, screen_id):
        return self.screens.get(screen_id)

    def update_screen(self, screen):
        self.screens[screen.id] = screen
        return screen

    def create_case(self, case):
        self.cases[case.id] = case
        return case

    def list_cases(self, *, external_account_id=None, mode=None, screen_id=None, symbol=None):
        return [
            case
            for case in self.cases.values()
            if (external_account_id is None or case.external_account_id == external_account_id)
            and (mode is None or case.mode == mode)
            and (screen_id is None or case.screen_id == screen_id)
            and (symbol is None or symbol.upper() in case.symbols)
        ]

    def get_case(self, case_id):
        return self.cases.get(case_id)

    def missing_proposal_ids(self, values, *, external_account_id, mode):
        return [
            value
            for value in values
            if (external_account_id, mode.value, value) not in self.proposals
        ]

    def missing_advisor_run_ids(self, values, *, external_account_id, mode):
        return [
            value
            for value in values
            if (external_account_id, mode.value, value) not in self.advisor_runs
        ]


class FakeEvents:
    def __init__(self, events):
        self.events = events
        self.request = None

    def list_events(self, **kwargs):
        self.request = kwargs
        return self.events


class FakePreOpenRuns:
    def __init__(self, runs):
        self.runs = runs
        self.request = None

    def list_runs(self, **kwargs):
        self.request = kwargs
        return self.runs


def _service(*, events=None, runs=None, provider=None):
    repository = FakeResearchRepository()
    service = ResearchRecordsService(
        repository=repository,
        market_events=FakeEvents(events or []),
        pre_open_runs=FakePreOpenRuns(runs or []),
        snapshot_provider=provider,
        now=lambda: NOW,
    )
    return service, repository


def _screen(service: ResearchRecordsService):
    return service.create_screen(
        CreateResearchScreenRequest(
            name="Core semis",
            description="Readable setup",
            configuration={"watchlist_id": "watch-1", "threshold": 0.2},
            symbols=[" qqq.us ", "smh.us", "QQQ.US"],
        )
    )


def test_screen_crud_normalizes_symbols_and_keeps_account_mode_scope() -> None:
    service, repository = _service()
    screen = _screen(service)

    assert screen.external_account_id == "LBPT10087357"
    assert screen.mode is ExecutionMode.PAPER
    assert screen.symbols == ["QQQ.US", "SMH.US"]

    updated = service.update_screen(
        screen.id,
        UpdateResearchScreenRequest(name="Core semis updated", symbols=["aapl.us"]),
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )
    assert updated.name == "Core semis updated"
    assert updated.symbols == ["AAPL.US"]

    copied = service.copy_screen(screen.id, external_account_id="LBPT10087357", mode=ExecutionMode.PAPER)
    assert copied.id != screen.id
    assert copied.configuration == screen.configuration

    with pytest.raises(ResearchScopeError):
        service.get_screen(screen.id, external_account_id="other-account", mode=ExecutionMode.PAPER)
    assert len(repository.screens) == 2


def test_screen_creation_requires_a_known_local_account() -> None:
    service, _ = _service()
    with pytest.raises(ResearchAccountNotFoundError):
        service.create_screen(
            CreateResearchScreenRequest(external_account_id="missing-account", name="No account")
        )


def test_capture_calls_server_provider_only_on_explicit_capture_and_freezes_payload() -> None:
    provider_calls = []

    def provider(*, screen, external_account_id, mode):
        provider_calls.append((screen.id, external_account_id, mode))
        return ResearchSnapshot(
            configuration={"threshold": 0.25},
            universe={"rows": [{"symbol": "QQQ.US", "last_done": "500"}]},
            symbols=["qqq.us"],
            as_of=NOW,
            data_quality="live",
            warnings=["quotes delayed"],
            source="research_workspace",
        )

    service, repository = _service(provider=provider)
    screen = _screen(service)
    assert provider_calls == []
    assert service.list_screens(external_account_id="LBPT10087357")
    assert provider_calls == []

    case = service.capture_case(
        ResearchCaseCaptureRequest(
            screen_id=screen.id,
            title="QQQ review",
            notes="Keep the explanation beside the chart.",
            next_action="Review downside before opening.",
            proposal_ids=["proposal-1"],
            advisor_run_ids=["advisor-1"],
        )
    )
    assert len(provider_calls) == 1
    assert case.title == "QQQ review"
    assert case.symbols == ["QQQ.US"]
    assert case.configuration == {"threshold": 0.25}
    assert case.warnings == ["quotes delayed"]
    assert repository.cases[case.id].universe["rows"][0]["last_done"] == "500"

    # Updating the screen after capture cannot rewrite the immutable snapshot.
    service.update_screen(screen.id, UpdateResearchScreenRequest(configuration={"threshold": 0.9}))
    stored = service.get_case(case.id)
    assert stored.configuration == {"threshold": 0.25}


def test_capture_rejects_out_of_scope_references_before_provider_call() -> None:
    provider = lambda **kwargs: pytest.fail("provider must not be called")
    service, _ = _service(provider=provider)
    screen = _screen(service)
    with pytest.raises(ResearchReferenceError) as exc_info:
        service.capture_case(
            ResearchCaseCaptureRequest(screen_id=screen.id, proposal_ids=["foreign-proposal"])
        )
    assert exc_info.value.missing_ids == ["foreign-proposal"]


def _pre_open_run(symbol: str = "QQQ.US"):
    assessment = SimpleNamespace(
        analyzed_at=NOW - timedelta(days=1),
        preferred_vehicle=symbol,
        summary="Pre-open board summary",
        signals=[SimpleNamespace(symbol=symbol)],
    )
    return SimpleNamespace(
        id="pre-open-1",
        external_account_id="LBPT10087357",
        target_session_date=date(2026, 10, 3),
        assessment=assessment,
        review_status="awaiting_open",
    )


def test_timeline_returns_all_events_and_pre_open_links_without_display_cap() -> None:
    events = [
        MarketEvent(
            id=f"event-{index}",
            symbol="QQQ.US" if index % 2 == 0 else None,
            event_type=MarketEventType.OTHER,
            title=f"Event {index}",
            scheduled_at=NOW - timedelta(hours=index),
            source="fixture",
            severity=MarketEventSeverity.MEDIUM,
        )
        for index in range(8)
    ]
    fake_events = FakeEvents(events)
    fake_runs = FakePreOpenRuns([_pre_open_run()])
    repository = FakeResearchRepository()
    service = ResearchRecordsService(
        repository=repository,
        market_events=fake_events,
        pre_open_runs=fake_runs,
        now=lambda: NOW,
    )

    response = service.get_event_timeline(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        start=NOW - timedelta(days=2),
        end=NOW,
        symbols=["qqq.us"],
    )

    assert len(response.events) == 8
    assert len(response.pre_open_links) == 1
    assert len(response.items) == 9
    assert fake_events.request["limit"] is None
    assert fake_runs.request["limit"] is None
    assert fake_events.request["symbols"] == ["QQQ.US"]


def test_timeline_page_is_bounded_and_rejects_windows_over_one_year() -> None:
    events = [
        MarketEvent(
            id=f"page-event-{index}",
            symbol="QQQ.US",
            event_type=MarketEventType.OTHER,
            title=f"Event {index}",
            scheduled_at=NOW - timedelta(hours=index),
            source="fixture",
            severity=MarketEventSeverity.MEDIUM,
        )
        for index in range(8)
    ]
    fake_events = FakeEvents(events)
    service = ResearchRecordsService(
        repository=FakeResearchRepository(),
        market_events=fake_events,
        now=lambda: NOW,
    )
    page = service.get_event_timeline_page(
        external_account_id="LBPT10087357",
        start=NOW - timedelta(days=2),
        end=NOW,
        symbols=["QQQ.US"],
        limit=3,
    )
    assert len(page.items) == 3
    assert page.has_more is True
    assert fake_events.request["limit"] == 4

    with pytest.raises(ValueError, match="366 days"):
        service.get_event_timeline_page(
            external_account_id="LBPT10087357",
            start=NOW - timedelta(days=367),
            end=NOW,
            limit=3,
        )


def test_sqlalchemy_research_repository_round_trips_json_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[ResearchScreenRecord.__table__, ResearchCaseRecord.__table__],
    )
    with Session(engine) as session:
        repository = SQLAlchemyResearchRepository(session)
        screen = repository.create_screen(
            ResearchScreen(
                name="SQLite screen",
                configuration={"watchlist_id": "watch-1"},
                symbols=["QQQ.US"],
                created_at=NOW,
                updated_at=NOW,
            )
        )
        assert screen.configuration["watchlist_id"] == "watch-1"
        case = repository.create_case(
            ResearchCase(
                screen_id=screen.id,
                title="SQLite case",
                configuration={"threshold": 0.2},
                universe={"rows": [{"symbol": "QQQ.US"}]},
                symbols=["QQQ.US"],
                as_of=NOW,
                created_at=NOW,
            )
        )
        assert repository.get_case(case.id).universe["rows"][0]["symbol"] == "QQQ.US"


def test_capture_provider_uses_canonical_selected_symbol_and_history_range() -> None:
    class Workspace:
        def __init__(self):
            self.calls = []

        def get_universe(self, **kwargs):
            self.calls.append(("universe", kwargs))
            return ResearchUniverseResponse(
                mode=ExecutionMode.PAPER,
                generated_at=NOW,
                data_quality="live",
                rows=[ResearchUniverseRow(symbol="QQQ.US"), ResearchUniverseRow(symbol="AAPL.US")],
            )

        def get_technicals(self, **kwargs):
            self.calls.append(("technicals", kwargs))
            return ResearchTechnicalsResponse(
                mode=ExecutionMode.PAPER,
                results=[ResearchTechnicalSnapshot(symbol="AAPL.US", status="ok")],
            )

        def get_history(self, **kwargs):
            self.calls.append(("history", kwargs))
            return ResearchHistoryResponse(symbol="AAPL.US", range="1y", mode=ExecutionMode.PAPER)

    workspace = Workspace()
    provider = _workspace_snapshot_provider(workspace)
    screen = ResearchScreen(
        name="Saved",
        symbols=["QQQ.US", "AAPL.US"],
        configuration={
            "filters": {"min_return_20": 5},
            "selected_symbol": "AAPL.US",
            "history_range": "1y",
        },
    )
    snapshot = provider(
        screen=screen,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    assert snapshot["primary_symbol"] == "AAPL.US"
    assert snapshot["configuration"]["filters"] == {"min_return_20": 5}
    assert snapshot["universe"]["technical_coverage"]["requested_symbols"] == ["AAPL.US"]
    assert snapshot["universe"]["technical_coverage"]["complete"] is False
    technical_call = next(call for call in workspace.calls if call[0] == "technicals")
    history_call = next(call for call in workspace.calls if call[0] == "history")
    assert technical_call[1]["symbols"] == ["AAPL.US"]
    assert history_call[1]["symbol"] == "AAPL.US"
    assert history_call[1]["range_name"] == "1y"
    assert "technical_coverage_primary_only" in snapshot["warnings"]


def test_capture_provider_rejects_invalid_current_configuration_and_dependency_errors() -> None:
    class Workspace:
        def get_universe(self, **kwargs):
            raise ResearchWatchlistNotFoundError("missing-watchlist")

    provider = _workspace_snapshot_provider(Workspace())
    with pytest.raises(ResearchCaptureConfigurationError):
        provider(
            screen=ResearchScreen(
                name="No selection",
                symbols=["QQQ.US"],
                configuration={"history_range": "1y"},
            ),
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
        )

    with pytest.raises(ResearchCaptureConfigurationError):
        provider(
            screen=ResearchScreen(
                name="Bad range",
                symbols=["QQQ.US"],
                configuration={"selected_symbol": "QQQ.US", "history_range": "10y"},
            ),
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
        )

    class InvalidWatchlistWorkspace:
        def get_universe(self, **kwargs):
            raise ResearchWatchlistNotFoundError("missing-watchlist")

    with pytest.raises(ResearchWatchlistNotFoundError):
        _workspace_snapshot_provider(InvalidWatchlistWorkspace())(
            screen=ResearchScreen(
                name="Bad watchlist",
                symbols=["QQQ.US"],
                configuration={"selected_symbol": "QQQ.US", "history_range": "3m"},
            ),
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
        )

    class UniverseWithoutSelectedWorkspace:
        def get_universe(self, **kwargs):
            return ResearchUniverseResponse(
                mode=ExecutionMode.PAPER,
                generated_at=NOW,
                data_quality="live",
                rows=[ResearchUniverseRow(symbol="QQQ.US")],
            )

    with pytest.raises(ResearchCaptureConfigurationError, match="captured research universe"):
        _workspace_snapshot_provider(UniverseWithoutSelectedWorkspace())(
            screen=ResearchScreen(
                name="Unknown symbol",
                symbols=["AAPL.US"],
                configuration={"selected_symbol": "AAPL.US", "history_range": "3m"},
            ),
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
        )


def test_research_repository_pages_are_bounded_and_symbol_filtered_in_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[ResearchScreenRecord.__table__, ResearchCaseRecord.__table__],
    )
    with Session(engine) as session:
        repository = SQLAlchemyResearchRepository(session)
        for index in range(3):
            now = NOW + timedelta(seconds=index)
            repository.create_screen(
                ResearchScreen(
                    name=f"Screen {index}",
                    symbols=["QQQ.US"],
                    created_at=now,
                    updated_at=now,
                )
            )
        first = repository.list_screens_page(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            limit=2,
        )
        assert len(first.items) == 2
        assert first.has_more is True
        second = repository.list_screens_page(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            limit=2,
            cursor=first.next_cursor,
        )
        assert len(second.items) == 1
        assert second.has_more is False

        screen = first.items[0]
        repository.create_case(
            ResearchCase(
                screen_id=screen.id,
                symbols=["QQQ.US"],
                primary_symbol="QQQ.US",
                universe={},
                as_of=NOW,
                created_at=NOW,
            )
        )
        repository.create_case(
            ResearchCase(
                screen_id=screen.id,
                symbols=["AAPL.US"],
                primary_symbol="AAPL.US",
                universe={},
                as_of=NOW,
                created_at=NOW,
            )
        )
        qqq_page = repository.list_cases_page(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            symbol="qqq.us",
            limit=1,
        )
        assert [case.primary_symbol for case in qqq_page.items] == ["QQQ.US"]
