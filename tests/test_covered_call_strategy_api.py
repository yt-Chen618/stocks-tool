from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_covered_call_strategy_service
from stocks_tool.domain.enums import ExecutionMode, RiskStatus
from stocks_tool.domain.models import (
    CoveredCallCandidate,
    CoveredCallPreviewResult,
    CoveredCallProposalResult,
    CoveredCallRiskSummary,
    StrategyProposal,
)
from stocks_tool.main import app


NOW = datetime(2026, 5, 29, 15, 0, tzinfo=timezone.utc)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def with_covered_call_service(service: Mock) -> TestClient:
    app.dependency_overrides[get_covered_call_strategy_service] = lambda: service
    return TestClient(app)


def build_preview() -> CoveredCallPreviewResult:
    candidate = CoveredCallCandidate(
        underlying_symbol="UNH.US",
        expiration_date=date(2026, 6, 26),
        days_to_expiration=28,
        contracts=1,
        covered_shares=100,
        share_quantity=Decimal("100"),
        average_cost=Decimal("90"),
        underlying_price=Decimal("100"),
        call_symbol="UNH260626C105000.US",
        call_strike=Decimal("105"),
        call_bid=Decimal("1.20"),
        call_ask=Decimal("1.30"),
        call_mid=Decimal("1.25"),
        premium_income=Decimal("120.00"),
        delta=Decimal("0.30"),
        open_interest=800,
        volume=25,
        quote_timestamp=NOW,
    )
    return CoveredCallPreviewResult(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        evaluated_at=NOW,
        eligible=True,
        symbol="UNH.US",
        selected_expiration_date=date(2026, 6, 26),
        days_to_expiration=28,
        candidate=candidate,
        risk=CoveredCallRiskSummary(
            status=RiskStatus.PASS,
            max_income=Decimal("120.00"),
            max_assignment_profit=Decimal("1620.00"),
            max_loss_if_zero=Decimal("8880.00"),
            break_even=Decimal("88.80"),
        ),
    )


def test_covered_call_preview_route_returns_candidate() -> None:
    service = Mock()
    service.preview.return_value = build_preview()

    client = with_covered_call_service(service)
    try:
        response = client.get(
            "/strategies/covered-call/preview",
            params={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "mode": "paper",
                "as_of": "2026-05-29T15:00:00Z",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["eligible"] is True
    assert body["candidate"]["call_symbol"] == "UNH260626C105000.US"
    request = service.preview.call_args.kwargs
    assert request["external_account_id"] == "LBPT10087357"
    assert request["symbol"] == "UNH.US"


def test_covered_call_propose_route_returns_ledger_proposal() -> None:
    service = Mock()
    preview = build_preview()
    service.create_proposal.return_value = CoveredCallProposalResult(
        preview=preview,
        proposal=StrategyProposal(
            id="proposal-1",
            strategy_id="covered_call_v1",
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            symbol="UNH.US",
            title="Sell covered call on UNH.US",
            proposed_action="sell_covered_call",
            rationale="Sell 1 call against 100 existing shares.",
            expected_max_profit=Decimal("1620.00"),
            created_at=NOW,
            updated_at=NOW,
        ),
    )

    client = with_covered_call_service(service)
    try:
        response = client.post(
            "/strategies/covered-call/propose",
            params={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["strategy_id"] == "covered_call_v1"
    assert body["proposal"]["proposed_action"] == "sell_covered_call"
    request = service.create_proposal.call_args.kwargs
    assert request["external_account_id"] == "LBPT10087357"
