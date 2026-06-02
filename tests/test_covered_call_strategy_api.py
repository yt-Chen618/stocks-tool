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
    CoveredCallCloseResult,
    CoveredCallMonitorResult,
    CoveredCallPreviewResult,
    CoveredCallProposalResult,
    CoveredCallRollExecutionResult,
    CoveredCallRollProposalResult,
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


def test_covered_call_roll_propose_route_returns_roll_proposal() -> None:
    service = Mock()
    preview = build_preview()
    roll_candidate = preview.candidate.model_copy(
        update={
            "expiration_date": date(2026, 7, 10),
            "days_to_expiration": 42,
            "call_symbol": "UNH260710C110000.US",
            "call_strike": Decimal("110"),
            "call_bid": Decimal("1.10"),
            "call_ask": Decimal("1.20"),
            "call_mid": Decimal("1.15"),
            "premium_income": Decimal("110.00"),
        }
    )
    next_preview = preview.model_copy(
        update={
            "selected_expiration_date": date(2026, 7, 10),
            "days_to_expiration": 42,
            "candidate": roll_candidate,
        }
    )
    proposal = StrategyProposal(
        id="proposal-2",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Roll covered call on UNH.US",
        proposed_action="roll_covered_call",
        rationale="Buy back the current call and sell a later call.",
        status=StrategyProposalStatus.PENDING,
        created_at=NOW,
        updated_at=NOW,
    )
    service.create_roll_proposal.return_value = CoveredCallRollProposalResult(
        current_monitor=CoveredCallMonitorResult(
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
        ),
        next_preview=next_preview,
        proposal=proposal,
    )

    client = with_covered_call_service(service)
    try:
        response = client.post(
            "/strategies/covered-call/proposals/proposal-1/roll-propose",
            json={
                "as_of": "2026-05-29T15:00:00Z",
                "min_new_expiration_date": "2026-07-01",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["proposed_action"] == "roll_covered_call"
    assert body["next_preview"]["candidate"]["call_symbol"] == "UNH260710C110000.US"
    request = service.create_roll_proposal.call_args.args[1]
    assert service.create_roll_proposal.call_args.args[0] == "proposal-1"
    assert request.min_new_expiration_date == date(2026, 7, 1)


def test_covered_call_roll_execute_route_sequences_approved_roll() -> None:
    service = Mock()
    proposal = StrategyProposal(
        id="proposal-2",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Roll covered call on UNH.US",
        proposed_action="roll_covered_call",
        rationale="Approved roll proposal.",
        status=StrategyProposalStatus.EXECUTED,
        created_at=NOW,
        updated_at=NOW,
    )
    service.execute_approved_roll_proposal.return_value = CoveredCallRollExecutionResult(
        proposal=proposal,
        buyback_order=Order(
            id="buyback-order-1",
            broker=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            external_order_id="external-buyback-1",
            symbol="UNH260626C105000.US",
            asset_type=AssetType.OPTION,
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            mode=ExecutionMode.PAPER,
            status=OrderStatus.FILLED,
            limit_price=Decimal("0.55"),
            created_at=NOW,
            updated_at=NOW,
        ),
        sell_order=Order(
            id="roll-open-order-1",
            broker=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            external_order_id="external-roll-open-1",
            symbol="UNH260710C110000.US",
            asset_type=AssetType.OPTION,
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            mode=ExecutionMode.PAPER,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("1.10"),
            created_at=NOW,
            updated_at=NOW,
        ),
        sequence_status="roll_submitted",
        submitted_at=NOW,
    )

    client = with_covered_call_service(service)
    try:
        response = client.post(
            "/strategies/covered-call/proposals/proposal-2/roll-execute",
            json={"buyback_limit_price": "0.55", "sell_limit_price": "1.10"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["sequence_status"] == "roll_submitted"
    assert body["buyback_order"]["side"] == "buy"
    assert body["sell_order"]["side"] == "sell"
    request = service.execute_approved_roll_proposal.call_args.args[1]
    assert service.execute_approved_roll_proposal.call_args.args[0] == "proposal-2"
    assert request.buyback_limit_price == Decimal("0.55")
    assert request.sell_limit_price == Decimal("1.10")


def test_covered_call_roll_continue_route_refreshes_pending_buyback() -> None:
    service = Mock()
    proposal = StrategyProposal(
        id="proposal-2",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Roll covered call on UNH.US",
        proposed_action="roll_covered_call",
        rationale="Approved roll proposal.",
        status=StrategyProposalStatus.APPROVED,
        created_at=NOW,
        updated_at=NOW,
    )
    service.continue_roll_proposal.return_value = CoveredCallRollExecutionResult(
        proposal=proposal,
        buyback_order=Order(
            id="buyback-order-1",
            broker=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            external_order_id="external-buyback-1",
            symbol="UNH260626C105000.US",
            asset_type=AssetType.OPTION,
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            mode=ExecutionMode.PAPER,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("0.55"),
            created_at=NOW,
            updated_at=NOW,
        ),
        sequence_status="buyback_still_working",
        reason="Buyback order is not filled yet; sell-to-open remains held.",
        submitted_at=NOW,
    )

    client = with_covered_call_service(service)
    try:
        response = client.post(
            "/strategies/covered-call/proposals/proposal-2/roll-continue",
            json={
                "buyback_order_id": "buyback-order-1",
                "sell_order_id": "roll-open-order-1",
                "sell_limit_price": "1.10",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["sequence_status"] == "buyback_still_working"
    assert body["sell_order"] is None
    request = service.continue_roll_proposal.call_args.args[1]
    assert service.continue_roll_proposal.call_args.args[0] == "proposal-2"
    assert request.buyback_order_id == "buyback-order-1"
    assert request.sell_order_id == "roll-open-order-1"
    assert request.sell_limit_price == Decimal("1.10")


def test_covered_call_close_route_submits_buyback_order() -> None:
    service = Mock()
    proposal = StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Executed covered call proposal.",
        status=StrategyProposalStatus.EXECUTED,
        created_at=NOW,
        updated_at=NOW,
    )
    service.close_proposal.return_value = CoveredCallCloseResult(
        proposal=proposal,
        order=Order(
            id="order-close-1",
            broker=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            external_order_id="external-close-1",
            symbol="UNH260626C105000.US",
            asset_type=AssetType.OPTION,
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            mode=ExecutionMode.PAPER,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("0.55"),
            created_at=NOW,
            updated_at=NOW,
        ),
        submitted_at=NOW,
    )

    client = with_covered_call_service(service)
    try:
        response = client.post(
            "/strategies/covered-call/proposals/proposal-1/close",
            json={"limit_price": "0.55"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["order"]["side"] == "buy"
    assert body["order"]["limit_price"] == "0.55"
    request = service.close_proposal.call_args.args[1]
    assert request.limit_price == Decimal("0.55")


def test_covered_call_lifecycle_reconcile_route_returns_counts() -> None:
    service = Mock()
    service.reconcile_pending_lifecycle.return_value = {
        "close_orders_refreshed": 0,
        "closed_proposals": 0,
        "sell_orders_refreshed": 1,
        "sell_orders_executed": 0,
        "roll_buyback_orders_refreshed": 0,
        "roll_sell_orders_submitted": 0,
        "roll_sell_orders_refreshed": 0,
        "rolls_executed": 0,
    }

    client = with_covered_call_service(service)
    try:
        response = client.post(
            "/strategies/covered-call/lifecycle/LBPT10087357/reconcile",
            params={"limit": "20"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["sell_orders_refreshed"] == 1
    assert body["sell_orders_executed"] == 0
    service.reconcile_pending_lifecycle.assert_called_once_with(
        external_account_id="LBPT10087357",
        limit=20,
    )
