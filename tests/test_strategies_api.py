from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_bull_put_strategy_service
from stocks_tool.domain.enums import BrokerName, ExecutionMode, SpreadStatus
from stocks_tool.domain.models import (
    BullPutSpread,
    BullPutSpreadMonitorResult,
    BullPutSpreadScanResult,
    DirectionalPutSnapshot,
    PreOpenAssessmentCaptureResult,
    PreOpenAssessmentReviewResult,
    PreOpenAssessmentRun,
    PreOpenReviewCheckpoint,
    OptionChainAnalysis,
    OptionChainExpiryAnalysis,
    OptionChainLiquidStrike,
    PreOpenDownsideAssessment,
    PreOpenProxySignal,
    BullPutStrategyReviewResult,
    BullPutStrategyRuntimeState,
    BullPutStrategyScanRunResult,
)
from stocks_tool.main import app


def with_strategy_service(service: Mock) -> TestClient:
    app.dependency_overrides[get_bull_put_strategy_service] = lambda: service
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_preview_bull_put_strategy_returns_scan_result() -> None:
    service = Mock()
    service.preview_spread.return_value = BullPutSpreadScanResult(
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        external_account_id="LBPT10087357",
        scanned_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        eligible=False,
        reasons=["Bull put spread entries are only evaluated between 10:45 ET and 11:15 ET."],
        moving_average_20=Decimal("450.50"),
        moving_average_50=Decimal("430.25"),
    )

    client = with_strategy_service(service)
    try:
        response = client.get(
            "/strategies/bull-put/preview",
            params={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "QQQ.US"
    assert body["eligible"] is False
    assert body["moving_average_20"] == "450.50"
    request = service.preview_spread.call_args.kwargs
    assert request["external_account_id"] == "LBPT10087357"


def test_pre_open_risk_route_returns_assessment() -> None:
    service = Mock()
    service.get_pre_open_downside_assessment.return_value = PreOpenDownsideAssessment(
        analyzed_at=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
        session="premarket",
        market_open=False,
        target_session_date=datetime(2026, 5, 26, tzinfo=timezone.utc).date(),
        minutes_to_regular_open=55,
        next_regular_open_at=datetime(2026, 5, 26, 13, 30, tzinfo=timezone.utc),
        downside_score=5,
        regime="broad_downside_risk",
        plain_put_view="reasonable",
        preferred_vehicle="QQQ",
        trade_action="wait_for_open_confirmation",
        trade_action_detail="Bias is bearish. Only press QQQ puts if QQQ and semis stay weak through the open.",
        gap_chase_risk="medium",
        gap_chase_detail="The bearish read is usable, but only if the first 5-15 minutes confirm that tech stays weaker than the broad market.",
        summary="Multiple macro and tech proxies are aligned for a weaker U.S. open.",
        reasons=["QQQ is trading meaningfully below its reference level."],
        checkpoints=[],
        signals=[
            PreOpenProxySignal(
                key="qqq",
                label="Nasdaq 100 ETF",
                symbol="QQQ.US",
                session_price=Decimal("710.00"),
                reference_price=Decimal("717.00"),
                change_pct=Decimal("-0.98"),
                signal="bearish",
            )
        ],
        put_snapshots=[
            DirectionalPutSnapshot(
                underlying_symbol="QQQ.US",
                expiration_date=datetime(2026, 5, 29, tzinfo=timezone.utc).date(),
                days_to_expiration=3,
                strike=Decimal("710"),
                put_symbol="QQQ260529P710000.US",
                bid=Decimal("6.10"),
                ask=Decimal("6.30"),
                mid_price=Decimal("6.20"),
                spread_width=Decimal("0.20"),
                spread_pct=Decimal("3.23"),
                distance_from_spot_pct=Decimal("0.99"),
                delta=Decimal("-0.41"),
                implied_volatility=Decimal("0.24"),
                liquidity_label="tight",
            )
        ],
        chain_analyses=[
            OptionChainAnalysis(
                underlying_symbol="QQQ.US",
                underlying_price=Decimal("710.00"),
                analyzed_at=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
                front_expiration=OptionChainExpiryAnalysis(
                    expiration_date=datetime(2026, 5, 29, tzinfo=timezone.utc).date(),
                    days_to_expiration=3,
                    atm_strike=Decimal("710"),
                    atm_put_symbol="QQQ260529P710000.US",
                    atm_implied_volatility=Decimal("0.24"),
                    atm_delta=Decimal("-0.41"),
                    atm_mid_price=Decimal("6.20"),
                    put_skew_strike=Decimal("700"),
                    put_skew_put_symbol="QQQ260529P700000.US",
                    put_skew_implied_volatility=Decimal("0.26"),
                    put_skew_delta=Decimal("-0.25"),
                    put_skew_diff=Decimal("0.02"),
                    median_spread_pct=Decimal("4.10"),
                    tight_count=1,
                    workable_count=1,
                    wide_count=0,
                    liquid_strikes=[
                        OptionChainLiquidStrike(
                            strike=Decimal("710"),
                            put_symbol="QQQ260529P710000.US",
                            open_interest=1200,
                            volume=5000,
                            delta=Decimal("-0.41"),
                            bid=Decimal("6.10"),
                            ask=Decimal("6.30"),
                            mid_price=Decimal("6.20"),
                            spread_width=Decimal("0.20"),
                            spread_pct=Decimal("3.23"),
                            liquidity_label="tight",
                        )
                    ],
                ),
                next_expiration=None,
                atm_iv_term_diff=None,
                term_structure_label=None,
                sample_note="Liquidity buckets use ATM/skew anchors plus the deepest open-interest puts for each expiry.",
            )
        ],
    )

    client = with_strategy_service(service)
    try:
        response = client.get(
            "/strategies/pre-open-risk",
            params={"external_account_id": "LBPT10087357"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["preferred_vehicle"] == "QQQ"
    assert body["plain_put_view"] == "reasonable"
    assert body["trade_action"] == "wait_for_open_confirmation"
    assert body["signals"][0]["symbol"] == "QQQ.US"
    assert body["chain_analyses"][0]["front_expiration"]["atm_put_symbol"] == "QQQ260529P710000.US"
    request = service.get_pre_open_downside_assessment.call_args.kwargs
    assert request["external_account_id"] == "LBPT10087357"
    assert request["include_option_overlays"] is False


def test_capture_pre_open_run_route_returns_run_result() -> None:
    service = Mock()
    run = PreOpenAssessmentRun(
        external_account_id="LBPT10087357",
        target_session_date=datetime(2026, 5, 26, tzinfo=timezone.utc).date(),
        assessment=PreOpenDownsideAssessment(
            analyzed_at=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
            session="holiday",
            market_open=False,
            target_session_date=datetime(2026, 5, 26, tzinfo=timezone.utc).date(),
            minutes_to_regular_open=None,
            next_regular_open_at=datetime(2026, 5, 26, 13, 30, tzinfo=timezone.utc),
            downside_score=4,
            regime="selective_downside_risk",
            plain_put_view="selective",
            preferred_vehicle="QQQ",
            trade_action="prepare_next_session",
            trade_action_detail="Wait for the next regular session.",
            gap_chase_risk="medium",
            gap_chase_detail="Do not pay up blindly into the first print.",
            summary="Memorial Day keeps the next regular open on Tuesday.",
            reasons=["NYSE is closed for Memorial Day on 2026-05-25."],
        ),
        checkpoints=[
            PreOpenReviewCheckpoint(
                key="open",
                label="Opening Print",
                timing_label="09:30 ET",
                scheduled_at=datetime(2026, 5, 26, 13, 30, tzinfo=timezone.utc),
            )
        ],
        review_status="awaiting_open",
    )
    service.capture_pre_open_run.return_value = PreOpenAssessmentCaptureResult(run=run, captured=True)

    client = with_strategy_service(service)
    try:
        response = client.post("/strategies/pre-open-runs/LBPT10087357/capture")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["captured"] is True
    assert body["run"]["target_session_date"] == "2026-05-26"
    request = service.capture_pre_open_run.call_args.kwargs
    assert request["include_option_overlays"] is False


def test_review_pre_open_run_route_returns_review_result() -> None:
    service = Mock()
    run = PreOpenAssessmentRun(
        external_account_id="LBPT10087357",
        target_session_date=datetime(2026, 5, 26, tzinfo=timezone.utc).date(),
        assessment=PreOpenDownsideAssessment(
            analyzed_at=datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
            session="premarket",
            market_open=False,
            target_session_date=datetime(2026, 5, 26, tzinfo=timezone.utc).date(),
            minutes_to_regular_open=70,
            next_regular_open_at=datetime(2026, 5, 26, 13, 30, tzinfo=timezone.utc),
            downside_score=5,
            regime="broad_downside_risk",
            plain_put_view="reasonable",
            preferred_vehicle="QQQ",
            trade_action="wait_for_open_confirmation",
            trade_action_detail="Bias is bearish.",
            gap_chase_risk="medium",
            gap_chase_detail="Wait for confirmation.",
            summary="Weak tape persists.",
        ),
        checkpoints=[],
        review_status="failed",
        review_summary="Opening follow-through failed to confirm the bearish pre-open read by 10:00 ET.",
        review_completed_at=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
    )
    service.review_pre_open_run.return_value = PreOpenAssessmentReviewResult(
        run=run,
        reviewed=True,
        updated_checkpoint_keys=["first_30"],
    )

    client = with_strategy_service(service)
    try:
        response = client.post("/strategies/pre-open-runs/LBPT10087357/review")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["reviewed"] is True
    assert body["updated_checkpoint_keys"] == ["first_30"]


def test_preview_bull_put_strategy_maps_lookup_error_to_404() -> None:
    service = Mock()
    service.preview_spread.side_effect = LookupError("No local account snapshot was found for 'LBPT10087357'. Run account sync first.")

    client = with_strategy_service(service)
    try:
        response = client.get(
            "/strategies/bull-put/preview",
            params={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "No local account snapshot was found for 'LBPT10087357'. Run account sync first."


def test_execute_bull_put_strategy_returns_spread() -> None:
    service = Mock()
    service.execute_spread.return_value = BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=datetime(2026, 6, 19, tzinfo=timezone.utc).date(),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260619P467000.US",
        long_strike=Decimal("467"),
        short_symbol="QQQ260619P470000.US",
        short_strike=Decimal("470"),
        status=SpreadStatus.OPEN,
        long_entry_order_id="long-entry",
        short_entry_order_id="short-entry",
        entry_long_price=Decimal("1.10"),
        entry_short_price=Decimal("2.40"),
        entry_net_credit=Decimal("1.30"),
        max_profit=Decimal("130.00"),
        max_loss=Decimal("170.00"),
        break_even=Decimal("468.70"),
        account_risk_pct=Decimal("0.0034"),
        entry_started_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        opened_at=datetime(2026, 5, 22, 14, 46, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 22, 14, 46, tzinfo=timezone.utc),
    )

    client = with_strategy_service(service)
    try:
        response = client.post(
            "/strategies/bull-put/execute",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "spread-1"
    assert body["status"] == "open"
    request = service.execute_spread.call_args.args[0]
    assert request.external_account_id == "LBPT10087357"


def test_execute_bull_put_strategy_maps_value_error_to_400() -> None:
    service = Mock()
    service.execute_spread.side_effect = ValueError(
        "An active bull put spread already exists for 'QQQ.US' in account 'LBPT10087357'."
    )

    client = with_strategy_service(service)
    try:
        response = client.post(
            "/strategies/bull-put/execute",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "An active bull put spread already exists for 'QQQ.US' in account 'LBPT10087357'."
    )


def test_get_bull_put_runtime_state_returns_runtime_state() -> None:
    service = Mock()
    service.get_runtime_state.return_value = BullPutStrategyRuntimeState(
        id="runtime-1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        auto_entry_enabled=True,
        manual_pause=False,
        kill_switch_active=False,
        paused_symbols=["SMH.US"],
        current_session_date=datetime(2026, 5, 23, tzinfo=timezone.utc).date(),
        daily_entry_count=1,
        daily_realized_pnl=Decimal("80.00"),
        last_scan_at=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
        last_scan_result="executed",
        last_scan_symbol="QQQ.US",
        last_action="Opened bull put spread for QQQ.US.",
        last_action_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 23, 14, 40, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
    )

    client = with_strategy_service(service)
    try:
        response = client.get(
            "/strategies/bull-put/runtime",
            params={"external_account_id": "LBPT10087357", "mode": "paper"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["daily_entry_count"] == 1
    assert body["paused_symbols"] == ["SMH.US"]


def test_run_bull_put_runtime_scan_returns_scan_result() -> None:
    service = Mock()
    runtime_state = BullPutStrategyRuntimeState(
        id="runtime-1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        daily_entry_count=1,
        last_scan_result="executed",
        last_scan_symbol="QQQ.US",
        last_scan_at=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 23, 14, 40, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
    )
    spread = BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=datetime(2026, 6, 19, tzinfo=timezone.utc).date(),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260619P467000.US",
        long_strike=Decimal("467"),
        short_symbol="QQQ260619P470000.US",
        short_strike=Decimal("470"),
        status=SpreadStatus.OPEN,
        created_at=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
    )
    service.run_entry_scan.return_value = BullPutStrategyScanRunResult(
        strategy_state=runtime_state,
        scanned_at=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
        executed=True,
        executed_spread=spread,
    )

    client = with_strategy_service(service)
    try:
        response = client.post(
            "/strategies/bull-put/runtime/LBPT10087357/scan",
            params={"mode": "paper", "force": "true"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["executed"] is True
    assert body["executed_spread"]["id"] == "spread-1"


def test_run_bull_put_runtime_review_returns_review_result() -> None:
    service = Mock()
    runtime_state = BullPutStrategyRuntimeState(
        id="runtime-1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        last_review_at=datetime(2026, 6, 22, 14, 45, tzinfo=timezone.utc),
        last_review_status="suggested",
        last_review_summary="Suggest tightening short delta target from 0.22 to 0.20.",
        created_at=datetime(2026, 5, 23, 14, 40, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 22, 14, 46, tzinfo=timezone.utc),
    )
    service.run_review.return_value = BullPutStrategyReviewResult(
        strategy_state=runtime_state,
        evaluated_at=datetime(2026, 6, 22, 14, 45, tzinfo=timezone.utc),
        review_status="suggested",
        closed_spreads_considered=20,
        lookback_days=30,
        net_realized_pnl=Decimal("-420.00"),
        take_profit_rate=Decimal("0.25"),
        stop_loss_rate=Decimal("0.40"),
        recommendation="Suggest tightening short delta target from 0.22 to 0.20.",
        parameter_name="short_delta_target",
        current_value="0.22",
        suggested_value="0.20",
        journal_entry_id="journal-1",
        reviewed_spread_ids=["spread-1"],
    )

    client = with_strategy_service(service)
    try:
        response = client.post(
            "/strategies/bull-put/runtime/LBPT10087357/review",
            params={"mode": "paper", "force": "true"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "suggested"
    assert body["parameter_name"] == "short_delta_target"
    assert body["journal_entry_id"] == "journal-1"


def test_monitor_bull_put_strategy_returns_monitor_result() -> None:
    service = Mock()
    spread = BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=datetime(2026, 6, 19, tzinfo=timezone.utc).date(),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260619P467000.US",
        long_strike=Decimal("467"),
        short_symbol="QQQ260619P470000.US",
        short_strike=Decimal("470"),
        status=SpreadStatus.CLOSED,
        short_exit_order_id="short-exit",
        long_exit_order_id="long-exit",
        entry_net_credit=Decimal("1.30"),
        exit_reason="take_profit",
        opened_at=datetime(2026, 5, 22, 14, 46, tzinfo=timezone.utc),
        closed_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
    )
    service.monitor_spread.return_value = BullPutSpreadMonitorResult(
        spread=spread,
        evaluated_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
        should_close=True,
        exit_reason="take_profit",
        current_underlying_price=Decimal("501.25"),
        estimated_exit_debit=Decimal("0.50"),
        estimated_pnl=Decimal("80.00"),
        days_to_expiration=27,
    )

    client = with_strategy_service(service)
    try:
        response = client.post("/strategies/bull-put/spreads/spread-1/monitor")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["should_close"] is True
    assert body["exit_reason"] == "take_profit"
    assert body["spread"]["status"] == "closed"
