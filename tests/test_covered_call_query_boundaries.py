from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.application.services.covered_call_strategy import CoveredCallStrategyService
from stocks_tool.application.services.orders import OrderService
from stocks_tool.core.config import Settings
from stocks_tool.db.base import Base
from stocks_tool.db.models import (
    BrokerAccountRecord,
    OrderRecord,
    StrategyProposalRecord,
    StrategyRunRecord,
)
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    StrategyProposalStatus,
    StrategyRunStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    CoveredCallCandidate,
    PositionSnapshot,
)
from stocks_tool.repositories.sqlalchemy_execution_repository import SQLAlchemyExecutionRepository
from stocks_tool.repositories.sqlalchemy_order_repository import SQLAlchemyOrderRepository
from stocks_tool.repositories.sqlalchemy_strategy_experiment_repository import (
    SQLAlchemyStrategyExperimentRepository,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


ACCOUNT_ID = "LBPT10087357"
BROKER_ACCOUNT_ID = "broker-account-1"
NOW = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)


def _candidate_payload() -> dict:
    candidate = CoveredCallCandidate(
        underlying_symbol="UNH.US",
        expiration_date=date(2026, 10, 30),
        days_to_expiration=28,
        contracts=1,
        covered_shares=100,
        share_quantity=Decimal("1000"),
        average_cost=Decimal("500"),
        underlying_price=Decimal("550"),
        call_symbol="UNH261030C600000.US",
        call_strike=Decimal("600"),
        call_bid=Decimal("1.20"),
        call_ask=Decimal("1.30"),
        call_mid=Decimal("1.25"),
        premium_income=Decimal("125"),
        quote_timestamp=NOW,
    )
    return candidate.model_dump(mode="json")


def _build_service(session: Session) -> CoveredCallStrategyService:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    orders = SQLAlchemyOrderRepository(session, attach_intent_ledger=False)
    order_service = OrderService(
        settings=settings,
        broker_accounts=Mock(),
        trade_plans=Mock(),
        orders=orders,
        executions=SQLAlchemyExecutionRepository(session),
        longbridge_adapter=Mock(),
    )
    snapshots = Mock()
    snapshots.get_latest_account_snapshot.return_value = AccountSnapshot(
        id="snapshot-1",
        broker=BrokerName.LONGBRIDGE,
        account_id=ACCOUNT_ID,
        cash_balance=Decimal("10000"),
        net_liquidation=Decimal("100000"),
        buying_power=Decimal("50000"),
        positions=[
            PositionSnapshot(
                symbol="UNH.US",
                asset_type=AssetType.STOCK,
                quantity=Decimal("1000"),
                average_cost=Decimal("500"),
                market_value=Decimal("550000"),
                unrealized_pnl=Decimal("50000"),
            )
        ],
        captured_at=NOW,
    )
    return CoveredCallStrategyService(
        settings=settings,
        broker_accounts=Mock(),
        account_snapshots=snapshots,
        experiments=SQLAlchemyStrategyExperimentRepository(session),
        longbridge_adapter=Mock(),
        order_service=order_service,
    )


def test_covered_call_reservation_reads_old_active_rows_after_large_history() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                BrokerAccountRecord(
                    id=BROKER_ACCOUNT_ID,
                    broker=BrokerName.LONGBRIDGE.value,
                    external_account_id=ACCOUNT_ID,
                )
            )
            candidate = _candidate_payload()
            proposals = [
                StrategyProposalRecord(
                    id="proposal-current",
                    strategy_id="covered_call_v1",
                    external_account_id=ACCOUNT_ID,
                    execution_mode=ExecutionMode.PAPER.value,
                    symbol="UNH.US",
                    title="Current proposal",
                    proposed_action="sell_covered_call",
                    rationale="Current request",
                    status=StrategyProposalStatus.APPROVED.value,
                    candidate_payload=candidate,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                StrategyProposalRecord(
                    id="proposal-old-active",
                    strategy_id="covered_call_v1",
                    external_account_id=ACCOUNT_ID,
                    execution_mode=ExecutionMode.PAPER.value,
                    symbol="UNH.US",
                    title="Old active proposal",
                    proposed_action="sell_covered_call",
                    rationale="Must survive the display history cap",
                    status=StrategyProposalStatus.EXECUTED.value,
                    candidate_payload=candidate,
                    created_at=NOW - timedelta(days=10),
                    updated_at=NOW - timedelta(days=10),
                ),
            ]
            for index in range(150):
                proposals.append(
                    StrategyProposalRecord(
                        id=f"proposal-terminal-{index:04d}",
                        strategy_id="covered_call_v1",
                        external_account_id=ACCOUNT_ID,
                        execution_mode=ExecutionMode.PAPER.value,
                        symbol="UNH.US",
                        title="Terminal history",
                        proposed_action="sell_covered_call",
                        rationale="Must not reserve shares",
                        status=StrategyProposalStatus.CLOSED.value,
                        candidate_payload=candidate,
                        created_at=NOW - timedelta(minutes=index + 1),
                        updated_at=NOW - timedelta(minutes=index + 1),
                    )
                )
            proposals.extend(
                [
                    StrategyProposalRecord(
                        id="proposal-live",
                        strategy_id="covered_call_v1",
                        external_account_id=ACCOUNT_ID,
                        execution_mode=ExecutionMode.LIVE.value,
                        symbol="UNH.US",
                        title="Wrong mode",
                        proposed_action="sell_covered_call",
                        rationale="Must be isolated",
                        status=StrategyProposalStatus.EXECUTED.value,
                        candidate_payload=candidate,
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    StrategyProposalRecord(
                        id="proposal-other-account",
                        strategy_id="covered_call_v1",
                        external_account_id="other-account",
                        execution_mode=ExecutionMode.PAPER.value,
                        symbol="UNH.US",
                        title="Wrong account",
                        proposed_action="sell_covered_call",
                        rationale="Must be isolated",
                        status=StrategyProposalStatus.EXECUTED.value,
                        candidate_payload=candidate,
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    StrategyProposalRecord(
                        id="proposal-other-symbol",
                        strategy_id="covered_call_v1",
                        external_account_id=ACCOUNT_ID,
                        execution_mode=ExecutionMode.PAPER.value,
                        symbol="QQQ.US",
                        title="Wrong symbol",
                        proposed_action="sell_covered_call",
                        rationale="Must be isolated",
                        status=StrategyProposalStatus.EXECUTED.value,
                        candidate_payload=candidate,
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                ]
            )
            runs = [
                StrategyRunRecord(
                    id="run-old-related",
                    strategy_id="covered_call_v1",
                    external_account_id=ACCOUNT_ID,
                    execution_mode=ExecutionMode.PAPER.value,
                    run_type="open_lifecycle_refresh",
                    status=StrategyRunStatus.EXECUTED.value,
                    symbol="UNH.US",
                    proposal_id="proposal-old-active",
                    order_id="old-working-order",
                    metrics_payload={"order_id": "old-working-order"},
                    created_at=NOW - timedelta(days=10),
                    updated_at=NOW - timedelta(days=10),
                )
            ]
            for index in range(520):
                runs.append(
                    StrategyRunRecord(
                        id=f"run-unrelated-{index:04d}",
                        strategy_id="covered_call_v1",
                        external_account_id=ACCOUNT_ID,
                        execution_mode=ExecutionMode.PAPER.value,
                        run_type="proposal_preview",
                        status=StrategyRunStatus.EXECUTED.value,
                        symbol="UNH.US",
                        proposal_id="other-proposal",
                        created_at=NOW - timedelta(minutes=index),
                        updated_at=NOW - timedelta(minutes=index),
                    )
                )
            session.add_all(proposals)
            session.add_all(runs)
            session.add(
                OrderRecord(
                    id="old-working-order",
                    broker_account_id=BROKER_ACCOUNT_ID,
                    broker=BrokerName.LONGBRIDGE.value,
                    external_order_id="external-old-working-order",
                    client_order_id="client-old-working-order",
                    symbol="UNH261030C600000.US",
                    asset_type=AssetType.OPTION.value,
                    side=OrderSide.SELL.value,
                    quantity=1,
                    order_type=OrderType.LIMIT.value,
                    time_in_force=TimeInForce.DAY.value,
                    execution_mode=ExecutionMode.PAPER.value,
                    status=OrderStatus.SUBMITTED.value,
                    created_at=NOW - timedelta(days=10),
                    updated_at=NOW - timedelta(days=10),
                )
            )
            session.commit()

            service = _build_service(session)
            reserved = service._reserved_covered_call_shares(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                underlying_symbol="UNH.US",
                excluded_proposal_ids={"proposal-current"},
            )

            assert reserved == 100
            assert service.reconcile_pending_lifecycle(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
            ) == {
                "sell_orders_refreshed": 0,
                "sell_orders_executed": 0,
                "close_orders_refreshed": 0,
                "closed_proposals": 0,
                "roll_buyback_orders_refreshed": 0,
                "roll_sell_orders_refreshed": 0,
                "roll_sell_orders_submitted": 0,
                "roll_sell_orders_waiting_confirmation": 0,
                "rolls_executed": 0,
            }
            assert service.reconcile_pending_lifecycle(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.LIVE,
            ) == {
                "sell_orders_refreshed": 0,
                "sell_orders_executed": 0,
                "close_orders_refreshed": 0,
                "closed_proposals": 0,
                "roll_buyback_orders_refreshed": 0,
                "roll_sell_orders_refreshed": 0,
                "roll_sell_orders_submitted": 0,
                "roll_sell_orders_waiting_confirmation": 0,
                "rolls_executed": 0,
            }
    finally:
        engine.dispose()
