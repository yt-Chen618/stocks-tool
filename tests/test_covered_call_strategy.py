from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from stocks_tool.application.services.covered_call_strategy import CoveredCallStrategyService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    RiskStatus,
    StrategyProposalStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerAccount,
    OptionMarketSnapshot,
    PositionSnapshot,
    SecurityQuoteSnapshot,
    StrategyProposal,
    StrategyRun,
    StrategySignal,
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
    def __init__(self) -> None:
        self.run_request = None
        self.signal_request = None
        self.proposal_request = None

    def create_run(self, request):
        self.run_request = request
        return StrategyRun(
            id="run-1",
            strategy_id=request.strategy_id,
            external_account_id=request.external_account_id,
            mode=request.mode,
            run_type=request.run_type,
            status=request.status,
            symbol=request.symbol,
            summary=request.summary,
            created_at=NOW,
            updated_at=NOW,
        )

    def create_signal(self, request):
        self.signal_request = request
        return StrategySignal(
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

    def create_proposal(self, request):
        self.proposal_request = request
        return StrategyProposal(
            id="proposal-1",
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
        Mock(standard=True, call_symbol="UNH260626C105000.US")
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


def build_service(
    *,
    snapshot: AccountSnapshot | None = None,
    experiments: FakeExperiments | None = None,
) -> CoveredCallStrategyService:
    return CoveredCallStrategyService(
        settings=Settings(),
        broker_accounts=FakeBrokerAccounts(),
        account_snapshots=FakeAccountSnapshots(snapshot or build_snapshot()),
        experiments=experiments or FakeExperiments(),
        longbridge_adapter=build_adapter(),
    )


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
