from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_operator_consistency_service
from stocks_tool.application.services.operator_consistency import OperatorConsistencyService
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    StrategyRunStatus,
    StrategySignalType,
    TimeInForce,
)
from stocks_tool.domain.models import (
    OperatorConsistencyRepairRequest,
    OperatorConsistencyRepairResult,
    OperatorConsistencySummary,
    Order,
    OptionContractRef,
    StrategyRun,
    StrategySignal,
)
from stocks_tool.main import app


NOW = datetime(2026, 6, 16, 15, 59, tzinfo=timezone.utc)


def _zero_dte_manual_scan_order() -> Order:
    return Order(
        id="zero-order-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-zero-order-1",
        client_order_id="client-zero-order-1",
        symbol="QQQ260616P731000.US",
        asset_type=AssetType.OPTION,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        limit_price=Decimal("0.74"),
        option_contract=OptionContractRef(
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 6, 16),
            strike=Decimal("731"),
            right=OptionRight.PUT,
        ),
        raw_payload={
            "submission_request": {
                "remark": "zero_dte_lottery_v1:manual-scan",
                "option_contract": {"underlying_symbol": "QQQ.US"},
            }
        },
        submitted_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _zero_dte_run(order_id: str = "zero-order-1") -> StrategyRun:
    return StrategyRun(
        id="zero-run-1",
        strategy_id="zero_dte_lottery_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        run_type="manual_scan_reconcile",
        status=StrategyRunStatus.EXECUTED,
        symbol="QQQ.US",
        order_id=order_id,
        started_at=NOW,
        completed_at=NOW,
        summary="Reconciled zero-DTE manual-scan paper order QQQ260616P731000.US.",
        created_at=NOW,
        updated_at=NOW,
    )


def _zero_dte_signal(run_id: str = "zero-run-1") -> StrategySignal:
    return StrategySignal(
        id="zero-signal-1",
        strategy_id="zero_dte_lottery_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        signal_type=StrategySignalType.EXECUTION,
        symbol="QQQ.US",
        run_id=run_id,
        strength=Decimal("0.20"),
        summary="Reconciled zero-DTE paper order QQQ260616P731000.US.",
        source="zero_dte_lottery_v1",
        signal_payload={"reconciled_order": {"id": "zero-order-1"}},
        emitted_at=NOW,
        created_at=NOW,
    )


def _consistency_service(
    *,
    runs: list[StrategyRun] | None = None,
    signals: list[StrategySignal] | None = None,
) -> tuple[OperatorConsistencyService, Mock, Mock, Mock]:
    experiments = Mock()
    experiments.list_runs.return_value = runs if runs is not None else []
    experiments.list_signals.return_value = signals if signals is not None else []
    experiments.list_proposals.return_value = []
    bull_put = Mock()
    bull_put.list_spreads.return_value = []
    orders = Mock()
    orders.list_orders.return_value = [_zero_dte_manual_scan_order()]
    orders.get_order.return_value = _zero_dte_manual_scan_order()
    audit_events = Mock()
    return (
        OperatorConsistencyService(
            strategy_experiments=experiments,
            bull_put_strategy=bull_put,
            order_service=orders,
            audit_events=audit_events,
        ),
        experiments,
        orders,
        audit_events,
    )


def test_consistency_report_flags_zero_dte_manual_scan_missing_strategy_records() -> None:
    service, _experiments, _orders, _audit_events = _consistency_service()

    summary = service.get_summary(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        strategy="zero_dte_lottery_v1",
    )

    assert summary.status == "fail"
    assert summary.repair_available_count == 1
    assert summary.checks[0].reason_code == "zero_dte_strategy_recording_missing"
    assert summary.checks[0].repair_id == "zero-dte-ledger:zero-order-1"
    assert summary.checks[0].related_order_ids == ["zero-order-1"]


def test_consistency_repair_creates_local_zero_dte_run_and_signal_only() -> None:
    service, experiments, orders, audit_events = _consistency_service()
    created_run = _zero_dte_run()
    created_signal = _zero_dte_signal()
    experiments.create_run.return_value = created_run
    experiments.create_signal.return_value = created_signal

    result = service.apply_repair(
        "zero-dte-ledger:zero-order-1",
        request=OperatorConsistencyRepairRequest(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            confirm_local_repair=True,
            actor="operator-a",
            note="repair local evidence only",
        ),
    )

    assert result.repaired is True
    assert result.local_repair_executed is True
    assert result.broker_order_submitted is False
    assert result.created_run == created_run
    assert result.created_signal == created_signal
    experiments.create_run.assert_called_once()
    experiments.create_signal.assert_called_once()
    orders.submit_order.assert_not_called()
    audit_events.create_event.assert_called_once()


def test_consistency_repair_rejects_without_confirmation() -> None:
    service, _experiments, _orders, _audit_events = _consistency_service()

    try:
        service.apply_repair(
            "zero-dte-ledger:zero-order-1",
            request=OperatorConsistencyRepairRequest(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                confirm_local_repair=False,
                actor="operator-a",
                note="repair local evidence only",
            ),
        )
    except ValueError as exc:
        assert "confirm_local_repair=true" in str(exc)
    else:
        raise AssertionError("Expected confirmation guard to reject repair")


def test_ops_consistency_route_returns_summary() -> None:
    service = Mock()
    service.get_summary.return_value = OperatorConsistencySummary(
        generated_at=NOW,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        strategy=None,
        status="pass",
        check_count=0,
        limit=20,
    )
    app.dependency_overrides[get_operator_consistency_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/ops/consistency",
            params={"external_account_id": "LBPT10087357", "mode": "paper", "limit": 20},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "pass"
    service.get_summary.assert_called_once_with(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        strategy=None,
        limit=20,
    )


def test_ops_consistency_repair_route_returns_guarded_result() -> None:
    service = Mock()
    service.apply_repair.return_value = OperatorConsistencyRepairResult(
        repair_id="zero-dte-ledger:zero-order-1",
        repaired=False,
        status="already_repaired",
        message="Already repaired.",
    )
    app.dependency_overrides[get_operator_consistency_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/ops/consistency/repairs/zero-dte-ledger:zero-order-1",
            json={
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "confirm_local_repair": True,
                "actor": "operator-a",
                "note": "repair local evidence only",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "already_repaired"
    service.apply_repair.assert_called_once()
