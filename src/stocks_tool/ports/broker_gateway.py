from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerConfigurationStatus,
    BrokerOrderSnapshot,
    BrokerProfile,
    CreateOrderRequest,
    HistoricalPriceBar,
    OptionChainEntry,
    OptionMarketSnapshot,
    SecurityQuoteSnapshot,
)


@runtime_checkable
class BrokerMarketDataGateway(Protocol):
    def get_quote(self, symbol: str, mode: ExecutionMode) -> SecurityQuoteSnapshot:
        ...

    def get_quotes(self, symbols: list[str], mode: ExecutionMode) -> dict[str, SecurityQuoteSnapshot]:
        ...

    def get_recent_daily_bars(self, symbol: str, count: int, mode: ExecutionMode) -> list[HistoricalPriceBar]:
        ...

    def list_option_expiry_dates(self, symbol: str, mode: ExecutionMode) -> list[date]:
        ...

    def list_option_chain(self, symbol: str, expiry_date: date, mode: ExecutionMode) -> list[OptionChainEntry]:
        ...

    def get_option_market_snapshots(self, symbols: list[str], mode: ExecutionMode) -> list[OptionMarketSnapshot]:
        ...

    def get_best_bid_ask(self, symbol: str, mode: ExecutionMode) -> tuple[Decimal | None, Decimal | None]:
        ...


@runtime_checkable
class BrokerOrderGateway(Protocol):
    def submit_order(self, request: CreateOrderRequest) -> BrokerOrderSnapshot:
        ...

    def get_order(self, external_order_id: str, mode: ExecutionMode) -> BrokerOrderSnapshot:
        ...

    def cancel_order(self, external_order_id: str, mode: ExecutionMode) -> BrokerOrderSnapshot:
        ...

    def replace_order(
        self,
        external_order_id: str,
        *,
        quantity: int,
        limit_price: Decimal | None,
        stop_price: Decimal | None,
        remark: str | None,
        mode: ExecutionMode,
    ) -> BrokerOrderSnapshot:
        ...

    def list_today_orders(
        self,
        mode: ExecutionMode,
        *,
        symbol: str | None = None,
        external_order_id: str | None = None,
    ) -> list[BrokerOrderSnapshot]:
        ...


@runtime_checkable
class BrokerAccountGateway(Protocol):
    def get_profile(self) -> BrokerProfile:
        ...

    def get_configuration_status(self) -> BrokerConfigurationStatus:
        ...

    def build_account_snapshot(
        self,
        external_account_id: str,
        mode: ExecutionMode,
        currency: str | None = None,
        options_level: str | None = None,
    ) -> AccountSnapshot:
        ...


@runtime_checkable
class BrokerIntegrationGateway(BrokerMarketDataGateway, BrokerAccountGateway, Protocol):
    pass


@runtime_checkable
class BrokerGateway(BrokerMarketDataGateway, BrokerOrderGateway, BrokerAccountGateway, Protocol):
    pass
