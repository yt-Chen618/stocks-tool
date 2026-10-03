from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from stocks_tool.domain.enums import (
    AccountSnapshotProvenance,
    AssetType,
    ExecutionMode,
    OrderSide,
    OrderType,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    CreateOrderRequest,
    Order,
    ReplaceOrderRequest,
    TradingActionContext,
)
from stocks_tool.domain.option_symbols import parse_us_option_symbol
from stocks_tool.ports.broker_gateway import BrokerMarketDataGateway
from stocks_tool.ports.repository import AccountSnapshotRepository


DEFAULT_ACCOUNT_SNAPSHOT_MAX_AGE_SECONDS = 120
# Keep generic manual-entry authorization aligned with the documented
# architecture-wide 2% risk ceiling used by strategy risk checks.
DEFAULT_MANUAL_ENTRY_MAX_ACCOUNT_RISK_PCT = Decimal("0.02")
DEFAULT_MANUAL_ENTRY_MAX_QUOTE_AGE_SECONDS = 15
OPTION_CONTRACT_MULTIPLIER = Decimal("100")
ZERO_DTE_EXECUTION_DISABLED_CODE = "zero_dte_execution_disabled_pending_lifecycle"
ZERO_DTE_EXPIRED_CODE = "zero_dte_contract_expired"


class OrderAuthorizationError(ValueError):
    """A deterministic, pre-broker order authorization failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OrderActionClass:
    MANUAL_ENTRY = "manual_entry"
    STRATEGY_ENTRY = "strategy_entry"
    PROTECTIVE = "protective"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AccountSnapshotEvidence:
    snapshot: AccountSnapshot
    age_seconds: int
    mode: ExecutionMode


def classify_order_action(
    action_context: TradingActionContext | None,
) -> str:
    """Classify internal action metadata without relying on order side.

    BUY can mean either a new long entry or a short-leg close, and SELL can
    mean either a new short entry or a long-leg rollback.  The action/leg
    identity is therefore the only safe discriminator available at this seam.
    """

    action = (action_context.action if action_context is not None else "order_submit").strip().lower()
    leg = (action_context.leg if action_context is not None and action_context.leg else "").strip().lower()

    if action == "order_submit":
        return OrderActionClass.MANUAL_ENTRY
    if action in {"bull_put_entry", "covered_call_open"}:
        return OrderActionClass.STRATEGY_ENTRY
    if action == "covered_call_roll" and leg == "roll_sell_open":
        return OrderActionClass.STRATEGY_ENTRY
    if action in {
        "bull_put_exit",
        "bull_put_rollback",
        "bull_put_recover_close",
        "covered_call_close",
    }:
        return OrderActionClass.PROTECTIVE
    if action == "covered_call_roll" and leg == "roll_buyback":
        return OrderActionClass.PROTECTIVE
    return OrderActionClass.UNKNOWN


class OrderAuthorizationService:
    """Pre-broker evidence checks for manual entries and strategy opening legs.

    Existing strategy orchestrators remain authoritative for their own entry
    checks.  This service closes the generic manual-order gap and provides a
    reusable current-account-snapshot check for Covered Call opening legs.
    Protective/rollback actions deliberately do not use manual entry caps.
    """

    def __init__(
        self,
        *,
        account_snapshots: AccountSnapshotRepository,
        market_data: BrokerMarketDataGateway | None = None,
        max_snapshot_age_seconds: int = DEFAULT_ACCOUNT_SNAPSHOT_MAX_AGE_SECONDS,
        max_account_risk_pct: Decimal = DEFAULT_MANUAL_ENTRY_MAX_ACCOUNT_RISK_PCT,
        max_quote_age_seconds: int = DEFAULT_MANUAL_ENTRY_MAX_QUOTE_AGE_SECONDS,
        clock: Any | None = None,
    ) -> None:
        if max_snapshot_age_seconds < 1:
            raise ValueError("max_snapshot_age_seconds must be positive.")
        if max_account_risk_pct <= Decimal("0"):
            raise ValueError("max_account_risk_pct must be positive.")
        if max_quote_age_seconds < 1:
            raise ValueError("max_quote_age_seconds must be positive.")
        self.account_snapshots = account_snapshots
        self.market_data = market_data
        self.max_snapshot_age_seconds = max_snapshot_age_seconds
        self.max_account_risk_pct = max_account_risk_pct
        self.max_quote_age_seconds = max_quote_age_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.new_york = ZoneInfo("America/New_York")

    def require_current_account_snapshot(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        evaluated_at: datetime | None = None,
    ) -> AccountSnapshotEvidence:
        snapshot = self.account_snapshots.get_latest_account_snapshot(
            external_account_id=external_account_id,
            mode=mode,
            trusted_only=True,
        )
        if snapshot is None:
            raise OrderAuthorizationError(
                "account_snapshot_unavailable",
                "A current broker account snapshot is required before this order.",
            )
        if snapshot.account_id.strip() != external_account_id.strip():
            raise OrderAuthorizationError(
                "account_snapshot_account_mismatch",
                "The broker account snapshot does not belong to the selected account.",
            )
        captured_at = self._as_utc(snapshot.captured_at)
        # The local authorization clock is authoritative.  A strategy
        # `as_of` value is research context and must not make old evidence look
        # current by moving the live authorization clock into the past.
        reference = self._as_utc(self.clock())
        age = (reference - captured_at).total_seconds()
        if age < 0:
            raise OrderAuthorizationError(
                "account_snapshot_future",
                "The broker account snapshot timestamp is ahead of the local authorization clock.",
            )
        if age > self.max_snapshot_age_seconds:
            raise OrderAuthorizationError(
                "account_snapshot_stale",
                (
                    "The broker account snapshot is stale; refresh the selected paper account "
                    "before submitting this order."
                ),
            )
        age_seconds = int(age)

        snapshot_mode = self._snapshot_mode(snapshot)
        if snapshot_mode is None:
            raise OrderAuthorizationError(
                "account_snapshot_mode_unknown",
                "The broker account snapshot has no trusted execution-mode provenance.",
            )
        if snapshot_mode != mode.value:
            raise OrderAuthorizationError(
                "account_snapshot_mode_mismatch",
                "The broker account snapshot does not belong to the selected execution mode.",
            )
        provenance = getattr(snapshot, "provenance", None)
        provenance_value = getattr(provenance, "value", provenance)
        if provenance_value != AccountSnapshotProvenance.BROKER_SYNC.value:
            raise OrderAuthorizationError(
                "account_snapshot_untrusted",
                "The account snapshot is not trusted broker-sync evidence.",
            )

        return AccountSnapshotEvidence(snapshot=snapshot, age_seconds=age_seconds, mode=mode)

    def authorize_manual_entry(
        self,
        *,
        request: CreateOrderRequest,
        reserved_quantity: Decimal = Decimal("0"),
        reserved_notional: Decimal = Decimal("0"),
        evaluated_at: datetime | None = None,
    ) -> AccountSnapshotEvidence:
        evidence = self.require_current_account_snapshot(
            external_account_id=request.external_account_id,
            mode=request.mode,
            evaluated_at=evaluated_at,
        )
        snapshot = evidence.snapshot

        parsed_option = parse_us_option_symbol(request.symbol)
        if parsed_option is not None and request.asset_type != AssetType.OPTION:
            raise OrderAuthorizationError(
                "manual_entry_asset_type_mismatch",
                "An option symbol must be submitted with option metadata.",
            )

        if request.asset_type == AssetType.OPTION:
            if request.option_contract is None:
                raise OrderAuthorizationError(
                    "manual_entry_option_contract_required",
                    "Manual option entry requires a concrete option contract.",
                )
            if parsed_option is None or not self._option_contract_matches(request, parsed_option):
                raise OrderAuthorizationError(
                    "manual_entry_option_contract_mismatch",
                    "Manual option entry contract metadata does not match the option symbol.",
                )

        reducing = self._is_position_reducing(
            snapshot,
            request,
            reserved_quantity=reserved_quantity,
        )
        if reducing:
            return evidence

        self._reject_expired_or_zero_dte_entry(request)

        if request.asset_type == AssetType.OPTION:
            if not snapshot.options_level:
                raise OrderAuthorizationError(
                    "manual_entry_options_approval_missing",
                    "Manual option entry requires account options approval.",
                )

        if snapshot.net_liquidation <= Decimal("0"):
            raise OrderAuthorizationError(
                "manual_entry_net_liquidation_unavailable",
                "Manual entry requires a positive account net liquidation value.",
            )
        if snapshot.buying_power <= Decimal("0"):
            raise OrderAuthorizationError(
                "manual_entry_buying_power_unavailable",
                "Manual entry requires positive account buying power.",
            )

        price = self._bounded_order_price(request)
        if price is None:
            raise OrderAuthorizationError(
                "manual_entry_unbounded_risk",
                "Manual market or missing-price entry is not bounded by the current authorization policy.",
            )

        self._require_current_entry_quote(request)

        multiplier = OPTION_CONTRACT_MULTIPLIER if request.asset_type == AssetType.OPTION else Decimal("1")
        estimated_notional = price * Decimal(request.quantity) * multiplier
        available_buying_power = snapshot.buying_power - reserved_notional
        if estimated_notional > available_buying_power:
            raise OrderAuthorizationError(
                "manual_entry_buying_power_exceeded",
                "Manual entry exceeds the current account buying power.",
            )
        risk_budget = (snapshot.net_liquidation * self.max_account_risk_pct) - reserved_notional
        if estimated_notional > risk_budget:
            raise OrderAuthorizationError(
                "manual_entry_account_risk_exceeded",
                "Manual entry exceeds the configured account-risk budget.",
            )
        return evidence

    def authorize_exposure_increasing_replace(
        self,
        *,
        order: Order,
        request: ReplaceOrderRequest,
        reserved_quantity: Decimal = Decimal("0"),
        reserved_notional: Decimal = Decimal("0"),
        evaluated_at: datetime | None = None,
    ) -> AccountSnapshotEvidence:
        replacement = CreateOrderRequest(
            external_account_id=order.external_account_id,
            broker=order.broker,
            symbol=order.symbol,
            asset_type=order.asset_type or AssetType.STOCK,
            side=order.side,
            quantity=request.quantity,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            mode=order.mode,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            option_contract=order.option_contract,
        )
        return self.authorize_manual_entry(
            request=replacement,
            reserved_quantity=reserved_quantity,
            reserved_notional=reserved_notional,
            evaluated_at=evaluated_at,
        )

    def _is_position_reducing(
        self,
        snapshot: AccountSnapshot,
        request: CreateOrderRequest,
        *,
        reserved_quantity: Decimal = Decimal("0"),
    ) -> bool:
        symbol = request.symbol.strip().upper()
        position = next(
            (item for item in snapshot.positions if item.symbol.strip().upper() == symbol),
            None,
        )
        if position is None:
            if request.side == OrderSide.SELL:
                raise OrderAuthorizationError(
                    "manual_entry_short_exposure_unbounded",
                    "Manual sell entry has no matching long position and would create unbounded exposure.",
                )
            return False

        quantity = Decimal(request.quantity)
        available_long = max(Decimal("0"), position.quantity - reserved_quantity)
        available_short = max(Decimal("0"), abs(position.quantity) - reserved_quantity)
        if request.side == OrderSide.SELL and position.quantity > 0 and quantity <= available_long:
            return True
        if request.side == OrderSide.BUY and position.quantity < 0 and quantity <= available_short:
            return True
        if request.side == OrderSide.SELL and position.quantity > 0 and reserved_quantity > 0:
            raise OrderAuthorizationError(
                "manual_entry_position_reserved",
                "Manual sell quantity exceeds the unreserved position after working orders are accounted for.",
            )
        if request.side == OrderSide.BUY and position.quantity < 0 and reserved_quantity > 0:
            raise OrderAuthorizationError(
                "manual_entry_position_reserved",
                "Manual buy quantity exceeds the unreserved short position after working orders are accounted for.",
            )
        if request.side == OrderSide.SELL:
            raise OrderAuthorizationError(
                "manual_entry_short_exposure_unbounded",
                "Manual sell entry would increase short exposure without a bounded close position.",
            )
        return False

    @staticmethod
    def _bounded_order_price(request: CreateOrderRequest) -> Decimal | None:
        price = request.limit_price if request.limit_price is not None else request.stop_price
        if price is None or price <= Decimal("0"):
            return None
        return price

    def _require_current_entry_quote(self, request: CreateOrderRequest) -> datetime:
        if self.market_data is None:
            raise OrderAuthorizationError(
                "manual_entry_quote_unavailable",
                "Manual entry requires current broker quote evidence.",
            )
        try:
            if request.asset_type == AssetType.OPTION:
                quotes = self.market_data.get_option_market_snapshots(
                    symbols=[request.symbol],
                    mode=request.mode,
                )
                normalized_symbol = request.symbol.strip().upper()
                quote = next(
                    (item for item in quotes if item.symbol.strip().upper() == normalized_symbol),
                    None,
                )
                if quote is None:
                    raise LookupError("No current option quote was returned.")
                timestamp = quote.timestamp
            else:
                quote = self.market_data.get_quote(symbol=request.symbol, mode=request.mode)
                if quote.data_quality != "live" or quote.warning_code is not None:
                    raise LookupError("Broker quote evidence is cached or degraded.")
                timestamp = quote.timestamp
        except OrderAuthorizationError:
            raise
        except Exception as exc:
            raise OrderAuthorizationError(
                "manual_entry_quote_unavailable",
                "Manual entry requires current broker quote evidence.",
            ) from exc

        quote_time = self._as_utc(timestamp)
        reference = self._as_utc(self.clock())
        age = (reference - quote_time).total_seconds()
        if age < 0:
            raise OrderAuthorizationError(
                "manual_entry_quote_future",
                "Broker quote timestamp is ahead of the local authorization clock.",
            )
        if age > self.max_quote_age_seconds:
            raise OrderAuthorizationError(
                "manual_entry_quote_stale",
                "Broker quote evidence is stale for manual entry.",
            )
        return quote_time

    def _reject_expired_or_zero_dte_entry(self, request: CreateOrderRequest) -> None:
        if request.option_contract is None:
            return
        today = self._as_utc(self.clock()).astimezone(self.new_york).date()
        expiration = request.option_contract.expiration_date
        if expiration < today:
            raise OrderAuthorizationError(
                ZERO_DTE_EXPIRED_CODE,
                "Expired option contracts cannot be opened.",
            )
        if expiration == today:
            raise OrderAuthorizationError(
                ZERO_DTE_EXECUTION_DISABLED_CODE,
                "Zero-DTE execution remains disabled until expiry and assignment handling is implemented.",
            )

    @staticmethod
    def _option_contract_matches(request: CreateOrderRequest, parsed: Any) -> bool:
        contract = request.option_contract
        if contract is None:
            return False
        right = "C" if contract.right.value == "call" else "P"
        return (
            contract.underlying_symbol.strip().upper() == parsed.underlying_symbol
            and contract.expiration_date == parsed.expiration_date
            and contract.strike == parsed.strike
            and right == parsed.right
        )

    @staticmethod
    def _snapshot_mode(snapshot: AccountSnapshot) -> str | None:
        explicit_mode = getattr(snapshot, "mode", None)
        if explicit_mode is not None:
            value = getattr(explicit_mode, "value", explicit_mode)
            return str(value).strip().lower() or None
        return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def is_exposure_increasing_replace(order: Order, request: ReplaceOrderRequest, action_class: str) -> bool:
    """Return whether a replacement needs fresh entry authorization."""

    if action_class == OrderActionClass.PROTECTIVE:
        return False
    if action_class == OrderActionClass.UNKNOWN:
        return True
    if action_class in {OrderActionClass.MANUAL_ENTRY, OrderActionClass.STRATEGY_ENTRY}:
        return True
    if request.quantity > order.quantity:
        return True

    old_price = order.limit_price if order.limit_price is not None else order.stop_price
    new_price = request.limit_price if request.limit_price is not None else request.stop_price
    if old_price is None or new_price is None:
        return old_price != new_price
    if order.side == OrderSide.BUY:
        return new_price > old_price
    return False


def action_class_from_intent(intent: Any | None) -> str:
    if intent is None:
        return OrderActionClass.UNKNOWN
    return classify_order_action(
        TradingActionContext(
            action=str(getattr(intent, "action", "")),
            strategy_id=getattr(intent, "strategy_id", None),
            entity_id=getattr(intent, "entity_id", None),
            leg=getattr(intent, "leg", None),
        )
    )


__all__ = [
    "AccountSnapshotEvidence",
    "DEFAULT_ACCOUNT_SNAPSHOT_MAX_AGE_SECONDS",
    "DEFAULT_MANUAL_ENTRY_MAX_ACCOUNT_RISK_PCT",
    "DEFAULT_MANUAL_ENTRY_MAX_QUOTE_AGE_SECONDS",
    "ZERO_DTE_EXECUTION_DISABLED_CODE",
    "ZERO_DTE_EXPIRED_CODE",
    "OrderActionClass",
    "OrderAuthorizationError",
    "OrderAuthorizationService",
    "action_class_from_intent",
    "classify_order_action",
    "is_exposure_increasing_replace",
]
