from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, call
from zoneinfo import ZoneInfo

import pytest

from stocks_tool.application.services.covered_call_strategy import CoveredCallStrategyService
from stocks_tool.application.services.orders import TradingIntentConflictError
from stocks_tool.application.services.strategy_idempotency import strategy_order_identity
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    MarketEventSeverity,
    MarketEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    OptionRight,
    RiskStatus,
    StrategyProposalStatus,
    StrategyRunStatus,
    StrategySignalType,
    TimeInForce,
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerOrderIntent,
    BrokerAccount,
    CloseCoveredCallProposalRequest,
    ContinueCoveredCallRollRequest,
    CreateCoveredCallRollProposalRequest,
    ExecuteCoveredCallProposalRequest,
    ExecuteCoveredCallRollProposalRequest,
    MarketEvent,
    OptionChainEntry,
    OptionContractRef,
    OptionMarketSnapshot,
    Order,
    PositionSnapshot,
    PreparedTradeActionIntent,
    SecurityQuoteSnapshot,
    StrategyProposal,
    StrategyRun,
    StrategySignal,
    TradeActionIntent,
)


NOW = datetime(2026, 5, 29, 15, 0, tzinfo=timezone.utc)


class FakeBrokerAccounts:
    def get_by_external_account_id(self, external_account_id: str) -> BrokerAccount | None:
        if external_account_id != "LBPT10087357":
            return None
        return BrokerAccount(
            id="broker-account-1",
            broker=BrokerName.LONGBRIDGE,
            external_account_id=external_account_id,
            display_name="Longbridge Paper",
            base_currency="USD",
            is_active=True,
            auto_reconcile_enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )


class FakeAccountSnapshots:
    def __init__(self, snapshot: AccountSnapshot | None) -> None:
        self.snapshot = snapshot

    def get_latest_account_snapshot(self, external_account_id: str) -> AccountSnapshot | None:
        return self.snapshot


class FakeExperiments:
    def __init__(
        self,
        proposal: StrategyProposal | list[StrategyProposal] | None = None,
        runs: list[StrategyRun] | None = None,
    ) -> None:
        proposals = [] if proposal is None else proposal if isinstance(proposal, list) else [proposal]
        self.proposals = {item.id: item for item in proposals}
        self.runs = list(runs or [])
        self.signals = []
        self.proposal = proposals[-1] if proposals else None
        self.proposal_counter = len(proposals) + 1
        self.run_request = None
        self.signal_request = None
        self.proposal_request = None
        self.updated_status = None
        self.updated_statuses = {}

    def create_run(self, request):
        self.run_request = request
        run = StrategyRun(
            id="run-1",
            strategy_id=request.strategy_id,
            external_account_id=request.external_account_id,
            mode=request.mode,
            run_type=request.run_type,
            status=request.status,
            symbol=request.symbol,
            proposal_id=request.proposal_id,
            order_id=request.order_id,
            summary=request.summary,
            reason=request.reason,
            metrics_payload=request.metrics_payload,
            created_at=NOW,
            updated_at=NOW,
        )
        self.runs.insert(0, run)
        return run

    def create_signal(self, request):
        self.signal_request = request
        signal = StrategySignal(
            id="signal-1",
            strategy_id=request.strategy_id,
            external_account_id=request.external_account_id,
            mode=request.mode,
            signal_type=request.signal_type,
            symbol=request.symbol,
            run_id=request.run_id,
            strength=request.strength,
            summary=request.summary,
            emitted_at=NOW,
            created_at=NOW,
        )
        self.signals.append(signal)
        return signal

    def create_proposal(self, request):
        self.proposal_request = request
        proposal_id = f"proposal-{self.proposal_counter}"
        self.proposal_counter += 1
        self.proposal = StrategyProposal(
            id=proposal_id,
            strategy_id=request.strategy_id,
            external_account_id=request.external_account_id,
            mode=request.mode,
            symbol=request.symbol,
            title=request.title,
            proposed_action=request.proposed_action,
            rationale=request.rationale,
            status=StrategyProposalStatus.PENDING,
            expected_max_loss=request.expected_max_loss,
            expected_max_profit=request.expected_max_profit,
            source_run_id=request.source_run_id,
            candidate_payload=request.candidate_payload,
            risk_payload=request.risk_payload,
            checks=request.checks,
            created_at=NOW,
            updated_at=NOW,
        )
        self.proposals[proposal_id] = self.proposal
        return self.proposal

    def get_proposal(self, proposal_id: str):
        return self.proposals.get(proposal_id)

    def update_proposal_status(self, proposal_id: str, *, status, approved_at=None, rejected_at=None):
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise LookupError(f"Strategy proposal '{proposal_id}' was not found.")
        self.updated_status = status
        self.updated_statuses[proposal_id] = status
        proposal = proposal.model_copy(update={"status": status, "updated_at": NOW})
        self.proposals[proposal_id] = proposal
        self.proposal = proposal
        return proposal

    def list_proposals(
        self,
        *,
        external_account_id=None,
        strategy_id=None,
        status=None,
        statuses=None,
        mode=None,
        symbol=None,
        symbols=None,
        proposal_ids=None,
        proposed_actions=None,
        limit=20,
    ):
        proposals = list(self.proposals.values())
        if external_account_id is not None:
            proposals = [item for item in proposals if item.external_account_id == external_account_id]
        if strategy_id is not None:
            proposals = [item for item in proposals if item.strategy_id == strategy_id]
        if status is not None:
            proposals = [item for item in proposals if item.status == status]
        if statuses is not None:
            proposals = [item for item in proposals if item.status in statuses]
        if mode is not None:
            proposals = [item for item in proposals if item.mode == mode]
        if symbol is not None:
            proposals = [item for item in proposals if item.symbol == symbol]
        if symbols is not None:
            proposals = [item for item in proposals if item.symbol in symbols]
        if proposal_ids is not None:
            proposals = [item for item in proposals if item.id in proposal_ids]
        if proposed_actions is not None:
            proposals = [item for item in proposals if item.proposed_action in proposed_actions]
        return proposals if limit is None else proposals[:limit]

    def list_runs(
        self,
        *,
        external_account_id=None,
        strategy_id=None,
        status=None,
        statuses=None,
        mode=None,
        symbol=None,
        proposal_id=None,
        proposal_ids=None,
        run_types=None,
        limit=20,
    ):
        runs = list(self.runs)
        if external_account_id is not None:
            runs = [item for item in runs if item.external_account_id == external_account_id]
        if strategy_id is not None:
            runs = [item for item in runs if item.strategy_id == strategy_id]
        if status is not None:
            runs = [item for item in runs if item.status == status]
        if statuses is not None:
            runs = [item for item in runs if item.status in statuses]
        if mode is not None:
            runs = [item for item in runs if item.mode == mode]
        if symbol is not None:
            runs = [item for item in runs if item.symbol == symbol]
        if proposal_id is not None:
            runs = [item for item in runs if item.proposal_id == proposal_id]
        if proposal_ids is not None:
            runs = [item for item in runs if item.proposal_id in proposal_ids]
        if run_types is not None:
            runs = [item for item in runs if item.run_type in run_types]
        return runs if limit is None else runs[:limit]

    def list_latest_runs_by_proposal(
        self,
        *,
        external_account_id=None,
        strategy_id=None,
        mode=None,
        run_types,
    ):
        runs = self.list_runs(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            mode=mode,
            limit=None,
        )
        latest = {}
        for run in runs:
            if run.proposal_id is None or run.run_type not in run_types:
                continue
            if run.proposal_id not in latest:
                latest[run.proposal_id] = run
        return list(latest.values())

    def get_latest_run_for_proposal(self, *, proposal_id, strategy_id, run_types):
        for run in self.runs:
            if (
                run.proposal_id == proposal_id
                and run.strategy_id == strategy_id
                and run.run_type in run_types
            ):
                return run
        return None


class FakeMarketEvents:
    def __init__(self, events: list[MarketEvent]) -> None:
        self.events = events

    def list_events(self, **kwargs) -> list[MarketEvent]:
        return self.events


def build_snapshot(*, quantity: Decimal = Decimal("100")) -> AccountSnapshot:
    return AccountSnapshot(
        id="snapshot-1",
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        cash_balance=Decimal("10000"),
        net_liquidation=Decimal("50000"),
        buying_power=Decimal("25000"),
        positions=[
            PositionSnapshot(
                symbol="UNH.US",
                asset_type=AssetType.STOCK,
                quantity=quantity,
                average_cost=Decimal("90"),
                market_value=Decimal("10000"),
                unrealized_pnl=Decimal("1000"),
            )
        ],
        captured_at=NOW,
    )


def build_adapter() -> Mock:
    adapter = Mock()
    adapter.get_quote.return_value = SecurityQuoteSnapshot(
        symbol="UNH.US",
        last_done=Decimal("100"),
        prev_close=Decimal("99"),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("98"),
        timestamp=NOW,
        volume=1_000_000,
        turnover=Decimal("100000000"),
        trade_status="Normal",
    )
    adapter.list_option_expiry_dates.return_value = [date(2026, 6, 26)]
    adapter.list_option_chain.return_value = [
        OptionChainEntry(strike=Decimal("105"), call_symbol="UNH260626C105000.US")
    ]
    adapter.get_option_market_snapshots.return_value = [
        OptionMarketSnapshot(
            symbol="UNH260626C105000.US",
            underlying_symbol="UNH.US",
            expiration_date=date(2026, 6, 26),
            strike=Decimal("105"),
            right=OptionRight.CALL,
            last_done=Decimal("1.25"),
            prev_close=Decimal("1.20"),
            open=Decimal("1.10"),
            high=Decimal("1.40"),
            low=Decimal("1.00"),
            timestamp=NOW,
            volume=25,
            turnover=Decimal("3125"),
            bid=Decimal("1.20"),
            ask=Decimal("1.30"),
            open_interest=800,
            delta=Decimal("0.30"),
        )
    ]
    return adapter


def build_roll_adapter() -> Mock:
    adapter = build_adapter()
    base_quote = adapter.get_option_market_snapshots.return_value[0]
    roll_quote = base_quote.model_copy(
        update={
            "symbol": "UNH260710C110000.US",
            "expiration_date": date(2026, 7, 10),
            "strike": Decimal("110"),
            "bid": Decimal("1.05"),
            "ask": Decimal("1.15"),
            "open_interest": 900,
            "volume": 35,
        }
    )
    adapter.get_option_market_snapshots.side_effect = lambda symbols, mode: [
        roll_quote if symbols[0] == roll_quote.symbol else base_quote
    ]
    return adapter


def build_candidate_payload(
    *,
    call_symbol: str = "UNH260626C105000.US",
    expiration_date: str = "2026-06-26",
    call_strike: str = "105",
    call_bid: str = "1.20",
    call_ask: str = "1.30",
    call_mid: str = "1.25",
    premium_income: str = "120.00",
) -> dict:
    return {
        "underlying_symbol": "UNH.US",
        "expiration_date": expiration_date,
        "days_to_expiration": 28,
        "contracts": 1,
        "covered_shares": 100,
        "share_quantity": "100",
        "average_cost": "90",
        "underlying_price": "100",
        "call_symbol": call_symbol,
        "call_strike": call_strike,
        "call_bid": call_bid,
        "call_ask": call_ask,
        "call_mid": call_mid,
        "premium_income": premium_income,
        "delta": "0.30",
        "open_interest": 800,
        "volume": 25,
        "quote_timestamp": "2026-05-29T15:00:00Z",
    }


def build_roll_proposal(*, proposal_id: str = "roll-proposal") -> StrategyProposal:
    return StrategyProposal(
        id=proposal_id,
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Roll covered call on UNH.US",
        proposed_action="roll_covered_call",
        rationale="Approved roll proposal.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload={
            "source_proposal_id": "source-proposal",
            "roll_from": build_candidate_payload(),
            "roll_to": build_candidate_payload(
                call_symbol="UNH260710C110000.US",
                expiration_date="2026-07-10",
                call_strike="110",
                call_bid="1.10",
                call_ask="1.20",
                call_mid="1.15",
                premium_income="110.00",
            ),
        },
        created_at=NOW,
        updated_at=NOW,
    )


def build_roll_order(
    *,
    order_id: str,
    symbol: str,
    side: OrderSide,
    quantity: int = 1,
    status: OrderStatus = OrderStatus.FILLED,
) -> Order:
    return Order(
        id=order_id,
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id=f"external-{order_id}",
        symbol=symbol,
        asset_type=AssetType.OPTION,
        side=side,
        quantity=quantity,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=status,
        limit_price=Decimal("1.10"),
        created_at=NOW,
        updated_at=NOW,
    )


def build_strategy_run(
    *,
    proposal_id: str,
    run_type: str,
    order_id: str,
    metrics_payload: dict | None = None,
) -> StrategyRun:
    return StrategyRun(
        id=f"run-{proposal_id}-{run_type}",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        run_type=run_type,
        status=StrategyRunStatus.EXECUTED,
        symbol="UNH.US",
        proposal_id=proposal_id,
        order_id=order_id,
        metrics_payload=metrics_payload,
        created_at=NOW,
        updated_at=NOW,
    )


def build_service(
    *,
    snapshot: AccountSnapshot | None = None,
    experiments: FakeExperiments | None = None,
    order_service: Mock | None = None,
    adapter: Mock | None = None,
    market_events: FakeMarketEvents | None = None,
    audit_events: Mock | None = None,
) -> CoveredCallStrategyService:
    if order_service is not None:
        order_service.has_unresolved_intents.return_value = False
        order_service.list_orders.return_value = []
        order_service.list_trading_intents.return_value = []
    return CoveredCallStrategyService(
        settings=Settings(),
        broker_accounts=FakeBrokerAccounts(),
        account_snapshots=FakeAccountSnapshots(snapshot or build_snapshot()),
        experiments=experiments or FakeExperiments(),
        longbridge_adapter=adapter or build_adapter(),
        order_service=order_service,
        market_events=market_events,
        audit_events=audit_events,
        authorization_clock=lambda: NOW,
    )


def configure_parent_action(
    order_service: Mock,
    *,
    action_id: str,
    idempotency_key: str,
    entity_id: str = "proposal-2",
    created: bool = True,
    state: TradingIntentState = TradingIntentState.PREPARED,
    response_payload: dict | None = None,
) -> None:
    order_service.prepare_trade_action.side_effect = None
    order_service.prepare_trade_action.return_value = PreparedTradeActionIntent(
        intent=TradeActionIntent(
            id=action_id,
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key=idempotency_key,
            request_hash="parent-request-hash",
            action="covered_call_roll_execute",
            strategy_id="covered_call_v1",
            entity_id=entity_id,
            state=state,
            request_payload={},
            response_payload=response_payload,
            created_at=NOW,
            updated_at=NOW,
        ),
        created=created,
    )


def test_strategy_order_identity_scopes_public_idempotency_namespace() -> None:
    baseline, _ = strategy_order_identity(
        strategy_id="covered_call_v1",
        entity_id="proposal-1",
        action="covered_call_open",
        leg="short_call_open",
    )
    first, first_context = strategy_order_identity(
        strategy_id="covered_call_v1",
        entity_id="proposal-1",
        action="covered_call_open",
        leg="short_call_open",
        request_namespace="covered-call-request-0001",
    )
    second, _ = strategy_order_identity(
        strategy_id="covered_call_v1",
        entity_id="proposal-1",
        action="covered_call_open",
        leg="short_call_open",
        request_namespace="covered-call-request-0002",
    )

    assert len({baseline, first, second}) == 3
    assert first_context.entity_id.startswith("proposal-1:")


def test_covered_call_preview_selects_liquid_otm_call() -> None:
    service = build_service()

    preview = service.preview(
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert preview.eligible is True
    assert preview.symbol == "UNH.US"
    assert preview.candidate is not None
    assert preview.candidate.call_symbol == "UNH260626C105000.US"
    assert preview.candidate.contracts == 1
    assert preview.candidate.premium_income == Decimal("120.00")
    assert preview.risk is not None
    assert preview.risk.status == RiskStatus.PASS
    assert preview.risk.max_assignment_profit == Decimal("1620.00")


def test_covered_call_preview_filters_chain_before_market_snapshot_request() -> None:
    adapter = build_adapter()
    adapter.list_option_chain.return_value = [
        OptionChainEntry(strike=Decimal("95"), call_symbol="UNH260626C095000.US"),
        OptionChainEntry(strike=Decimal("105"), call_symbol="UNH260626C105000.US"),
        OptionChainEntry(strike=Decimal("130"), call_symbol="UNH260626C130000.US"),
    ]
    service = build_service(adapter=adapter)

    preview = service.preview(
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert preview.eligible is True
    adapter.get_option_market_snapshots.assert_called_with(
        symbols=["UNH260626C105000.US"],
        mode=ExecutionMode.PAPER,
    )


def test_covered_call_preview_blocks_without_covered_lot() -> None:
    service = build_service(snapshot=build_snapshot(quantity=Decimal("50")))

    preview = service.preview(
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert preview.eligible is False
    assert preview.candidate is None
    assert "at least 100 shares" in preview.reasons[0]


def test_covered_call_preview_warns_on_upcoming_market_event() -> None:
    events = FakeMarketEvents(
        [
            MarketEvent(
                id="event-1",
                symbol="UNH.US",
                event_type=MarketEventType.EARNINGS,
                title="UNH earnings",
                scheduled_at=datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc),
                severity=MarketEventSeverity.HIGH,
                created_at=NOW,
                updated_at=NOW,
            )
        ]
    )
    service = build_service(market_events=events)

    preview = service.preview(
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert preview.eligible is True
    assert preview.risk is not None
    assert preview.risk.status == RiskStatus.WARN
    assert "UNH earnings" in preview.warnings[0]


def test_covered_call_proposal_writes_strategy_experiment_records() -> None:
    experiments = FakeExperiments()
    service = build_service(experiments=experiments)

    result = service.create_proposal(
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert result.proposal is not None
    assert result.proposal.strategy_id == "covered_call_v1"
    assert result.proposal.proposed_action == "sell_covered_call"
    assert result.proposal.source_run_id == "run-1"
    assert experiments.run_request.status == StrategyRunStatus.EXECUTED
    assert experiments.signal_request.signal_type == StrategySignalType.CANDIDATE
    assert experiments.proposal_request.checks == [
        "local_position_covered",
        "otm_call",
        "delta_window",
        "liquidity_filter",
        "manual_approval_required",
    ]


def test_covered_call_proposal_skips_active_duplicate() -> None:
    existing_proposal = StrategyProposal(
        id="proposal-existing",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Existing active proposal.",
        status=StrategyProposalStatus.PENDING,
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(existing_proposal)
    service = build_service(experiments=experiments)

    result = service.create_proposal(
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert result.proposal is not None
    assert result.proposal.id == "proposal-existing"
    assert experiments.proposal_request is None
    assert len(experiments.proposals) == 1
    assert experiments.run_request.status == StrategyRunStatus.SKIPPED
    assert "already exists" in experiments.run_request.reason
    assert experiments.signal_request.signal_type == StrategySignalType.RISK_CHECK


def test_covered_call_execute_requires_approved_proposal_and_submits_option_order() -> None:
    proposal = StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Sell 1 call against 100 shares.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload={
            "underlying_symbol": "UNH.US",
            "expiration_date": "2026-06-26",
            "days_to_expiration": 28,
            "contracts": 1,
            "covered_shares": 100,
            "share_quantity": "100",
            "average_cost": "90",
            "underlying_price": "100",
            "call_symbol": "UNH260626C105000.US",
            "call_strike": "105",
            "call_bid": "1.20",
            "call_ask": "1.30",
            "call_mid": "1.25",
            "premium_income": "120.00",
            "delta": "0.30",
            "open_interest": 800,
            "volume": 25,
            "quote_timestamp": "2026-05-29T15:00:00Z",
        },
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(proposal)
    order_service = Mock()
    order_service.submit_order.return_value = Order(
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
        status=OrderStatus.FILLED,
        limit_price=Decimal("1.20"),
        created_at=NOW,
        updated_at=NOW,
    )
    adapter = build_adapter()
    adapter.get_option_market_snapshots.return_value = [
        adapter.get_option_market_snapshots.return_value[0].model_copy(
            update={"bid": Decimal("1.10"), "ask": Decimal("1.20")}
        )
    ]
    service = build_service(
        experiments=experiments,
        order_service=order_service,
        adapter=adapter,
    )
    configure_parent_action(
        order_service,
        action_id="covered-parent-1",
        idempotency_key="covered-public-key-0001",
        entity_id="proposal-1",
    )

    result = service.execute_approved_proposal(
        "proposal-1",
        request=ExecuteCoveredCallProposalRequest(),
        idempotency_key="covered-public-key-0001",
    )

    assert result.proposal.status == StrategyProposalStatus.EXECUTED
    assert result.order.id == "order-1"
    request = order_service.submit_order.call_args.args[0]
    assert request.symbol == "UNH260626C105000.US"
    assert request.asset_type == AssetType.OPTION
    assert request.side == OrderSide.SELL
    assert request.limit_price == Decimal("1.10")
    assert request.option_contract.underlying_symbol == "UNH.US"
    assert order_service.submit_order.call_args.kwargs["idempotency_key"].startswith("strategy:")
    assert order_service.submit_order.call_args.kwargs["action_context"].leg == "short_call_open"
    assert order_service.submit_order.call_args.kwargs["action_context"].entity_id == "proposal-1"
    assert order_service.submit_order.call_args.kwargs["parent_action_intent_id"] == "covered-parent-1"
    assert order_service.has_unresolved_intents.call_args.kwargs[
        "exclude_action_intent_id"
    ] == "covered-parent-1"
    order_service.complete_trade_action.assert_called_once()
    assert experiments.updated_status == StrategyProposalStatus.EXECUTED


def test_covered_call_execute_blocks_cached_underlying_before_submit() -> None:
    proposal = StrategyProposal(
        id="proposal-cached-quote",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Sell 1 call against 100 shares.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    adapter = build_adapter()
    adapter.get_quote.return_value = adapter.get_quote.return_value.model_copy(
        update={"data_quality": "cached", "warning_code": "quote_cache_fallback"}
    )
    order_service = Mock()
    service = build_service(
        experiments=FakeExperiments(proposal),
        order_service=order_service,
        adapter=adapter,
    )
    configure_parent_action(
        order_service,
        action_id="covered-parent-cached",
        idempotency_key="covered-cached-key-0001",
        entity_id=proposal.id,
    )

    with pytest.raises(ValueError, match="Cached underlying quote"):
        service.execute_approved_proposal(
            proposal.id,
            request=ExecuteCoveredCallProposalRequest(),
            idempotency_key="covered-cached-key-0001",
        )

    order_service.submit_order.assert_not_called()


def test_covered_call_execute_keeps_working_sell_order_approved() -> None:
    proposal = StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Sell 1 call against 100 shares.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(proposal)
    order_service = Mock()
    order_service.submit_order.return_value = Order(
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
        submitted_at=NOW - timedelta(minutes=20),
        created_at=NOW,
        updated_at=NOW,
    )
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.execute_approved_proposal(
        "proposal-1",
        request=ExecuteCoveredCallProposalRequest(),
    )

    assert result.proposal.status == StrategyProposalStatus.APPROVED
    assert result.order.status == OrderStatus.SUBMITTED
    assert experiments.updated_status is None
    assert experiments.run_request.metrics_payload["sequence_status"] == "sell_submitted_waiting_fill"
    assert experiments.run_request.metrics_payload["sell_status"] == "submitted"


def test_covered_call_execute_blocks_same_day_option_position_mapped_as_stock() -> None:
    proposal = StrategyProposal(
        id="proposal-same-day",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Sell 1 call against 100 shares.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    snapshot = build_snapshot()
    expiry_token = datetime.now(ZoneInfo("America/New_York")).strftime("%y%m%d")
    snapshot.positions.append(
        PositionSnapshot(
            symbol=f"UNH{expiry_token}C105000.US",
            asset_type=AssetType.STOCK,
            quantity=Decimal("-1"),
            average_cost=Decimal("1.20"),
            market_value=Decimal("-120"),
            unrealized_pnl=Decimal("0"),
        )
    )
    order_service = Mock()
    audit_events = Mock()
    service = build_service(
        snapshot=snapshot,
        experiments=FakeExperiments(proposal),
        order_service=order_service,
        audit_events=audit_events,
    )
    configure_parent_action(
        order_service,
        action_id="covered-parent-same-day",
        idempotency_key="covered-same-day-key-0001",
        entity_id=proposal.id,
    )

    with pytest.raises(ValueError, match="same-day expiring option positions"):
        service.execute_approved_proposal(
            proposal.id,
            request=ExecuteCoveredCallProposalRequest(),
            idempotency_key="covered-same-day-key-0001",
        )

    order_service.submit_order.assert_not_called()
    order_service.mark_trade_action_rejected.assert_called_once()
    warning = audit_events.create_event.call_args.args[0]
    assert warning.warning_code == "same_day_option_position_requires_manual_action"
    assert warning.payload["severity"] == "critical"
    assert warning.payload["manual_action_required"] is True


def test_covered_call_different_public_key_reuses_same_child_identity() -> None:
    proposal = StrategyProposal(
        id="proposal-repeat",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Sell 1 call against 100 shares.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    working_order = Order(
        id="working-repeat-order",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-working-repeat-order",
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
    )
    order_service = Mock()
    order_service.submit_order.return_value = working_order
    service = build_service(
        experiments=FakeExperiments(proposal),
        order_service=order_service,
    )
    configure_parent_action(
        order_service,
        action_id="covered-parent-repeat-1",
        idempotency_key="covered-repeat-key-0001",
        entity_id=proposal.id,
    )
    service.execute_approved_proposal(
        proposal.id,
        ExecuteCoveredCallProposalRequest(),
        idempotency_key="covered-repeat-key-0001",
    )
    first_child_key = order_service.submit_order.call_args.kwargs["idempotency_key"]

    configure_parent_action(
        order_service,
        action_id="covered-parent-repeat-2",
        idempotency_key="covered-repeat-key-0002",
        entity_id=proposal.id,
    )
    order_service.submit_order.side_effect = ValueError(
        "Existing deterministic child belongs to the first parent action."
    )
    with pytest.raises(ValueError, match="first parent action"):
        service.execute_approved_proposal(
            proposal.id,
            ExecuteCoveredCallProposalRequest(),
            idempotency_key="covered-repeat-key-0002",
        )

    second_child_key = order_service.submit_order.call_args.kwargs["idempotency_key"]
    assert second_child_key == first_child_key
    assert order_service.submit_order.call_count == 2
    order_service.mark_trade_action_rejected.assert_called_with(
        "covered-parent-repeat-2",
        "Existing deterministic child belongs to the first parent action.",
    )


def test_covered_call_execute_reserves_shares_for_other_working_short_call() -> None:
    current = StrategyProposal(
        id="proposal-current",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Current covered call",
        proposed_action="sell_covered_call",
        rationale="Current action.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    other_working = current.model_copy(
        update={
            "id": "proposal-working",
            "title": "Working covered call",
        }
    )
    experiments = FakeExperiments([current, other_working])
    order_service = Mock()
    service = build_service(experiments=experiments, order_service=order_service)

    with pytest.raises(ValueError, match="0 unreserved shares"):
        service.execute_approved_proposal(
            current.id,
            request=ExecuteCoveredCallProposalRequest(),
        )

    order_service.submit_order.assert_not_called()


def test_covered_call_execute_blocks_unlinked_working_short_call_order() -> None:
    proposal = StrategyProposal(
        id="proposal-current",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Current covered call",
        proposed_action="sell_covered_call",
        rationale="Current action.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    order_service = Mock()
    service = build_service(
        experiments=FakeExperiments(proposal),
        order_service=order_service,
    )
    order_service.list_orders.return_value = [
        Order(
            id="unlinked-working-call",
            broker=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            external_order_id="external-unlinked-working-call",
            symbol="UNH260626C110000.US",
            asset_type=AssetType.STOCK,
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            mode=ExecutionMode.PAPER,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("0.80"),
            option_contract=None,
            created_at=NOW,
            updated_at=NOW,
        )
    ]

    with pytest.raises(ValueError, match="0 unreserved shares"):
        service.execute_approved_proposal(
            proposal.id,
            request=ExecuteCoveredCallProposalRequest(),
        )

    order_service.submit_order.assert_not_called()


def test_covered_call_execute_blocks_when_trading_intent_is_unresolved() -> None:
    proposal = StrategyProposal(
        id="proposal-current",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Current covered call",
        proposed_action="sell_covered_call",
        rationale="Current action.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    order_service = Mock()
    service = build_service(
        experiments=FakeExperiments(proposal),
        order_service=order_service,
    )
    order_service.has_unresolved_intents.return_value = True

    with pytest.raises(ValueError, match="unresolved trading intent"):
        service.execute_approved_proposal(
            proposal.id,
            request=ExecuteCoveredCallProposalRequest(),
        )

    order_service.submit_order.assert_not_called()


def test_covered_call_reserves_unlinked_unknown_sell_call_intent_without_local_order() -> None:
    proposal = StrategyProposal(
        id="proposal-current",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Current covered call",
        proposed_action="sell_covered_call",
        rationale="Current action.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    order_service = Mock()
    service = build_service(
        experiments=FakeExperiments(proposal),
        order_service=order_service,
    )
    order_service.list_trading_intents.return_value = [
        BrokerOrderIntent(
            id="unknown-call-intent",
            trade_action_intent_id="unknown-call-action",
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key="generic-call-key-0001",
            request_hash="request-hash",
            operation=TradingOperation.SUBMIT,
            action="order_submit",
            broker_marker="st:0123456789abcdef",
            state=TradingIntentState.UNKNOWN,
            request_payload={
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "side": "sell",
                "quantity": 1,
                "option_contract": {
                    "underlying_symbol": "UNH.US",
                    "expiration_date": "2026-06-26",
                    "strike": "110",
                    "right": "call",
                },
            },
            created_at=NOW,
            updated_at=NOW,
        )
    ]

    reserved = service._reserved_covered_call_shares(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="UNH.US",
        excluded_proposal_ids={proposal.id},
    )

    assert reserved == 100


def test_covered_call_reserves_short_call_position_imported_as_stock() -> None:
    proposal = StrategyProposal(
        id="proposal-current",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Current covered call",
        proposed_action="sell_covered_call",
        rationale="Current action.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    snapshot = build_snapshot(quantity=Decimal("200"))
    snapshot.positions.append(
        PositionSnapshot(
            symbol="UNH260626C110000.US",
            asset_type=AssetType.STOCK,
            quantity=Decimal("-1"),
            average_cost=Decimal("0.80"),
            market_value=Decimal("-80"),
            unrealized_pnl=Decimal("0"),
        )
    )
    service = build_service(
        snapshot=snapshot,
        experiments=FakeExperiments(proposal),
        order_service=Mock(),
    )

    reserved = service._reserved_covered_call_shares(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="UNH.US",
        excluded_proposal_ids={proposal.id},
    )

    assert reserved == 100


def test_covered_call_execute_blocks_advisor_source_without_local_checks() -> None:
    proposal = StrategyProposal(
        id="proposal-llm",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Advisor-generated proposal.",
        status=StrategyProposalStatus.APPROVED,
        source="deepseek",
        candidate_payload=build_candidate_payload(),
        checks=[],
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(proposal)
    order_service = Mock()
    service = build_service(experiments=experiments, order_service=order_service)

    with pytest.raises(PermissionError, match="advisor-sourced proposal"):
        service.execute_approved_proposal(
            "proposal-llm",
            request=ExecuteCoveredCallProposalRequest(),
        )

    order_service.submit_order.assert_not_called()


def test_covered_call_monitor_records_take_profit_guidance() -> None:
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
        candidate_payload={
            "underlying_symbol": "UNH.US",
            "expiration_date": "2026-06-26",
            "days_to_expiration": 28,
            "contracts": 1,
            "covered_shares": 100,
            "share_quantity": "100",
            "average_cost": "90",
            "underlying_price": "100",
            "call_symbol": "UNH260626C105000.US",
            "call_strike": "105",
            "call_bid": "1.20",
            "call_ask": "1.30",
            "call_mid": "1.25",
            "premium_income": "120.00",
            "delta": "0.30",
            "open_interest": 800,
            "volume": 25,
            "quote_timestamp": "2026-05-29T15:00:00Z",
        },
        created_at=NOW,
        updated_at=NOW,
    )
    adapter = build_adapter()
    adapter.get_option_market_snapshots.return_value = [
        OptionMarketSnapshot(
            symbol="UNH260626C105000.US",
            underlying_symbol="UNH.US",
            expiration_date=date(2026, 6, 26),
            strike=Decimal("105"),
            right=OptionRight.CALL,
            last_done=Decimal("0.55"),
            prev_close=Decimal("1.20"),
            open=Decimal("0.80"),
            high=Decimal("0.90"),
            low=Decimal("0.50"),
            timestamp=NOW,
            volume=20,
            turnover=Decimal("1100"),
            bid=Decimal("0.50"),
            ask=Decimal("0.60"),
            open_interest=700,
            delta=Decimal("0.15"),
        )
    ]
    experiments = FakeExperiments(proposal)
    service = build_service(experiments=experiments, adapter=adapter)

    result = service.monitor_proposal("proposal-1", as_of=NOW)

    assert result.action == "consider_buyback_take_profit"
    assert result.estimated_buyback_debit == Decimal("55.00")
    assert result.estimated_open_pnl == Decimal("65.00")
    assert result.premium_capture_pct == Decimal("54.17")
    assert result.signal is not None
    assert experiments.signal_request.signal_type == StrategySignalType.MONITOR
    assert experiments.signal_request.signal_payload["estimated_open_pnl"] == "65.00"


def test_covered_call_monitor_uses_roll_to_candidate_for_executed_roll() -> None:
    proposal = StrategyProposal(
        id="proposal-2",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Roll covered call on UNH.US",
        proposed_action="roll_covered_call",
        rationale="Executed roll proposal.",
        status=StrategyProposalStatus.EXECUTED,
        candidate_payload={
            "source_proposal_id": "proposal-1",
            "roll_from": build_candidate_payload(),
            "roll_to": build_candidate_payload(
                call_symbol="UNH260710C110000.US",
                expiration_date="2026-07-10",
                call_strike="110",
                call_bid="1.10",
                call_ask="1.20",
                call_mid="1.15",
                premium_income="110.00",
            ),
        },
        created_at=NOW,
        updated_at=NOW,
    )
    adapter = build_adapter()
    adapter.get_option_market_snapshots.return_value = [
        OptionMarketSnapshot(
            symbol="UNH260710C110000.US",
            underlying_symbol="UNH.US",
            expiration_date=date(2026, 7, 10),
            strike=Decimal("110"),
            right=OptionRight.CALL,
            last_done=Decimal("0.55"),
            prev_close=Decimal("1.20"),
            open=Decimal("0.80"),
            high=Decimal("0.90"),
            low=Decimal("0.50"),
            timestamp=NOW,
            volume=20,
            turnover=Decimal("1100"),
            bid=Decimal("0.50"),
            ask=Decimal("0.60"),
            open_interest=700,
            delta=Decimal("0.15"),
        )
    ]
    experiments = FakeExperiments(proposal)
    service = build_service(experiments=experiments, adapter=adapter)

    result = service.monitor_proposal("proposal-2", as_of=NOW)

    assert result.candidate.call_symbol == "UNH260710C110000.US"
    assert result.estimated_buyback_debit == Decimal("55.00")
    adapter.get_option_market_snapshots.assert_called_with(
        symbols=["UNH260710C110000.US"],
        mode=ExecutionMode.PAPER,
    )


def test_covered_call_roll_proposal_records_buyback_and_next_call_candidate() -> None:
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
        candidate_payload={
            "underlying_symbol": "UNH.US",
            "expiration_date": "2026-06-26",
            "days_to_expiration": 28,
            "contracts": 1,
            "covered_shares": 100,
            "share_quantity": "100",
            "average_cost": "90",
            "underlying_price": "100",
            "call_symbol": "UNH260626C105000.US",
            "call_strike": "105",
            "call_bid": "1.20",
            "call_ask": "1.30",
            "call_mid": "1.25",
            "premium_income": "120.00",
            "delta": "0.30",
            "open_interest": 800,
            "volume": 25,
            "quote_timestamp": "2026-05-29T15:00:00Z",
        },
        created_at=NOW,
        updated_at=NOW,
    )
    adapter = build_adapter()
    adapter.list_option_expiry_dates.return_value = [date(2026, 6, 26), date(2026, 7, 10)]
    adapter.list_option_chain.return_value = [
        OptionChainEntry(strike=Decimal("110"), call_symbol="UNH260710C110000.US")
    ]
    adapter.get_option_market_snapshots.side_effect = [
        [
            OptionMarketSnapshot(
                symbol="UNH260626C105000.US",
                underlying_symbol="UNH.US",
                expiration_date=date(2026, 6, 26),
                strike=Decimal("105"),
                right=OptionRight.CALL,
                last_done=Decimal("0.55"),
                prev_close=Decimal("1.20"),
                open=Decimal("0.80"),
                high=Decimal("0.90"),
                low=Decimal("0.50"),
                timestamp=NOW,
                volume=20,
                turnover=Decimal("1100"),
                bid=Decimal("0.50"),
                ask=Decimal("0.60"),
                open_interest=700,
                delta=Decimal("0.15"),
            )
        ],
        [
            OptionMarketSnapshot(
                symbol="UNH260710C110000.US",
                underlying_symbol="UNH.US",
                expiration_date=date(2026, 7, 10),
                strike=Decimal("110"),
                right=OptionRight.CALL,
                last_done=Decimal("1.15"),
                prev_close=Decimal("1.05"),
                open=Decimal("1.00"),
                high=Decimal("1.30"),
                low=Decimal("0.95"),
                timestamp=NOW,
                volume=35,
                turnover=Decimal("4025"),
                bid=Decimal("1.10"),
                ask=Decimal("1.20"),
                open_interest=900,
                delta=Decimal("0.30"),
            )
        ],
    ]
    experiments = FakeExperiments(proposal)
    service = build_service(experiments=experiments, adapter=adapter)

    result = service.create_roll_proposal(
        "proposal-1",
        request=CreateCoveredCallRollProposalRequest(as_of=NOW),
    )

    assert result.proposal is not None
    assert result.proposal.id == "proposal-2"
    assert result.proposal.proposed_action == "roll_covered_call"
    assert result.current_monitor.estimated_buyback_debit == Decimal("55.00")
    assert result.next_preview.candidate is not None
    assert result.next_preview.candidate.call_symbol == "UNH260710C110000.US"
    assert result.proposal.candidate_payload["source_proposal_id"] == "proposal-1"
    assert result.proposal.candidate_payload["roll_from"]["call_symbol"] == "UNH260626C105000.US"
    assert result.proposal.candidate_payload["roll_to"]["call_symbol"] == "UNH260710C110000.US"
    assert experiments.run_request.run_type == "roll_proposal_preview"
    assert experiments.signal_request.signal_type == StrategySignalType.CANDIDATE


def test_covered_call_roll_execute_submits_sell_to_open_after_buyback_fills() -> None:
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
        candidate_payload={
            "roll_from": {
                "underlying_symbol": "UNH.US",
                "expiration_date": "2026-06-26",
                "days_to_expiration": 28,
                "contracts": 1,
                "covered_shares": 100,
                "share_quantity": "100",
                "average_cost": "90",
                "underlying_price": "100",
                "call_symbol": "UNH260626C105000.US",
                "call_strike": "105",
                "call_bid": "1.20",
                "call_ask": "1.30",
                "call_mid": "1.25",
                "premium_income": "120.00",
                "delta": "0.30",
                "open_interest": 800,
                "volume": 25,
                "quote_timestamp": "2026-05-29T15:00:00Z",
            },
            "roll_to": {
                "underlying_symbol": "UNH.US",
                "expiration_date": "2026-07-10",
                "days_to_expiration": 42,
                "contracts": 1,
                "covered_shares": 100,
                "share_quantity": "100",
                "average_cost": "90",
                "underlying_price": "100",
                "call_symbol": "UNH260710C110000.US",
                "call_strike": "110",
                "call_bid": "1.10",
                "call_ask": "1.20",
                "call_mid": "1.15",
                "premium_income": "110.00",
                "delta": "0.30",
                "open_interest": 900,
                "volume": 35,
                "quote_timestamp": "2026-05-29T15:00:00Z",
            },
        },
        created_at=NOW,
        updated_at=NOW,
    )
    source_proposal = proposal.model_copy(
        update={
            "id": "proposal-1",
            "proposed_action": "sell_covered_call",
            "status": StrategyProposalStatus.EXECUTED,
            "candidate_payload": proposal.candidate_payload["roll_from"],
        }
    )
    proposal = proposal.model_copy(
        update={
            "candidate_payload": {
                **proposal.candidate_payload,
                "source_proposal_id": "proposal-1",
            }
        }
    )
    experiments = FakeExperiments([source_proposal, proposal])
    order_service = Mock()
    order_service.submit_order.side_effect = [
        Order(
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
        Order(
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
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    service = build_service(
        experiments=experiments,
        order_service=order_service,
        adapter=build_roll_adapter(),
    )
    configure_parent_action(
        order_service,
        action_id="roll-parent-1",
        idempotency_key="roll-public-key-0001",
    )

    result = service.execute_approved_roll_proposal(
        "proposal-2",
        ExecuteCoveredCallRollProposalRequest(
            buyback_limit_price=Decimal("0.55"),
            sell_limit_price=Decimal("1.10"),
        ),
        idempotency_key="roll-public-key-0001",
    )

    assert result.sequence_status == "roll_filled"
    assert result.proposal.status == StrategyProposalStatus.EXECUTED
    assert result.buyback_order.id == "buyback-order-1"
    assert result.sell_order is not None
    assert result.sell_order.id == "roll-open-order-1"
    assert order_service.submit_order.call_count == 2
    assert {
        call_args.kwargs["parent_action_intent_id"]
        for call_args in order_service.submit_order.call_args_list
    } == {"roll-parent-1"}
    assert {
        call_args.kwargs["action_context"].entity_id
        for call_args in order_service.submit_order.call_args_list
    } == {"proposal-2"}
    child_keys = {
        call_args.kwargs["idempotency_key"]
        for call_args in order_service.submit_order.call_args_list
    }
    assert len(child_keys) == 2
    assert "roll-public-key-0001" not in child_keys
    order_service.complete_trade_action.assert_called_once()
    buyback_request = order_service.submit_order.call_args_list[0].args[0]
    sell_request = order_service.submit_order.call_args_list[1].args[0]
    assert buyback_request.symbol == "UNH260626C105000.US"
    assert buyback_request.side == OrderSide.BUY
    assert sell_request.symbol == "UNH260710C110000.US"
    assert sell_request.side == OrderSide.SELL
    assert experiments.updated_status == StrategyProposalStatus.EXECUTED
    assert experiments.updated_statuses["proposal-1"] == StrategyProposalStatus.ROLLED
    assert experiments.updated_statuses["proposal-2"] == StrategyProposalStatus.EXECUTED
    assert experiments.run_request.run_type == "roll_execution"
    assert experiments.signal_request.signal_type == StrategySignalType.EXECUTION

    order_service.submit_order.reset_mock()
    configure_parent_action(
        order_service,
        action_id="roll-parent-1",
        idempotency_key="roll-public-key-0001",
        created=False,
        state=TradingIntentState.PERSISTED,
        response_payload=result.model_dump(mode="json"),
    )
    replay = service.execute_approved_roll_proposal(
        "proposal-2",
        ExecuteCoveredCallRollProposalRequest(
            buyback_limit_price=Decimal("0.55"),
            sell_limit_price=Decimal("1.10"),
        ),
        idempotency_key="roll-public-key-0001",
    )

    assert replay.model_dump() == result.model_dump()
    assert replay.buyback_order.idempotent_replayed is True
    assert replay.sell_order is not None and replay.sell_order.idempotent_replayed is True
    order_service.submit_order.assert_not_called()

    order_service.prepare_trade_action.side_effect = TradingIntentConflictError("roll-parent-1")
    with pytest.raises(TradingIntentConflictError) as exc_info:
        service.execute_approved_roll_proposal(
            "proposal-2",
            ExecuteCoveredCallRollProposalRequest(
                buyback_limit_price=Decimal("0.55"),
                sell_limit_price=Decimal("1.15"),
            ),
            idempotency_key="roll-public-key-0001",
        )
    assert exc_info.value.intent_id == "roll-parent-1"


def test_covered_call_roll_closes_old_call_before_same_day_gate_blocks_new_sell() -> None:
    proposal = StrategyProposal(
        id="proposal-roll-same-day",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Roll covered call on UNH.US",
        proposed_action="roll_covered_call",
        rationale="Approved roll proposal.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload={
            "roll_from": build_candidate_payload(),
            "roll_to": build_candidate_payload(
                call_symbol="UNH260710C110000.US",
                expiration_date="2026-07-10",
                call_strike="110",
                call_bid="1.10",
                call_ask="1.20",
                call_mid="1.15",
                premium_income="110.00",
            ),
            "source_proposal_id": "proposal-source",
        },
        created_at=NOW,
        updated_at=NOW,
    )
    snapshot = build_snapshot()
    expiry_token = datetime.now(ZoneInfo("America/New_York")).strftime("%y%m%d")
    snapshot.positions.append(
        PositionSnapshot(
            symbol=f"SPY{expiry_token}P600000.US",
            asset_type=AssetType.STOCK,
            quantity=Decimal("1"),
            average_cost=Decimal("1.00"),
            market_value=Decimal("100"),
            unrealized_pnl=Decimal("0"),
        )
    )
    order_service = Mock()
    order_service.submit_order.return_value = Order(
        id="same-day-buyback",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-same-day-buyback",
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
    )
    audit_events = Mock()
    service = build_service(
        snapshot=snapshot,
        experiments=FakeExperiments(proposal),
        order_service=order_service,
        audit_events=audit_events,
    )
    configure_parent_action(
        order_service,
        action_id="roll-parent-same-day",
        idempotency_key="roll-same-day-key-0001",
        entity_id=proposal.id,
    )

    result = service.execute_approved_roll_proposal(
        proposal.id,
        ExecuteCoveredCallRollProposalRequest(
            buyback_limit_price=Decimal("0.55"),
            sell_limit_price=Decimal("1.10"),
        ),
        idempotency_key="roll-same-day-key-0001",
    )

    assert result.sequence_status == "roll_sell_blocked_manual_action"
    assert result.sell_order is None
    assert result.buyback_order.side == OrderSide.BUY
    assert order_service.submit_order.call_count == 1
    assert "Buyback filled" in (result.reason or "")
    warning = audit_events.create_event.call_args.args[0]
    assert warning.warning_code == "same_day_option_position_requires_manual_action"
    order_service.complete_trade_action.assert_called_once()


def test_covered_call_roll_execute_waits_when_buyback_does_not_fill() -> None:
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
        candidate_payload={
            "roll_from": {
                "underlying_symbol": "UNH.US",
                "expiration_date": "2026-06-26",
                "days_to_expiration": 28,
                "contracts": 1,
                "covered_shares": 100,
                "share_quantity": "100",
                "average_cost": "90",
                "underlying_price": "100",
                "call_symbol": "UNH260626C105000.US",
                "call_strike": "105",
                "call_bid": "1.20",
                "call_ask": "1.30",
                "call_mid": "1.25",
                "premium_income": "120.00",
                "delta": "0.30",
                "open_interest": 800,
                "volume": 25,
                "quote_timestamp": "2026-05-29T15:00:00Z",
            },
            "roll_to": {
                "underlying_symbol": "UNH.US",
                "expiration_date": "2026-07-10",
                "days_to_expiration": 42,
                "contracts": 1,
                "covered_shares": 100,
                "share_quantity": "100",
                "average_cost": "90",
                "underlying_price": "100",
                "call_symbol": "UNH260710C110000.US",
                "call_strike": "110",
                "call_bid": "1.10",
                "call_ask": "1.20",
                "call_mid": "1.15",
                "premium_income": "110.00",
                "delta": "0.30",
                "open_interest": 900,
                "volume": 35,
                "quote_timestamp": "2026-05-29T15:00:00Z",
            },
        },
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(proposal)
    order_service = Mock()
    order_service.submit_order.return_value = Order(
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
    )
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.execute_approved_roll_proposal(
        "proposal-2",
        ExecuteCoveredCallRollProposalRequest(
            buyback_limit_price=Decimal("0.55"),
            sell_limit_price=Decimal("1.10"),
        ),
    )

    assert result.sequence_status == "buyback_submitted_waiting_fill"
    assert result.proposal.status == StrategyProposalStatus.APPROVED
    assert result.sell_order is None
    assert result.reason is not None
    assert order_service.submit_order.call_count == 1
    assert experiments.updated_status is None


def test_covered_call_roll_continue_submits_sell_after_buyback_refresh_fills() -> None:
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
        candidate_payload={
            "roll_from": {
                "underlying_symbol": "UNH.US",
                "expiration_date": "2026-06-26",
                "days_to_expiration": 28,
                "contracts": 1,
                "covered_shares": 100,
                "share_quantity": "100",
                "average_cost": "90",
                "underlying_price": "100",
                "call_symbol": "UNH260626C105000.US",
                "call_strike": "105",
                "call_bid": "1.20",
                "call_ask": "1.30",
                "call_mid": "1.25",
                "premium_income": "120.00",
                "delta": "0.30",
                "open_interest": 800,
                "volume": 25,
                "quote_timestamp": "2026-05-29T15:00:00Z",
            },
            "roll_to": {
                "underlying_symbol": "UNH.US",
                "expiration_date": "2026-07-10",
                "days_to_expiration": 42,
                "contracts": 1,
                "covered_shares": 100,
                "share_quantity": "100",
                "average_cost": "90",
                "underlying_price": "100",
                "call_symbol": "UNH260710C110000.US",
                "call_strike": "110",
                "call_bid": "1.10",
                "call_ask": "1.20",
                "call_mid": "1.15",
                "premium_income": "110.00",
                "delta": "0.30",
                "open_interest": 900,
                "volume": 35,
                "quote_timestamp": "2026-05-29T15:00:00Z",
            },
        },
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id="proposal-2",
                run_type="roll_execution",
                order_id="buyback-order-1",
                metrics_payload={"buyback_order_id": "buyback-order-1"},
            )
        ],
    )
    order_service = Mock()
    order_service.refresh_order.return_value = Order(
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
    )
    order_service.submit_order.return_value = Order(
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
        status=OrderStatus.FILLED,
        limit_price=Decimal("1.10"),
        created_at=NOW,
        updated_at=NOW,
    )
    service = build_service(
        experiments=experiments,
        order_service=order_service,
        adapter=build_roll_adapter(),
    )

    result = service.continue_roll_proposal(
        "proposal-2",
        ContinueCoveredCallRollRequest(
            buyback_order_id="buyback-order-1",
            sell_limit_price=Decimal("1.10"),
        ),
    )

    assert result.sequence_status == "roll_filled"
    assert result.proposal.status == StrategyProposalStatus.EXECUTED
    assert result.sell_order is not None
    assert result.sell_order.id == "roll-open-order-1"
    order_service.refresh_order.assert_called_once_with("buyback-order-1")
    sell_request = order_service.submit_order.call_args.args[0]
    assert sell_request.symbol == "UNH260710C110000.US"
    assert sell_request.side == OrderSide.SELL
    assert experiments.updated_status == StrategyProposalStatus.EXECUTED
    assert experiments.run_request.run_type == "roll_continuation"


def test_covered_call_roll_continue_refreshes_existing_sell_order_without_duplicate() -> None:
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
        candidate_payload={
            "source_proposal_id": "proposal-1",
            "roll_from": build_candidate_payload(),
            "roll_to": build_candidate_payload(
                call_symbol="UNH260710C110000.US",
                expiration_date="2026-07-10",
                call_strike="110",
                call_bid="1.10",
                call_ask="1.20",
                call_mid="1.15",
                premium_income="110.00",
            ),
        },
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id="proposal-2",
                run_type="roll_execution",
                order_id="roll-open-order-1",
                metrics_payload={
                    "buyback_order_id": "buyback-order-1",
                    "sell_order_id": "roll-open-order-1",
                },
            )
        ],
    )
    order_service = Mock()
    order_service.refresh_order.side_effect = [
        Order(
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
        Order(
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
    ]
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.continue_roll_proposal(
        "proposal-2",
        ContinueCoveredCallRollRequest(
            buyback_order_id="buyback-order-1",
            sell_order_id="roll-open-order-1",
        ),
    )

    assert result.sequence_status == "roll_sell_submitted_waiting_fill"
    assert result.proposal.status == StrategyProposalStatus.APPROVED
    assert result.sell_order is not None
    assert result.sell_order.id == "roll-open-order-1"
    assert result.reason is not None
    order_service.refresh_order.assert_has_calls([call("buyback-order-1"), call("roll-open-order-1")])
    order_service.submit_order.assert_not_called()
    assert experiments.updated_status is None


def test_covered_call_roll_continue_rejects_orders_not_linked_to_proposal() -> None:
    proposal = StrategyProposal(
        id="proposal-current-roll",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Roll covered call on UNH.US",
        proposed_action="roll_covered_call",
        rationale="Approved roll proposal.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload={
            "source_proposal_id": "proposal-source",
            "roll_from": build_candidate_payload(),
            "roll_to": build_candidate_payload(
                call_symbol="UNH260710C110000.US",
                expiration_date="2026-07-10",
                call_strike="110",
                call_bid="1.10",
                call_ask="1.20",
                call_mid="1.15",
                premium_income="110.00",
            ),
        },
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id=proposal.id,
                run_type="roll_execution",
                order_id="proposal-buyback",
                metrics_payload={
                    "buyback_order_id": "proposal-buyback",
                    "sell_order_id": "proposal-sell",
                },
            )
        ],
    )
    order_service = Mock()
    order_service.refresh_order.side_effect = [
        Order(
            id="foreign-buyback",
            broker=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            external_order_id="external-foreign-buyback",
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
        Order(
            id="foreign-sell",
            broker=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            external_order_id="external-foreign-sell",
            symbol="UNH260710C110000.US",
            asset_type=AssetType.OPTION,
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            mode=ExecutionMode.PAPER,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    service = build_service(experiments=experiments, order_service=order_service)

    with pytest.raises(ValueError, match="not linked to covered call roll proposal"):
        service.continue_roll_proposal(
            proposal.id,
            ContinueCoveredCallRollRequest(
                buyback_order_id="foreign-buyback",
                sell_order_id="foreign-sell",
            ),
        )

    order_service.refresh_order.assert_not_called()
    assert experiments.updated_status is None


def test_covered_call_roll_continue_requires_persisted_run() -> None:
    proposal = build_roll_proposal(proposal_id="roll-proposal-missing-run")
    order_service = Mock()
    service = build_service(
        experiments=FakeExperiments(proposal),
        order_service=order_service,
    )

    with pytest.raises(ValueError, match="no persisted lifecycle run"):
        service.continue_roll_proposal(
            proposal.id,
            ContinueCoveredCallRollRequest(buyback_order_id="buyback-order-1"),
        )

    order_service.refresh_order.assert_not_called()
    order_service.submit_order.assert_not_called()


def test_covered_call_roll_continue_rejects_foreign_sell_only() -> None:
    proposal = build_roll_proposal(proposal_id="roll-proposal-foreign-sell")
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id=proposal.id,
                run_type="roll_execution",
                order_id="linked-sell",
                metrics_payload={
                    "buyback_order_id": "linked-buyback",
                    "sell_order_id": "linked-sell",
                },
            )
        ],
    )
    order_service = Mock()
    service = build_service(experiments=experiments, order_service=order_service)

    with pytest.raises(ValueError, match="Sell order 'foreign-sell'.*not linked"):
        service.continue_roll_proposal(
            proposal.id,
            ContinueCoveredCallRollRequest(
                buyback_order_id="linked-buyback",
                sell_order_id="foreign-sell",
            ),
        )

    order_service.refresh_order.assert_not_called()
    order_service.submit_order.assert_not_called()


def test_covered_call_roll_continue_rejects_omitted_linked_sell() -> None:
    proposal = build_roll_proposal(proposal_id="roll-proposal-omitted-sell")
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id=proposal.id,
                run_type="roll_execution",
                order_id="linked-sell",
                metrics_payload={
                    "buyback_order_id": "linked-buyback",
                    "sell_order_id": "linked-sell",
                },
            )
        ],
    )
    order_service = Mock()
    service = build_service(experiments=experiments, order_service=order_service)

    with pytest.raises(ValueError, match="already has linked sell order"):
        service.continue_roll_proposal(
            proposal.id,
            ContinueCoveredCallRollRequest(buyback_order_id="linked-buyback"),
        )

    order_service.refresh_order.assert_not_called()
    order_service.submit_order.assert_not_called()


def test_covered_call_roll_continue_rejects_order_quantity_mismatch() -> None:
    proposal = build_roll_proposal(proposal_id="roll-proposal-quantity")
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id=proposal.id,
                run_type="roll_execution",
                order_id="linked-sell",
                metrics_payload={
                    "buyback_order_id": "linked-buyback",
                    "sell_order_id": "linked-sell",
                },
            )
        ],
    )
    order_service = Mock()
    order_service.refresh_order.side_effect = [
        build_roll_order(
            order_id="linked-buyback",
            symbol="UNH260626C105000.US",
            side=OrderSide.BUY,
        ),
        build_roll_order(
            order_id="linked-sell",
            symbol="UNH260710C110000.US",
            side=OrderSide.SELL,
            quantity=2,
        ),
    ]
    service = build_service(experiments=experiments, order_service=order_service)

    with pytest.raises(ValueError, match="quantity 2 does not match expected contract quantity 1"):
        service.continue_roll_proposal(
            proposal.id,
            ContinueCoveredCallRollRequest(
                buyback_order_id="linked-buyback",
                sell_order_id="linked-sell",
            ),
        )

    order_service.submit_order.assert_not_called()
    assert experiments.updated_status is None


def test_covered_call_close_submits_buy_to_close_order() -> None:
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
        candidate_payload={
            "underlying_symbol": "UNH.US",
            "expiration_date": "2026-06-26",
            "days_to_expiration": 28,
            "contracts": 1,
            "covered_shares": 100,
            "share_quantity": "100",
            "average_cost": "90",
            "underlying_price": "100",
            "call_symbol": "UNH260626C105000.US",
            "call_strike": "105",
            "call_bid": "1.20",
            "call_ask": "1.30",
            "call_mid": "1.25",
            "premium_income": "120.00",
            "delta": "0.30",
            "open_interest": 800,
            "volume": 25,
            "quote_timestamp": "2026-05-29T15:00:00Z",
        },
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(proposal)
    order_service = Mock()
    order_service.submit_order.return_value = Order(
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
    )
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.close_proposal(
        "proposal-1",
        request=CloseCoveredCallProposalRequest(limit_price=Decimal("0.55")),
    )

    assert result.proposal.status == StrategyProposalStatus.EXECUTED
    assert result.order.id == "order-close-1"
    request = order_service.submit_order.call_args.args[0]
    assert request.symbol == "UNH260626C105000.US"
    assert request.side == OrderSide.BUY
    assert request.limit_price == Decimal("0.55")
    assert experiments.run_request.run_type == "proposal_close"
    assert experiments.signal_request.signal_type == StrategySignalType.EXECUTION
    assert experiments.updated_status is None


def test_covered_call_close_marks_closed_only_after_buyback_fills() -> None:
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
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(proposal)
    order_service = Mock()
    order_service.submit_order.return_value = Order(
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
        status=OrderStatus.FILLED,
        limit_price=Decimal("0.55"),
        created_at=NOW,
        updated_at=NOW,
    )
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.close_proposal(
        "proposal-1",
        request=CloseCoveredCallProposalRequest(limit_price=Decimal("0.55")),
    )

    assert result.proposal.status == StrategyProposalStatus.CLOSED
    assert experiments.updated_status == StrategyProposalStatus.CLOSED


def test_covered_call_lifecycle_reconcile_marks_filled_close_closed() -> None:
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
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(
        proposal,
        runs=[build_strategy_run(proposal_id="proposal-1", run_type="proposal_close", order_id="close-order-1")],
    )
    order_service = Mock()
    order_service.refresh_order.return_value = Order(
        id="close-order-1",
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
        status=OrderStatus.FILLED,
        limit_price=Decimal("0.55"),
        created_at=NOW,
        updated_at=NOW,
    )
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.reconcile_pending_lifecycle(
        external_account_id="LBPT10087357",
        as_of=NOW,
    )

    assert result["close_orders_refreshed"] == 1
    assert result["closed_proposals"] == 1
    assert experiments.updated_status == StrategyProposalStatus.CLOSED
    order_service.refresh_order.assert_called_once_with("close-order-1")


def test_covered_call_lifecycle_reconcile_marks_filled_sell_executed() -> None:
    proposal = StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Approved covered call proposal.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id="proposal-1",
                run_type="proposal_execution",
                order_id="sell-order-1",
                metrics_payload={
                    "order_id": "sell-order-1",
                    "sequence_status": "sell_submitted_waiting_fill",
                    "sell_status": "submitted",
                },
            )
        ],
    )
    order_service = Mock()
    order_service.refresh_order.return_value = Order(
        id="sell-order-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-sell-1",
        symbol="UNH260626C105000.US",
        asset_type=AssetType.OPTION,
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        limit_price=Decimal("1.20"),
        created_at=NOW,
        updated_at=NOW,
    )
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.reconcile_pending_lifecycle(
        external_account_id="LBPT10087357",
        as_of=NOW,
    )

    assert result["sell_orders_refreshed"] == 1
    assert result["sell_orders_executed"] == 1
    assert experiments.updated_status == StrategyProposalStatus.EXECUTED
    order_service.refresh_order.assert_called_once_with("sell-order-1")


def test_covered_call_lifecycle_reconcile_records_working_sell_refresh() -> None:
    proposal = StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Approved covered call proposal.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id="proposal-1",
                run_type="proposal_execution",
                order_id="sell-order-1",
                metrics_payload={
                    "order_id": "sell-order-1",
                    "sequence_status": "sell_submitted_waiting_fill",
                    "sell_status": "submitted",
                },
            )
        ],
    )
    order_service = Mock()
    order_service.refresh_order.return_value = Order(
        id="sell-order-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-sell-1",
        symbol="UNH260626C105000.US",
        asset_type=AssetType.OPTION,
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.SUBMITTED,
        limit_price=Decimal("1.20"),
        submitted_at=NOW - timedelta(minutes=20),
        created_at=NOW,
        updated_at=NOW,
    )
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.reconcile_pending_lifecycle(
        external_account_id="LBPT10087357",
        as_of=NOW,
    )

    assert result["sell_orders_refreshed"] == 1
    assert result["sell_orders_executed"] == 0
    assert experiments.updated_status is None
    assert experiments.run_request.run_type == "open_lifecycle_refresh"
    assert experiments.run_request.order_id == "sell-order-1"
    assert experiments.run_request.metrics_payload["sell_status"] == "submitted"
    assert experiments.run_request.metrics_payload["order_submitted_at"] == (
        NOW - timedelta(minutes=20)
    ).isoformat()


def test_covered_call_lifecycle_reconcile_waits_for_confirmed_roll_continue() -> None:
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
        candidate_payload={
            "source_proposal_id": "proposal-1",
            "roll_from": build_candidate_payload(),
            "roll_to": build_candidate_payload(
                call_symbol="UNH260710C110000.US",
                expiration_date="2026-07-10",
                call_strike="110",
                call_bid="1.10",
                call_ask="1.20",
                call_mid="1.15",
                premium_income="110.00",
            ),
        },
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(
        proposal,
        runs=[
            build_strategy_run(
                proposal_id="proposal-2",
                run_type="roll_execution",
                order_id="buyback-order-1",
                metrics_payload={
                    "buyback_order_id": "buyback-order-1",
                    "sell_order_id": None,
                    "sell_limit_price": "1.10",
                },
            )
        ],
    )
    order_service = Mock()
    order_service.refresh_order.return_value = Order(
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
    )
    order_service.submit_order.return_value = Order(
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
    )
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.reconcile_pending_lifecycle(
        external_account_id="LBPT10087357",
        as_of=NOW,
    )

    assert result["roll_buyback_orders_refreshed"] == 1
    assert result["roll_sell_orders_submitted"] == 0
    assert result["roll_sell_orders_waiting_confirmation"] == 1
    assert result["rolls_executed"] == 0
    assert experiments.updated_status is None
    order_service.submit_order.assert_not_called()


def test_covered_call_lifecycle_reconcile_executes_filled_roll_sell() -> None:
    source_proposal = StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action="sell_covered_call",
        rationale="Executed covered call proposal.",
        status=StrategyProposalStatus.EXECUTED,
        candidate_payload=build_candidate_payload(),
        created_at=NOW,
        updated_at=NOW,
    )
    roll_proposal = StrategyProposal(
        id="proposal-2",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Roll covered call on UNH.US",
        proposed_action="roll_covered_call",
        rationale="Approved roll proposal.",
        status=StrategyProposalStatus.APPROVED,
        candidate_payload={
            "source_proposal_id": "proposal-1",
            "roll_from": build_candidate_payload(),
            "roll_to": build_candidate_payload(
                call_symbol="UNH260710C110000.US",
                expiration_date="2026-07-10",
                call_strike="110",
                call_bid="1.10",
                call_ask="1.20",
                call_mid="1.15",
                premium_income="110.00",
            ),
        },
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = FakeExperiments(
        [source_proposal, roll_proposal],
        runs=[
            build_strategy_run(
                proposal_id="proposal-2",
                run_type="roll_continuation",
                order_id="roll-open-order-1",
                metrics_payload={
                    "buyback_order_id": "buyback-order-1",
                    "sell_order_id": "roll-open-order-1",
                },
            )
        ],
    )
    order_service = Mock()
    order_service.refresh_order.side_effect = [
        Order(
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
        Order(
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
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    service = build_service(experiments=experiments, order_service=order_service)

    result = service.reconcile_pending_lifecycle(
        external_account_id="LBPT10087357",
        as_of=NOW,
    )

    assert result["roll_sell_orders_refreshed"] == 1
    assert result["rolls_executed"] == 1
    assert experiments.updated_statuses["proposal-1"] == StrategyProposalStatus.ROLLED
    assert experiments.updated_statuses["proposal-2"] == StrategyProposalStatus.EXECUTED
    order_service.submit_order.assert_not_called()
