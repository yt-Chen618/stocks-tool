from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_covered_call_strategy_service
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskStatus,
    StrategyProposalStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    CoveredCallExecutionResult,
    CoveredCallCandidate,
    CoveredCallMonitorResult,
    CoveredCallPreviewResult,
    CoveredCallProposalResult,
    CoveredCallRiskSummary,
    Order,
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


def test_covered_call_execute_route_submits_approved_proposal() -> None:
    service = Mock()
    proposal = StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Approved covered call proposal.",
        status=StrategyProposalStatus.EXECUTED,
        created_at=NOW,
        updated_at=NOW,
    )
    service.execute_approved_proposal.return_value = CoveredCallExecutionResult(
        proposal=proposal,
        order=Order(
            id="order-1",
            broker=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            external_order_id="external-order-1",
            symbol="UNH260626C105000.US",
            asset_type=AssetType.OPTION,
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            mode=ExecutionMode.PAPER,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("1.20"),
            created_at=NOW,
            updated_at=NOW,
        ),
        submitted_at=NOW,
    )

    client = with_covered_call_service(service)
    try:
        response = client.post(
            "/strategies/covered-call/proposals/proposal-1/execute",
            json={"limit_price": "1.20", "remark": "approved-test"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["status"] == "executed"
    assert body["order"]["symbol"] == "UNH260626C105000.US"
    request = service.execute_approved_proposal.call_args.args[1]
    assert request.limit_price == Decimal("1.20")
    assert request.remark == "approved-test"


def test_covered_call_monitor_route_returns_management_guidance() -> None:
    service = Mock()
    preview = build_preview()
    service.monitor_proposal.return_value = CoveredCallMonitorResult(
        proposal_id="proposal-1",
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        evaluated_at=NOW,
        candidate=preview.candidate,
        underlying_price=Decimal("100"),
        call_mark=Decimal("0.55"),
        estimated_buyback_debit=Decimal("55.00"),
        estimated_open_pnl=Decimal("65.00"),
        premium_capture_pct=Decimal("54.17"),
        days_to_expiration=28,
        action="consider_buyback_take_profit",
        reasons=["At least 50% of the original premium is captured."],
    )

    client = with_covered_call_service(service)
    try:
        response = client.post(
            "/strategies/covered-call/proposals/proposal-1/monitor",
            params={"record_signal": "false"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "consider_buyback_take_profit"
    assert body["premium_capture_pct"] == "54.17"
    request = service.monitor_proposal.call_args
    assert request.args[0] == "proposal-1"
    assert request.kwargs["record_signal"] is False
