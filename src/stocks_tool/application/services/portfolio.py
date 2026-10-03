"""Read-only portfolio analytics and risk aggregation.

This service deliberately builds its read model from persisted local records.  It
does not call a broker and it never writes to the order, execution, or journal
ledgers.  Missing cash-flow, fee, Greeks, mode, or provenance data is represented
as an unavailable field instead of being turned into a zero or an inferred value.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from stocks_tool.db.models import (
    AccountSnapshotRecord,
    BullPutSpreadRecord,
    ExecutionRecord,
    JournalEntryRecord,
    OrderRecord,
    PositionSnapshotRecord,
    StrategyProposalRecord,
    StrategyRunRecord,
)
from stocks_tool.domain.option_symbols import parse_us_option_symbol
from stocks_tool.domain.enums import ExecutionMode


DEFAULT_MAX_POINTS = 500
MAX_MAX_POINTS = 2_000
# Kept as a named compatibility constant for callers that imported it before
# SQL row sampling was added.  It is no longer used as a history truncation
# limit; requested chart points bound the sampled rows instead.
SNAPSHOT_QUERY_LIMIT = MAX_MAX_POINTS
ACTIVITY_LIMIT = 200
EVIDENCE_ID_LIMIT = 100
STALE_AFTER = timedelta(hours=24)
ACTIVE_COVERED_CALL_STATUSES = ("pending", "approved", "executed")
ACTIVE_BULL_PUT_STATUSES = (
    "entry_pending_long",
    "entry_pending_short",
    "open",
    "exit_pending_short",
    "exit_pending_long",
    "rollback_failed",
)


class PortfolioUnavailable(BaseModel):
    """A value that could not be computed from the available evidence."""

    model_config = ConfigDict(extra="forbid")

    code: str
    reason: str


class PortfolioEvidence(BaseModel):
    """Bounded references supporting a read-model result."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime | None = None
    snapshot_ids: list[str] = Field(default_factory=list)
    position_ids: list[str] = Field(default_factory=list)
    order_ids: list[str] = Field(default_factory=list)
    execution_ids: list[str] = Field(default_factory=list)
    journal_ids: list[str] = Field(default_factory=list)
    journal_ids_unscoped: list[str] = Field(default_factory=list)
    strategy_proposal_ids: list[str] = Field(default_factory=list)
    strategy_run_ids: list[str] = Field(default_factory=list)
    bull_put_spread_ids: list[str] = Field(default_factory=list)
    truncated: bool = False


class PortfolioDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warnings: list[str] = Field(default_factory=list)
    unavailable: list[PortfolioUnavailable] = Field(default_factory=list)
    snapshot_count: int = 0
    snapshot_count_in_range: int = 0
    chart_downsampled: bool = False
    snapshot_stale: bool = False
    mode_scope_verified: bool = True
    provenance_verified: bool = False
    provenance_counts: dict[str, int] = Field(default_factory=dict)
    provenance_complete: bool = False
    legacy_unscoped_snapshot_count: int = 0


class PortfolioBalance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    captured_at: datetime
    currency: str | None
    net_liquidation: Decimal
    cash_balance: Decimal
    buying_power: Decimal
    day_trade_buying_power: Decimal | None = None
    position_market_value: Decimal | None = None
    position_market_value_available: bool = True
    stale: bool = False
    provenance: str | None = None


class PortfolioTimePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    captured_at: datetime
    currency: str | None
    provenance: str | None = None
    net_liquidation: Decimal
    cash_balance: Decimal
    buying_power: Decimal
    position_market_value: Decimal | None = None
    snapshot_id: str
    source_snapshot_id: str


class PortfolioChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_at: datetime | None = None
    to_at: datetime | None = None
    net_liquidation_change: Decimal | None = None
    cash_balance_change: Decimal | None = None
    buying_power_change: Decimal | None = None
    investment_return: Decimal | None = None
    investment_return_unavailable: PortfolioUnavailable | None = None


class AllocationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    asset_type: str
    quantity: Decimal
    market_value: Decimal
    absolute_market_value: Decimal
    weight_of_net_liquidation: Decimal | None = None
    weight_unavailable: PortfolioUnavailable | None = None
    unrealized_pnl: Decimal | None = None
    option_underlying_symbol: str | None = None
    option_expiration_date: date | None = None
    option_strike: Decimal | None = None
    option_right: str | None = None
    contract_multiplier: Decimal | None = None
    contract_units: Decimal | None = None
    contract_metadata_unavailable: PortfolioUnavailable | None = None
    position_ids: list[str] = Field(default_factory=list)


class StrategyExposure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    label: str
    symbol: str | None = None
    exposure_value: Decimal | None = None
    known_max_loss: Decimal | None = None
    known_max_profit: Decimal | None = None
    contracts: Decimal | None = None
    reserved_shares: Decimal | None = None
    expiration_date: date | None = None
    status: str | None = None
    unavailable: list[PortfolioUnavailable] = Field(default_factory=list)
    evidence: PortfolioEvidence = Field(default_factory=PortfolioEvidence)


class CoveredShareReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    strategy_id: str = "covered_call_v1"
    underlying_symbol: str | None = None
    call_symbol: str | None = None
    reserved_shares: Decimal | None = None
    expiration_date: date | None = None
    proposal_status: str
    unavailable: list[PortfolioUnavailable] = Field(default_factory=list)
    evidence: PortfolioEvidence = Field(default_factory=PortfolioEvidence)


class CoveredShareReservationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    underlying_symbol: str | None = None
    expiration_date: date | None = None
    reserved_shares: Decimal | None = None
    reservation_count: int = 0
    unavailable: list[PortfolioUnavailable] = Field(default_factory=list)
    proposal_ids: list[str] = Field(default_factory=list)


class PortfolioLinks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orders: list[str] = Field(default_factory=list)
    executions: list[str] = Field(default_factory=list)
    journals: list[str] = Field(default_factory=list)
    journal_ids_unscoped: list[str] = Field(default_factory=list)
    strategy_proposals: list[str] = Field(default_factory=list)
    strategy_runs: list[str] = Field(default_factory=list)
    bull_put_spreads: list[str] = Field(default_factory=list)
    unavailable: list[PortfolioUnavailable] = Field(default_factory=list)
    truncated: bool = False


class PortfolioAnalytics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_account_id: str
    mode: ExecutionMode
    currency: str | None = "USD"
    as_of: datetime | None = None
    latest: PortfolioBalance | None = None
    series: list[PortfolioTimePoint] = Field(default_factory=list)
    allocation: list[AllocationItem] = Field(default_factory=list)
    strategy_exposures: list[StrategyExposure] = Field(default_factory=list)
    change: PortfolioChange = Field(default_factory=PortfolioChange)
    links: PortfolioLinks = Field(default_factory=PortfolioLinks)
    evidence: PortfolioEvidence = Field(default_factory=PortfolioEvidence)
    data_quality: PortfolioDataQuality = Field(default_factory=PortfolioDataQuality)


class ConcentrationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    market_value: Decimal
    absolute_market_value: Decimal
    weight_of_net_liquidation: Decimal | None = None
    weight_unavailable: PortfolioUnavailable | None = None
    risk_level: Literal["normal", "watch", "unknown"] = "normal"
    source_position_ids: list[str] = Field(default_factory=list)


class KnownMaxLoss(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # This is intentionally a Bull Put-only total.  It is not a whole-account
    # maximum loss estimate.
    scope: Literal["bull_put"] = "bull_put"
    total: Decimal | None = None
    loss_currency: str | None = None
    nav_currency: str | None = None
    nav_ratio_pct: Decimal | None = None
    nav_ratio_unavailable: PortfolioUnavailable | None = None
    components: list[StrategyExposure] = Field(default_factory=list)
    known_component_count: int = 0
    unknown_component_count: int = 0
    unknown_sources: list[str] = Field(default_factory=list)
    not_included_sources: list[str] = Field(
        default_factory=lambda: [
            "stock_or_etf_downside",
            "covered_call_assignment",
            "unpriced_option_risk",
            "fees",
        ]
    )
    unavailable: PortfolioUnavailable | None = None


class PortfolioRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_account_id: str
    mode: ExecutionMode
    currency: str | None = "USD"
    as_of: datetime | None = None
    balance: PortfolioBalance | None = None
    concentrations: list[ConcentrationItem] = Field(default_factory=list)
    strategy_exposures: list[StrategyExposure] = Field(default_factory=list)
    known_max_loss: KnownMaxLoss = Field(default_factory=KnownMaxLoss)
    covered_share_reservations: list[CoveredShareReservation] = Field(default_factory=list)
    covered_share_groups: list[CoveredShareReservationGroup] = Field(default_factory=list)
    links: PortfolioLinks = Field(default_factory=PortfolioLinks)
    evidence: PortfolioEvidence = Field(default_factory=PortfolioEvidence)
    data_quality: PortfolioDataQuality = Field(default_factory=PortfolioDataQuality)


class PortfolioAnalyticsService:
    """Build bounded account analytics from local persisted evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session
        # A service instance is request-scoped.  These flags let the bounded
        # read model say when a list is display-limited while keeping aggregate
        # risk calculations fail-closed.
        self._strategy_exposure_truncated = False
        self._reservation_truncated = False
        self._active_bull_put_count = 0
        self._active_bull_put_max_loss_total: Decimal | None = None
        self._active_bull_put_missing_max_loss = 0

    def get_analytics(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        start: datetime | None = None,
        end: datetime | None = None,
        max_points: int = DEFAULT_MAX_POINTS,
    ) -> PortfolioAnalytics:
        self._strategy_exposure_truncated = False
        self._reservation_truncated = False
        self._active_bull_put_count = 0
        self._active_bull_put_max_loss_total = None
        self._active_bull_put_missing_max_loss = 0
        account_id = self._normalize_account_id(external_account_id)
        start, end = self._normalize_window(start, end)
        max_points = max(1, min(max_points, MAX_MAX_POINTS))
        snapshots, total_in_range, total_all, quality = self._load_snapshots(
            account_id,
            mode,
            start=start,
            end=end,
            max_points=max_points,
        )

        # Read positions only for the latest snapshot in the selected window.
        # Historical chart rows carry a SQL position total and do not trigger an
        # ORM lazy load for every historical positions collection.
        latest = self._load_latest_snapshot(
            account_id,
            mode,
            as_of=end,
            since=start,
        )
        if latest is not None:
            snapshots_by_id = {record.id: record for record in snapshots}
            snapshots_by_id[latest.id] = latest
            snapshots = sorted(
                snapshots_by_id.values(),
                key=lambda record: (record.captured_at, record.id),
            )

        series_snapshots = self._downsample_snapshots(snapshots, max_points)
        if len(series_snapshots) != len(snapshots):
            quality.chart_downsampled = True
            self._append_warning(quality.warnings, "chart_downsampled")
        if total_in_range > len(snapshots):
            quality.chart_downsampled = True
            self._append_warning(quality.warnings, "snapshot_history_bounded")

        if latest is not None:
            quality.snapshot_stale = self._is_stale(latest.captured_at)
            if quality.snapshot_stale:
                self._append_warning(quality.warnings, "snapshot_stale")

        currency = self._currency_value(latest.currency) if latest is not None else "USD"
        latest_balance = self._balance(latest) if latest is not None else None
        series = [self._time_point(record) for record in series_snapshots]
        allocation, allocation_unavailable = self._allocation(latest)
        for item in allocation_unavailable:
            self._append_unavailable(quality.unavailable, item)

        change = self._change(snapshots)
        if (
            change.investment_return_unavailable is not None
            and change.investment_return_unavailable.code
            in {"mixed_currency_history", "currency_unavailable"}
        ):
            self._append_warning(quality.warnings, change.investment_return_unavailable.code)
        if total_all == 0:
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="account_snapshot_unavailable",
                    reason="No account snapshots are available for this account and mode.",
                ),
            )
        # Historical snapshot tables predate mode/provenance migration.  Keep
        # this explicit in the read model until the migration has populated it.
        self._check_snapshot_provenance(quality, latest)
        self._append_unavailable(
            quality.unavailable,
            PortfolioUnavailable(
                code="fee_history_unavailable",
                reason="Persisted fee history is unavailable; fees are not treated as zero.",
            ),
        )
        if self._has_option_positions(latest):
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="greeks_unavailable",
                    reason="Persisted Greeks are unavailable for one or more option positions.",
                ),
            )

        strategy_exposures = self._strategy_exposures(account_id, mode)
        links = self._activity_links(account_id, mode)
        for item in links.unavailable:
            self._append_unavailable(quality.unavailable, item)
        if self._strategy_exposure_truncated:
            self._append_warning(quality.warnings, "active_risk_components_bounded")
        if self._reservation_truncated:
            self._append_warning(quality.warnings, "covered_call_reservations_bounded")
        evidence = self._evidence_from_snapshots(snapshots, latest, links)
        return PortfolioAnalytics(
            external_account_id=account_id,
            mode=mode,
            currency=currency,
            as_of=latest.captured_at if latest is not None else None,
            latest=latest_balance,
            series=series,
            allocation=allocation,
            strategy_exposures=strategy_exposures,
            change=change,
            links=links,
            evidence=evidence,
            data_quality=quality,
        )

    def get_risk(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        as_of: datetime | None = None,
        max_items: int = 100,
    ) -> PortfolioRisk:
        self._strategy_exposure_truncated = False
        self._reservation_truncated = False
        self._active_bull_put_count = 0
        self._active_bull_put_max_loss_total = None
        self._active_bull_put_missing_max_loss = 0
        account_id = self._normalize_account_id(external_account_id)
        if as_of is not None:
            raise ValueError(
                "Historical portfolio risk is unavailable because strategy exposures are not persisted as point-in-time records."
            )
        max_items = max(1, min(max_items, EVIDENCE_ID_LIMIT))
        latest = self._load_latest_snapshot(account_id, mode, as_of=as_of)
        quality = PortfolioDataQuality()
        quality.legacy_unscoped_snapshot_count = self._legacy_unscoped_snapshot_count(account_id)
        if quality.legacy_unscoped_snapshot_count:
            self._append_warning(quality.warnings, "snapshot_mode_unknown")
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="snapshot_mode_unknown",
                    reason=(
                        f"{quality.legacy_unscoped_snapshot_count} retained snapshot(s) have no confirmed execution mode "
                        "and are excluded from paper/live calculations."
                    ),
                ),
            )
        if latest is None:
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="account_snapshot_unavailable",
                    reason="No account snapshot is available for this account and mode.",
                ),
            )
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="fee_history_unavailable",
                    reason="Persisted fee history is unavailable; fees are not treated as zero.",
                ),
            )
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="concentration_unavailable",
                    reason="A current account snapshot is required to calculate position concentration.",
                ),
            )
            strategy_exposures = self._strategy_exposures(account_id, mode, max_items=max_items)
            known_max_loss = self._known_max_loss(strategy_exposures)
            reservations, groups = self._covered_share_reservations(
                account_id,
                mode,
                max_items=max_items,
            )
            links = self._activity_links(account_id, mode, max_items=max_items)
            for item in links.unavailable:
                self._append_unavailable(quality.unavailable, item)
            if self._strategy_exposure_truncated:
                self._append_warning(quality.warnings, "active_risk_components_bounded")
                if self._active_bull_put_count > max_items:
                    if self._active_bull_put_missing_max_loss:
                        known_max_loss.total = None
                    elif self._active_bull_put_max_loss_total is not None:
                        known_max_loss.total = self._active_bull_put_max_loss_total
                    known_max_loss.known_component_count = max(
                        0,
                        self._active_bull_put_count - self._active_bull_put_missing_max_loss,
                    )
                    known_max_loss.unknown_component_count = self._active_bull_put_missing_max_loss
                    known_max_loss.unknown_sources = (
                        ["bull_put_max_loss"] if self._active_bull_put_missing_max_loss else []
                    )
                    known_max_loss.unavailable = PortfolioUnavailable(
                        code="active_risk_components_bounded",
                        reason="The active Bull Put list exceeded the display bound; components are truncated even when an aggregate is available.",
                    )
            if self._reservation_truncated:
                self._append_warning(quality.warnings, "covered_call_reservations_bounded")
            known_max_loss = self._with_nav_ratio(known_max_loss, None)
            return PortfolioRisk(
                external_account_id=account_id,
                mode=mode,
                as_of=None,
                strategy_exposures=strategy_exposures,
                known_max_loss=known_max_loss,
                covered_share_reservations=reservations,
                covered_share_groups=groups,
                links=links,
                evidence=self._evidence_from_snapshots([], None, links),
                data_quality=quality,
            )

        quality.snapshot_stale = self._is_stale(latest.captured_at)
        if quality.snapshot_stale:
            self._append_warning(quality.warnings, "snapshot_stale")
        self._check_snapshot_provenance(quality, latest)
        self._append_unavailable(
            quality.unavailable,
            PortfolioUnavailable(
                code="fee_history_unavailable",
                reason="Persisted fee history is unavailable; fees are not treated as zero.",
            ),
        )
        if self._has_option_positions(latest):
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="greeks_unavailable",
                    reason="Persisted Greeks are unavailable for one or more option positions.",
                ),
            )
        balance = self._balance(latest)
        concentrations, concentration_unavailable = self._concentrations(latest, max_items)
        for item in concentration_unavailable:
            self._append_unavailable(quality.unavailable, item)

        strategy_exposures = self._strategy_exposures(account_id, mode, max_items=max_items)
        known_max_loss = self._known_max_loss(strategy_exposures)
        reservations, groups = self._covered_share_reservations(
            account_id,
            mode,
            max_items=max_items,
        )
        links = self._activity_links(account_id, mode, max_items=max_items)
        for item in links.unavailable:
            self._append_unavailable(quality.unavailable, item)
        if self._strategy_exposure_truncated:
            self._append_warning(quality.warnings, "active_risk_components_bounded")
            if self._active_bull_put_count > max_items:
                if self._active_bull_put_missing_max_loss:
                    known_max_loss.total = None
                elif self._active_bull_put_max_loss_total is not None:
                    known_max_loss.total = self._active_bull_put_max_loss_total
                known_max_loss.known_component_count = max(
                    0,
                    self._active_bull_put_count - self._active_bull_put_missing_max_loss,
                )
                known_max_loss.unknown_component_count = self._active_bull_put_missing_max_loss
                known_max_loss.unknown_sources = (
                    ["bull_put_max_loss"] if self._active_bull_put_missing_max_loss else []
                )
                known_max_loss.unavailable = PortfolioUnavailable(
                    code="active_risk_components_bounded",
                    reason="The active Bull Put list exceeded the display bound; components are truncated even when an aggregate is available.",
                )
        if self._reservation_truncated:
            self._append_warning(quality.warnings, "covered_call_reservations_bounded")
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="covered_call_reservations_bounded",
                    reason="The active Covered Call reservation list exceeded the display bound.",
                ),
            )
        known_max_loss = self._with_nav_ratio(known_max_loss, balance)
        evidence = self._evidence_from_snapshots([latest], latest, links)
        return PortfolioRisk(
            external_account_id=account_id,
            mode=mode,
            currency=self._currency_value(latest.currency),
            as_of=latest.captured_at,
            balance=balance,
            concentrations=concentrations,
            strategy_exposures=strategy_exposures,
            known_max_loss=known_max_loss,
            covered_share_reservations=reservations,
            covered_share_groups=groups,
            links=links,
            evidence=evidence,
            data_quality=quality,
        )

    def _load_snapshots(
        self,
        account_id: str,
        mode: ExecutionMode,
        *,
        start: datetime | None,
        end: datetime | None,
        max_points: int = DEFAULT_MAX_POINTS,
    ) -> tuple[list[AccountSnapshotRecord], int, int, PortfolioDataQuality]:
        quality = PortfolioDataQuality()
        max_points = max(1, min(max_points, MAX_MAX_POINTS))
        filters = self._snapshot_filters(account_id, mode, start=start, end=end)
        count_query = select(func.count(AccountSnapshotRecord.id)).where(*filters)
        total_in_range = int(self.session.execute(count_query).scalar_one() or 0)
        total_all_query = select(func.count(AccountSnapshotRecord.id)).where(
            *self._snapshot_filters(account_id, mode)
        )
        total_all = int(self.session.execute(total_all_query).scalar_one() or 0)
        quality.legacy_unscoped_snapshot_count = self._legacy_unscoped_snapshot_count(
            account_id,
            start=start,
            end=end,
        )
        if quality.legacy_unscoped_snapshot_count:
            self._append_warning(quality.warnings, "snapshot_mode_unknown")
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="snapshot_mode_unknown",
                    reason=(
                        f"{quality.legacy_unscoped_snapshot_count} retained snapshot(s) have no confirmed execution mode "
                        "and are excluded from paper/live calculations."
                    ),
                ),
            )

        provenance_rows = self.session.execute(
            select(
                AccountSnapshotRecord.provenance,
                func.count(AccountSnapshotRecord.id).label("provenance_count"),
            )
            .where(*filters)
            .group_by(AccountSnapshotRecord.provenance)
        ).all()
        quality.provenance_counts = {
            str(row.provenance or "unknown"): int(row.provenance_count or 0)
            for row in provenance_rows
        }
        quality.provenance_complete = bool(quality.provenance_counts) and not any(
            key in {"legacy_unknown", "unknown", "None"}
            for key in quality.provenance_counts
        )
        quality.provenance_verified = quality.provenance_complete
        if not quality.provenance_complete and total_in_range:
            self._append_warning(quality.warnings, "snapshot_provenance_partial")
            self._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="snapshot_provenance_partial",
                    reason="At least one snapshot in the selected history has unknown provenance.",
                ),
            )

        # Rank rows in SQL and fetch only evenly spaced row numbers.  This
        # preserves true first/middle/last points for a chart while avoiding
        # an in-memory load of the whole account history.
        if total_in_range <= max_points:
            sample_query = (
                select(AccountSnapshotRecord.id)
                .where(*filters)
                .order_by(AccountSnapshotRecord.captured_at.asc(), AccountSnapshotRecord.id.asc())
            )
            sample_ids = [str(item) for item in self.session.execute(sample_query).scalars().all()]
        else:
            ranked = (
                select(
                    AccountSnapshotRecord.id.label("snapshot_id"),
                    func.row_number()
                    .over(
                        order_by=(
                            AccountSnapshotRecord.captured_at.asc(),
                            AccountSnapshotRecord.id.asc(),
                        )
                    )
                    .label("row_number"),
                )
                .where(*filters)
                .subquery()
            )
            if max_points == 1:
                positions = [total_in_range]
            else:
                positions = [
                    1 + round(index * (total_in_range - 1) / (max_points - 1))
                    for index in range(max_points)
                ]
            sampled_rows = self.session.execute(
                select(ranked.c.snapshot_id, ranked.c.row_number)
                .where(ranked.c.row_number.in_(positions))
                .order_by(ranked.c.row_number.asc())
            ).all()
            sample_ids = [str(row.snapshot_id) for row in sampled_rows]
            quality.chart_downsampled = True
            self._append_warning(quality.warnings, "snapshot_history_bounded")

        if sample_ids:
            records_by_id = {
                record.id: record
                for record in self.session.execute(
                    select(AccountSnapshotRecord).where(AccountSnapshotRecord.id.in_(sample_ids))
                ).scalars().all()
            }
            position_totals = {
                str(row.account_snapshot_id): (
                    Decimal(row.position_market_value)
                    if row.position_market_value is not None
                    else Decimal("0")
                )
                for row in self.session.execute(
                    select(
                        PositionSnapshotRecord.account_snapshot_id,
                        func.sum(PositionSnapshotRecord.market_value).label("position_market_value"),
                    )
                    .where(PositionSnapshotRecord.account_snapshot_id.in_(sample_ids))
                    .group_by(PositionSnapshotRecord.account_snapshot_id)
                ).all()
            }
            records = [
                records_by_id[snapshot_id]
                for snapshot_id in sample_ids
                if snapshot_id in records_by_id
            ]
            for record in records:
                record._portfolio_position_market_value = position_totals.get(
                    record.id,
                    Decimal("0"),
                )
        else:
            records = []
        quality.snapshot_count = total_all
        quality.snapshot_count_in_range = total_in_range
        quality.mode_scope_verified = True
        return records, total_in_range, total_all, quality

    def _legacy_unscoped_snapshot_count(
        self,
        account_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        filters: list[Any] = [
            AccountSnapshotRecord.external_account_id == account_id,
            AccountSnapshotRecord.execution_mode.is_(None),
        ]
        if start is not None:
            filters.append(AccountSnapshotRecord.captured_at >= start)
        if end is not None:
            filters.append(AccountSnapshotRecord.captured_at <= end)
        return int(
            self.session.execute(
                select(func.count(AccountSnapshotRecord.id)).where(*filters)
            ).scalar_one()
            or 0
        )

    def _load_latest_snapshot(
        self,
        account_id: str,
        mode: ExecutionMode,
        *,
        as_of: datetime | None = None,
        since: datetime | None = None,
    ) -> AccountSnapshotRecord | None:
        filters = self._snapshot_filters(account_id, mode)
        if since is not None:
            filters.append(AccountSnapshotRecord.captured_at >= since)
        if as_of is not None:
            filters.append(AccountSnapshotRecord.captured_at <= as_of)
        query = (
            select(AccountSnapshotRecord)
            .options(selectinload(AccountSnapshotRecord.positions))
            .where(*filters)
            .order_by(AccountSnapshotRecord.captured_at.desc(), AccountSnapshotRecord.id.desc())
            .limit(1)
        )
        return self.session.execute(query).scalars().unique().first()

    def _snapshot_filters(
        self,
        account_id: str,
        mode: ExecutionMode,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Any]:
        filters: list[Any] = [
            AccountSnapshotRecord.external_account_id == account_id,
            AccountSnapshotRecord.execution_mode == mode.value,
        ]
        if start is not None:
            filters.append(AccountSnapshotRecord.captured_at >= start)
        if end is not None:
            filters.append(AccountSnapshotRecord.captured_at <= end)
        return filters

    @staticmethod
    def _provenance_value(record: Any) -> str | None:
        if record is None:
            return None
        for name in ("provenance", "source", "capture_source", "snapshot_source"):
            value = getattr(record, name, None)
            if value is not None and str(value).strip():
                return str(getattr(value, "value", value))
        return None

    @staticmethod
    def _currency_value(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(getattr(value, "value", value)).strip().upper()
        return normalized or None

    @staticmethod
    def _normalize_account_id(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("external_account_id must not be blank")
        return normalized

    @staticmethod
    def _normalize_window(
        start: datetime | None,
        end: datetime | None,
    ) -> tuple[datetime | None, datetime | None]:
        if start is not None and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start is not None and end is not None and start > end:
            raise ValueError("start must be earlier than or equal to end")
        return start, end

    @staticmethod
    def _is_stale(captured_at: datetime) -> bool:
        now = datetime.now(timezone.utc)
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        return now - captured_at > STALE_AFTER

    @staticmethod
    def _balance(record: AccountSnapshotRecord) -> PortfolioBalance:
        position_value = PortfolioAnalyticsService._position_market_value(record)
        provenance = PortfolioAnalyticsService._provenance_value(record)
        return PortfolioBalance(
            snapshot_id=record.id,
            captured_at=record.captured_at,
            currency=record.currency,
            net_liquidation=Decimal(record.net_liquidation),
            cash_balance=Decimal(record.cash_balance),
            buying_power=Decimal(record.buying_power),
            day_trade_buying_power=(
                Decimal(record.day_trade_buying_power)
                if record.day_trade_buying_power is not None
                else None
            ),
            position_market_value=position_value,
            position_market_value_available=True,
            stale=PortfolioAnalyticsService._is_stale(record.captured_at),
            provenance=provenance,
        )

    @staticmethod
    def _has_option_positions(record: AccountSnapshotRecord | None) -> bool:
        if record is None:
            return False
        return any(
            str(getattr(position, "asset_type", "")).lower() == "option"
            for position in list(getattr(record, "positions", []) or [])
        )

    @staticmethod
    def _time_point(record: AccountSnapshotRecord) -> PortfolioTimePoint:
        position_value = PortfolioAnalyticsService._position_market_value(record)
        return PortfolioTimePoint(
            captured_at=record.captured_at,
            currency=PortfolioAnalyticsService._currency_value(record.currency),
            provenance=PortfolioAnalyticsService._provenance_value(record),
            net_liquidation=Decimal(record.net_liquidation),
            cash_balance=Decimal(record.cash_balance),
            buying_power=Decimal(record.buying_power),
            position_market_value=position_value,
            snapshot_id=record.id,
            source_snapshot_id=record.id,
        )

    @staticmethod
    def _position_market_value(record: AccountSnapshotRecord) -> Decimal:
        sampled_value = getattr(record, "_portfolio_position_market_value", None)
        if sampled_value is not None:
            return Decimal(sampled_value)
        positions = list(getattr(record, "positions", []) or [])
        return sum((Decimal(position.market_value) for position in positions), Decimal("0"))

    @staticmethod
    def _downsample_snapshots(
        snapshots: list[AccountSnapshotRecord],
        max_points: int,
    ) -> list[AccountSnapshotRecord]:
        if len(snapshots) <= max_points:
            return snapshots
        if max_points == 1:
            return [snapshots[-1]]
        # Preserve both endpoints.  The chart is a presentation view; latest
        # allocation/risk always comes from the un-downsampled latest record.
        positions = [round(index * (len(snapshots) - 1) / (max_points - 1)) for index in range(max_points)]
        return [snapshots[index] for index in positions]

    @staticmethod
    def _change(snapshots: list[AccountSnapshotRecord]) -> PortfolioChange:
        if len(snapshots) < 2:
            return PortfolioChange(
                from_at=snapshots[0].captured_at if snapshots else None,
                to_at=snapshots[-1].captured_at if snapshots else None,
                investment_return_unavailable=PortfolioUnavailable(
                    code="cash_flow_history_unavailable",
                    reason="Investment return requires complete cash-flow history; NAV change is shown separately.",
                ),
            )
        first, last = snapshots[0], snapshots[-1]
        currencies = {
            PortfolioAnalyticsService._currency_value(getattr(record, "currency", None))
            for record in snapshots
        }
        if None in currencies:
            return PortfolioChange(
                from_at=first.captured_at,
                to_at=last.captured_at,
                investment_return_unavailable=PortfolioUnavailable(
                    code="currency_unavailable",
                    reason="NAV changes are unavailable when one or more snapshots have no currency.",
                ),
            )
        if len(currencies) > 1:
            return PortfolioChange(
                from_at=first.captured_at,
                to_at=last.captured_at,
                investment_return_unavailable=PortfolioUnavailable(
                    code="mixed_currency_history",
                    reason="NAV changes are unavailable when the selected snapshots use different currencies.",
                ),
            )
        return PortfolioChange(
            from_at=first.captured_at,
            to_at=last.captured_at,
            net_liquidation_change=Decimal(last.net_liquidation) - Decimal(first.net_liquidation),
            cash_balance_change=Decimal(last.cash_balance) - Decimal(first.cash_balance),
            buying_power_change=Decimal(last.buying_power) - Decimal(first.buying_power),
            investment_return_unavailable=PortfolioUnavailable(
                code="cash_flow_history_unavailable",
                reason="Investment return requires complete cash-flow history; NAV change is shown separately.",
            ),
        )

    def _allocation(
        self,
        record: AccountSnapshotRecord | None,
    ) -> tuple[list[AllocationItem], list[PortfolioUnavailable]]:
        if record is None:
            return [], [
                PortfolioUnavailable(
                    code="allocation_unavailable",
                    reason="A latest account snapshot is required to calculate allocation.",
                )
            ]
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for position in list(getattr(record, "positions", []) or []):
            asset_type = str(getattr(position.asset_type, "value", position.asset_type))
            key = (str(position.symbol).upper(), asset_type)
            item = grouped.setdefault(
                key,
                {
                    "quantity": Decimal("0"),
                    "market_value": Decimal("0"),
                    "unrealized_pnl": Decimal("0"),
                    "position_ids": [],
                    "metadata": position,
                },
            )
            item["quantity"] += Decimal(position.quantity)
            item["market_value"] += Decimal(position.market_value)
            item["unrealized_pnl"] += Decimal(position.unrealized_pnl)
            if getattr(position, "id", None):
                item["position_ids"].append(str(position.id))
        nav = Decimal(record.net_liquidation)
        result: list[AllocationItem] = []
        unavailable: list[PortfolioUnavailable] = []
        for (symbol, asset_type), item in sorted(grouped.items()):
            market_value = item["market_value"]
            weight = None
            weight_unavailable = None
            if nav > 0:
                weight = abs(market_value) / nav
            else:
                weight_unavailable = PortfolioUnavailable(
                    code="non_positive_net_liquidation",
                    reason="Position concentration is unavailable when net liquidation is not positive.",
                )
                unavailable.append(weight_unavailable)
            position = item["metadata"]
            contract_multiplier, contract_units, contract_unavailable = self._option_contract_metadata(
                position,
                symbol=symbol,
                asset_type=asset_type,
            )
            if contract_unavailable is not None:
                unavailable.append(contract_unavailable)
            result.append(
                AllocationItem(
                    symbol=symbol,
                    asset_type=asset_type,
                    quantity=item["quantity"],
                    market_value=market_value,
                    absolute_market_value=abs(market_value),
                    weight_of_net_liquidation=weight,
                    weight_unavailable=weight_unavailable,
                    unrealized_pnl=item["unrealized_pnl"],
                    option_underlying_symbol=getattr(position, "option_underlying_symbol", None),
                    option_expiration_date=getattr(position, "option_expiration_date", None),
                    option_strike=(
                        Decimal(position.option_strike)
                        if getattr(position, "option_strike", None) is not None
                        else None
                    ),
                    option_right=getattr(position, "option_right", None),
                    contract_multiplier=contract_multiplier,
                    contract_units=contract_units,
                    contract_metadata_unavailable=contract_unavailable,
                    position_ids=item["position_ids"],
                )
            )
        return result, unavailable

    @staticmethod
    def _option_contract_metadata(
        position: Any,
        *,
        symbol: str,
        asset_type: str,
    ) -> tuple[Decimal | None, Decimal | None, PortfolioUnavailable | None]:
        if asset_type.lower() != "option":
            return None, None, None
        # A compact Longbridge US option symbol is the canonical local parser
        # for right/expiry/strike.  Standard US contracts carry 100 shares;
        # retain the raw market value and expose units separately so a chart
        # never silently applies a multiplier to broker-reported value.
        parsed = parse_us_option_symbol(symbol)
        if parsed is None:
            return (
                None,
                None,
                PortfolioUnavailable(
                    code="option_contract_metadata_unavailable",
                    reason="The option symbol could not be parsed, so contract units are not estimated.",
                ),
            )
        multiplier = Decimal("100")
        return multiplier, abs(Decimal(position.quantity)) * multiplier, None

    def _concentrations(
        self,
        record: AccountSnapshotRecord,
        max_items: int,
    ) -> tuple[list[ConcentrationItem], list[PortfolioUnavailable]]:
        allocations, unavailable = self._allocation(record)
        ordered = sorted(allocations, key=lambda item: item.absolute_market_value, reverse=True)
        concentrations = []
        for item in ordered[:max_items]:
            weight = item.weight_of_net_liquidation
            level: Literal["normal", "watch", "unknown"] = "unknown" if weight is None else (
                "watch" if weight >= Decimal("0.25") else "normal"
            )
            concentrations.append(
                ConcentrationItem(
                    symbol=item.symbol,
                    market_value=item.market_value,
                    absolute_market_value=item.absolute_market_value,
                    weight_of_net_liquidation=weight,
                    weight_unavailable=item.weight_unavailable,
                    risk_level=level,
                    source_position_ids=item.position_ids,
                )
            )
        return concentrations, unavailable

    def _strategy_exposures(
        self,
        account_id: str,
        mode: ExecutionMode,
        *,
        max_items: int = EVIDENCE_ID_LIMIT,
    ) -> list[StrategyExposure]:
        exposures: list[StrategyExposure] = []
        spread_filters = (
            BullPutSpreadRecord.external_account_id == account_id,
            BullPutSpreadRecord.execution_mode == mode.value,
            BullPutSpreadRecord.status.in_(ACTIVE_BULL_PUT_STATUSES),
        )
        spread_summary = self.session.execute(
            select(
                func.count(BullPutSpreadRecord.id),
                func.sum(BullPutSpreadRecord.max_loss),
                func.count(BullPutSpreadRecord.max_loss),
            ).where(*spread_filters)
        ).one()
        spread_count = int(spread_summary[0] or 0)
        max_loss_count = int(spread_summary[2] or 0)
        self._active_bull_put_count = spread_count
        self._active_bull_put_max_loss_total = (
            Decimal(spread_summary[1]) if spread_summary[1] is not None else Decimal("0")
        )
        self._active_bull_put_missing_max_loss = max(0, spread_count - max_loss_count)
        if spread_count > max_items:
            self._strategy_exposure_truncated = True
        spreads = self.session.execute(
            select(BullPutSpreadRecord)
            .where(*spread_filters)
            .order_by(BullPutSpreadRecord.expiration_date.asc(), BullPutSpreadRecord.id.asc())
            .limit(max_items)
        ).scalars().all()
        for spread in spreads:
            known_max_loss = Decimal(spread.max_loss) if spread.max_loss is not None else None
            unavailable = []
            if known_max_loss is None:
                unavailable.append(
                    PortfolioUnavailable(
                        code="bull_put_max_loss_unavailable",
                        reason="This Bull Put spread has no persisted max-loss amount.",
                    )
                )
            exposures.append(
                StrategyExposure(
                    strategy_id=spread.strategy_id,
                    label="Bull Put spread",
                    symbol=spread.underlying_symbol,
                    exposure_value=(
                        Decimal(spread.max_loss) if spread.max_loss is not None else None
                    ),
                    known_max_loss=known_max_loss,
                    known_max_profit=(
                        Decimal(spread.max_profit) if spread.max_profit is not None else None
                    ),
                    contracts=Decimal(spread.contracts),
                    expiration_date=spread.expiration_date,
                    status=spread.status,
                    unavailable=unavailable,
                    evidence=PortfolioEvidence(
                        as_of=spread.last_synced_at or spread.updated_at,
                        bull_put_spread_ids=[spread.id],
                    ),
                )
            )

        reservations, _ = self._covered_share_reservations(
            account_id,
            mode,
            max_items=max_items,
        )
        for reservation in reservations:
            exposures.append(
                StrategyExposure(
                    strategy_id=reservation.strategy_id,
                    label="Covered Call reservation",
                    symbol=reservation.underlying_symbol,
                    reserved_shares=reservation.reserved_shares,
                    expiration_date=reservation.expiration_date,
                    status=reservation.proposal_status,
                    unavailable=reservation.unavailable,
                    evidence=reservation.evidence,
                )
            )
        if len(exposures) > max_items:
            self._strategy_exposure_truncated = True
        return exposures[:max_items]

    def _known_max_loss(self, exposures: list[StrategyExposure]) -> KnownMaxLoss:
        bull_put_exposures = [
            item
            for item in exposures
            if item.label == "Bull Put spread" or item.strategy_id.startswith("paper_bull_put")
        ]
        components = [item for item in bull_put_exposures if item.known_max_loss is not None]
        unknown_count = len(bull_put_exposures) - len(components)
        if unknown_count:
            return KnownMaxLoss(
                total=None,
                components=components,
                known_component_count=len(components),
                unknown_component_count=unknown_count,
                unknown_sources=["bull_put_max_loss"],
                unavailable=PortfolioUnavailable(
                    code="bull_put_max_loss_partial",
                    reason="At least one active Bull Put spread lacks a persisted max-loss amount.",
                ),
            )
        if not components:
            return KnownMaxLoss(
                total=None,
                components=[],
                known_component_count=0,
                unknown_component_count=0,
                unknown_sources=[],
                unavailable=PortfolioUnavailable(
                    code="bull_put_no_active_exposure",
                    reason="No active Bull Put spread has a known max-loss amount.",
                ),
            )
        return KnownMaxLoss(
            total=sum((item.known_max_loss or Decimal("0") for item in components), Decimal("0")),
            components=components,
            known_component_count=len(components),
            unknown_component_count=0,
            unknown_sources=[],
        )

    @staticmethod
    def _with_nav_ratio(
        known_max_loss: KnownMaxLoss,
        balance: PortfolioBalance | None,
    ) -> KnownMaxLoss:
        """Add a comparable USD Bull Put loss/NAV ratio, or explain why not."""
        has_bull_put_amount = (
            known_max_loss.total is not None
            or known_max_loss.known_component_count > 0
            or known_max_loss.unknown_component_count > 0
        )
        loss_currency = "USD" if has_bull_put_amount else None
        nav_currency = PortfolioAnalyticsService._currency_value(
            balance.currency if balance is not None else None
        )
        if not has_bull_put_amount:
            reason = PortfolioUnavailable(
                code="bull_put_max_loss_unavailable",
                reason="There is no known Bull Put max-loss amount to compare with NAV.",
            )
        elif balance is None or balance.net_liquidation <= 0:
            reason = PortfolioUnavailable(
                code="nav_ratio_non_positive_or_unavailable",
                reason="A positive account NAV is required before comparing known Bull Put loss with NAV.",
            )
        elif nav_currency is None:
            reason = PortfolioUnavailable(
                code="nav_currency_unavailable",
                reason="The account NAV currency is missing, so USD Bull Put loss cannot be compared safely.",
            )
        elif nav_currency != loss_currency:
            reason = PortfolioUnavailable(
                code="nav_currency_mismatch",
                reason=f"Known Bull Put loss is {loss_currency}, while account NAV is {nav_currency}; FX conversion is unavailable.",
            )
        elif known_max_loss.total is None:
            reason = PortfolioUnavailable(
                code="bull_put_max_loss_partial",
                reason="Known Bull Put max loss is incomplete, so its NAV ratio is unavailable.",
            )
        else:
            return known_max_loss.model_copy(
                update={
                    "loss_currency": loss_currency,
                    "nav_currency": nav_currency,
                    "nav_ratio_pct": (
                        known_max_loss.total / balance.net_liquidation * Decimal("100")
                    ),
                    "nav_ratio_unavailable": None,
                }
            )
        return known_max_loss.model_copy(
            update={
                "loss_currency": loss_currency,
                "nav_currency": nav_currency,
                "nav_ratio_pct": None,
                "nav_ratio_unavailable": reason,
            }
        )

    def _covered_share_reservations(
        self,
        account_id: str,
        mode: ExecutionMode,
        *,
        max_items: int,
    ) -> tuple[list[CoveredShareReservation], list[CoveredShareReservationGroup]]:
        proposal_filters = (
            StrategyProposalRecord.external_account_id == account_id,
            StrategyProposalRecord.execution_mode == mode.value,
            StrategyProposalRecord.strategy_id == "covered_call_v1",
            StrategyProposalRecord.status.in_(ACTIVE_COVERED_CALL_STATUSES),
            StrategyProposalRecord.proposed_action.in_(("sell_covered_call", "roll_covered_call")),
        )
        proposal_count = int(
            self.session.execute(
                select(func.count(StrategyProposalRecord.id)).where(*proposal_filters)
            ).scalar_one()
            or 0
        )
        if proposal_count > max_items:
            self._reservation_truncated = True
        proposals = self.session.execute(
            select(StrategyProposalRecord)
            .where(*proposal_filters)
            .order_by(StrategyProposalRecord.updated_at.desc(), StrategyProposalRecord.id.desc())
            .limit(max_items)
        ).scalars().all()
        reservations: list[CoveredShareReservation] = []
        groups: dict[tuple[str | None, date | None], CoveredShareReservationGroup] = {}
        for proposal in proposals:
            candidate = self._covered_call_candidate_payload(proposal)
            unavailable: list[PortfolioUnavailable] = []
            if candidate is None:
                unavailable.append(
                    PortfolioUnavailable(
                        code="covered_call_reservation_unreadable",
                        reason="The active Covered Call proposal has no valid candidate payload.",
                    )
                )
            underlying = self._candidate_field(candidate, "underlying_symbol")
            call_symbol = self._candidate_field(candidate, "call_symbol")
            covered_shares = self._decimal_candidate_field(candidate, "covered_shares")
            if candidate is not None and covered_shares is None:
                unavailable.append(
                    PortfolioUnavailable(
                        code="covered_call_shares_unavailable",
                        reason="The active Covered Call proposal has no valid non-negative covered_shares value.",
                    )
                )
            expiration = self._candidate_date(candidate, "expiration_date")
            evidence = PortfolioEvidence(
                as_of=proposal.updated_at,
                strategy_proposal_ids=[proposal.id],
            )
            reservation = CoveredShareReservation(
                proposal_id=proposal.id,
                underlying_symbol=underlying,
                call_symbol=call_symbol,
                reserved_shares=covered_shares,
                expiration_date=expiration,
                proposal_status=proposal.status,
                unavailable=unavailable,
                evidence=evidence,
            )
            reservations.append(reservation)
            key = (underlying, expiration)
            group = groups.setdefault(
                key,
                CoveredShareReservationGroup(
                    underlying_symbol=underlying,
                    expiration_date=expiration,
                ),
            )
            group.reservation_count += 1
            group.proposal_ids.append(proposal.id)
            if unavailable:
                for item in unavailable:
                    if not any(existing.code == item.code for existing in group.unavailable):
                        group.unavailable.append(item)
            if covered_shares is None:
                group.reserved_shares = None
            elif group.reserved_shares is not None:
                group.reserved_shares = (group.reserved_shares or Decimal("0")) + covered_shares
            if len(group.proposal_ids) > max_items:
                group.proposal_ids = group.proposal_ids[:max_items]
        return reservations, list(groups.values())[:max_items]

    @staticmethod
    def _covered_call_candidate_payload(proposal: StrategyProposalRecord) -> dict[str, Any] | None:
        payload = proposal.candidate_payload
        if not isinstance(payload, dict):
            return None
        if proposal.proposed_action == "sell_covered_call":
            return payload
        if proposal.proposed_action == "roll_covered_call":
            roll_to = payload.get("roll_to")
            return roll_to if isinstance(roll_to, dict) else None
        return None

    @staticmethod
    def _candidate_field(candidate: dict[str, Any] | None, key: str) -> str | None:
        if not candidate:
            return None
        value = candidate.get(key)
        return str(value).strip().upper() if value is not None and str(value).strip() else None

    @staticmethod
    def _decimal_candidate_field(candidate: dict[str, Any] | None, key: str) -> Decimal | None:
        if not candidate or candidate.get(key) is None:
            return None
        try:
            value = Decimal(str(candidate[key]))
        except (ArithmeticError, TypeError, ValueError):
            return None
        return value if value >= 0 else None

    @staticmethod
    def _candidate_date(candidate: dict[str, Any] | None, key: str) -> date | None:
        if not candidate or candidate.get(key) is None:
            return None
        value = candidate[key]
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def _activity_links(
        self,
        account_id: str,
        mode: ExecutionMode,
        *,
        max_items: int = EVIDENCE_ID_LIMIT,
    ) -> PortfolioLinks:
        strategy_proposals = self.session.execute(
            select(StrategyProposalRecord.id)
            .where(
                StrategyProposalRecord.external_account_id == account_id,
                StrategyProposalRecord.execution_mode == mode.value,
            )
            .order_by(StrategyProposalRecord.updated_at.desc(), StrategyProposalRecord.id.desc())
            .limit(ACTIVITY_LIMIT)
        ).scalars().all()
        strategy_runs = self.session.execute(
            select(StrategyRunRecord.id)
            .where(
                StrategyRunRecord.external_account_id == account_id,
                StrategyRunRecord.execution_mode == mode.value,
            )
            .order_by(StrategyRunRecord.created_at.desc(), StrategyRunRecord.id.desc())
            .limit(ACTIVITY_LIMIT)
        ).scalars().all()
        spreads = self.session.execute(
            select(BullPutSpreadRecord.id)
            .where(
                BullPutSpreadRecord.external_account_id == account_id,
                BullPutSpreadRecord.execution_mode == mode.value,
            )
            .order_by(BullPutSpreadRecord.updated_at.desc(), BullPutSpreadRecord.id.desc())
            .limit(ACTIVITY_LIMIT)
        ).scalars().all()

        orders_query = (
            select(OrderRecord)
            .join(
                # broker_account_id is the authoritative local account link.
                # Use external account as a second guard when the link exists.
                OrderRecord.broker_account,
            )
            .where(
                OrderRecord.execution_mode == mode.value,
                OrderRecord.broker_account.has(external_account_id=account_id),
            )
            .order_by(OrderRecord.created_at.desc(), OrderRecord.id.desc())
            .limit(ACTIVITY_LIMIT)
        )
        orders = list(self.session.execute(orders_query).scalars().all())
        order_ids = [str(item.id) for item in orders[:max_items]]

        executions = []
        if order_ids:
            executions = list(
                self.session.execute(
                    select(ExecutionRecord)
                    .join(OrderRecord, ExecutionRecord.order_id == OrderRecord.id)
                    .where(
                        ExecutionRecord.external_account_id == account_id,
                        OrderRecord.execution_mode == mode.value,
                        ExecutionRecord.order_id.in_(order_ids),
                    )
                    .order_by(ExecutionRecord.created_at.desc(), ExecutionRecord.id.desc())
                    .limit(ACTIVITY_LIMIT)
                ).scalars().all()
            )
        execution_ids = [str(item.id) for item in executions[:max_items]]

        journal_rows = list(
            self.session.execute(
                select(JournalEntryRecord)
                .where(JournalEntryRecord.external_account_id == account_id)
                .order_by(JournalEntryRecord.created_at.desc(), JournalEntryRecord.id.desc())
                .limit(ACTIVITY_LIMIT)
            ).scalars().all()
        )
        journal_ids: list[str] = []
        journal_ids_unscoped: list[str] = []
        journal_unavailable: list[PortfolioUnavailable] = []
        foreign_mode_journals = 0
        for journal in journal_rows:
            linked_mode = None
            if journal.order_id:
                linked_mode = self.session.execute(
                    select(OrderRecord.execution_mode).where(OrderRecord.id == journal.order_id)
                ).scalar_one_or_none()
            elif journal.execution_id:
                linked_mode = self.session.execute(
                    select(OrderRecord.execution_mode)
                    .join(ExecutionRecord, ExecutionRecord.order_id == OrderRecord.id)
                    .where(ExecutionRecord.id == journal.execution_id)
                ).scalar_one_or_none()
            if linked_mode == mode.value:
                if len(journal_ids) < max_items:
                    journal_ids.append(str(journal.id))
            elif linked_mode is None:
                if len(journal_ids_unscoped) < max_items:
                    journal_ids_unscoped.append(str(journal.id))
            else:
                foreign_mode_journals += 1
        if journal_ids_unscoped:
            journal_unavailable.append(
                PortfolioUnavailable(
                    code="journal_mode_unavailable",
                    reason="Some journal entries have no order or execution with a verifiable execution mode.",
                )
            )
        if foreign_mode_journals:
            journal_unavailable.append(
                PortfolioUnavailable(
                    code="journal_foreign_mode_excluded",
                    reason="Journal entries linked to another execution mode were excluded from this read model.",
                )
            )
        return PortfolioLinks(
            orders=order_ids,
            executions=execution_ids,
            journals=journal_ids,
            journal_ids_unscoped=journal_ids_unscoped,
            strategy_proposals=[str(item) for item in strategy_proposals[:max_items]],
            strategy_runs=[str(item) for item in strategy_runs[:max_items]],
            bull_put_spreads=[str(item) for item in spreads[:max_items]],
            unavailable=journal_unavailable,
            truncated=any(
                len(items) >= ACTIVITY_LIMIT
                for items in (strategy_proposals, strategy_runs, spreads, orders, executions, journal_rows)
            ),
        )

    @staticmethod
    def _evidence_from_snapshots(
        snapshots: list[AccountSnapshotRecord],
        latest: AccountSnapshotRecord | None,
        links: PortfolioLinks,
    ) -> PortfolioEvidence:
        snapshot_ids = [str(record.id) for record in snapshots]
        position_ids = [
            str(position.id)
            for record in snapshots
            for position in list(getattr(record, "positions", []) or [])
            if getattr(position, "id", None)
        ]
        return PortfolioEvidence(
            as_of=latest.captured_at if latest is not None else None,
            snapshot_ids=snapshot_ids[:EVIDENCE_ID_LIMIT],
            position_ids=position_ids[:EVIDENCE_ID_LIMIT],
            order_ids=list(links.orders),
            execution_ids=list(links.executions),
            journal_ids=list(links.journals),
            journal_ids_unscoped=list(links.journal_ids_unscoped),
            strategy_proposal_ids=list(links.strategy_proposals),
            strategy_run_ids=list(links.strategy_runs),
            bull_put_spread_ids=list(links.bull_put_spreads),
            truncated=(
                len(snapshot_ids) > EVIDENCE_ID_LIMIT
                or len(position_ids) > EVIDENCE_ID_LIMIT
                or links.truncated
            ),
        )

    @staticmethod
    def _check_snapshot_provenance(
        quality: PortfolioDataQuality,
        latest: AccountSnapshotRecord | None,
    ) -> None:
        quality.mode_scope_verified = True
        provenance = PortfolioAnalyticsService._provenance_value(latest) if latest is not None else None
        # ``legacy_unknown`` is a real persisted value, but it is deliberately
        # not considered verified provenance.  Public uploads are identifiable
        # evidence, while broker-derived authorization remains a separate
        # broker_sync concern outside this read-only service.
        latest_verified = provenance in {"broker_sync", "public_upload"}
        if quality.provenance_counts:
            quality.provenance_verified = quality.provenance_complete and latest_verified
        else:
            quality.provenance_verified = latest_verified
        if not latest_verified:
            PortfolioAnalyticsService._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="snapshot_provenance_unavailable",
                    reason="The snapshot does not expose a persisted capture provenance value.",
                ),
            )
        elif quality.provenance_counts and not quality.provenance_complete:
            PortfolioAnalyticsService._append_unavailable(
                quality.unavailable,
                PortfolioUnavailable(
                    code="snapshot_provenance_partial",
                    reason="At least one snapshot in the selected history has unknown provenance.",
                ),
            )

    @staticmethod
    def _append_warning(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)

    @staticmethod
    def _append_unavailable(values: list[PortfolioUnavailable], value: PortfolioUnavailable) -> None:
        if not any(item.code == value.code for item in values):
            values.append(value)
