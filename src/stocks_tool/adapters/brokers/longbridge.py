from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import logging
import threading
import time
from typing import Any

from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerOrderSnapshot,
    BrokerCapability,
    BrokerConfigurationStatus,
    CreateOrderRequest,
    HistoricalPriceBar,
    OptionChainEntry,
    OptionMarketSnapshot,
    PositionSnapshot,
    BrokerProfile,
    SecurityQuoteSnapshot,
    SessionQuote,
)
from stocks_tool.ports.broker import BrokerAdapter

logger = logging.getLogger(__name__)


class LongbridgeIntegrationError(RuntimeError):
    pass


class LongbridgeDependencyError(LongbridgeIntegrationError):
    pass


class LongbridgeConfigurationError(LongbridgeIntegrationError):
    pass


class LongbridgeBrokerAdapter(BrokerAdapter):
    _QUOTE_CACHE_TTL_SECONDS = 60

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, self.settings.longbridge_executor_max_workers),
            thread_name_prefix="longbridge-sdk",
        )
        self._circuit_lock = threading.Lock()
        self._circuit_open_until = 0.0
        self._circuit_reason = ""
        self._quote_cache_lock = threading.Lock()
        self._quote_cache: dict[tuple[str, str], tuple[float, SecurityQuoteSnapshot]] = {}

    @property
    def name(self) -> BrokerName:
        return BrokerName.LONGBRIDGE

    def get_profile(self) -> BrokerProfile:
        return BrokerProfile(
            name=self.name,
            supported_modes=[ExecutionMode.PAPER, ExecutionMode.LIVE],
            capabilities=[
                BrokerCapability(
                    name="us_equity_trading",
                    supported=True,
                    notes="Official OpenAPI supports US stocks and ETFs.",
                ),
                BrokerCapability(
                    name="us_options_trading",
                    supported=True,
                    notes="Official OpenAPI supports US options, subject to account approval.",
                ),
                BrokerCapability(
                    name="paper_trading",
                    supported=True,
                    notes="Paper trading is suitable for first-pass order workflow validation.",
                ),
                BrokerCapability(
                    name="order_status_push",
                    supported=True,
                    notes="Order status can be consumed from WebSocket push channels.",
                ),
                BrokerCapability(
                    name="live_execution_guard",
                    supported=True,
                    notes="This codebase keeps live execution behind an environment switch.",
                ),
            ],
        )

    def get_configuration_status(self) -> BrokerConfigurationStatus:
        return BrokerConfigurationStatus(
            broker=self.name,
            app_key_configured=bool(self.settings.longbridge_app_key),
            app_secret_configured=bool(self.settings.longbridge_app_secret),
            paper_token_configured=bool(self.settings.longbridge_paper_access_token),
            live_token_configured=bool(self.settings.longbridge_access_token),
        )

    def get_quote(
        self,
        symbol: str,
        mode: ExecutionMode,
    ) -> SecurityQuoteSnapshot:
        def _load_quote() -> SecurityQuoteSnapshot:
            sdk = self._load_sdk()
            config = self._build_config(mode=mode, sdk=sdk)
            quote_context = sdk["QuoteContext"](config)
            quotes = quote_context.quote([symbol])
            if not quotes:
                raise LongbridgeIntegrationError(f"No quote returned for symbol '{symbol}'.")
            return self._map_security_quote(quotes[0])

        try:
            quote = self._run_sdk_action(f"load quote for '{symbol}'", _load_quote)
        except LongbridgeIntegrationError as exc:
            cached_quote = self._get_cached_quote(symbol=symbol, mode=mode)
            if cached_quote is not None:
                logger.warning(
                    "Using cached Longbridge quote for %s after transient failure. %s",
                    symbol,
                    exc,
                )
                return cached_quote
            raise
        self._store_cached_quote(symbol=symbol, mode=mode, quote=quote)
        return quote

    def get_quotes(
        self,
        symbols: list[str],
        mode: ExecutionMode,
    ) -> dict[str, SecurityQuoteSnapshot]:
        normalized_symbols = [symbol for symbol in symbols if symbol]
        if not normalized_symbols:
            return {}

        def _load_quotes() -> dict[str, SecurityQuoteSnapshot]:
            sdk = self._load_sdk()
            config = self._build_config(mode=mode, sdk=sdk)
            quote_context = sdk["QuoteContext"](config)
            quotes = quote_context.quote(normalized_symbols)
            return {
                mapped.symbol: mapped
                for mapped in (self._map_security_quote(quote) for quote in quotes)
            }

        joined_symbols = ", ".join(normalized_symbols)
        try:
            quotes = self._run_sdk_action(f"load quotes for {joined_symbols}", _load_quotes)
        except LongbridgeIntegrationError as exc:
            cached_quotes = self._get_cached_quotes(symbols=normalized_symbols, mode=mode)
            if cached_quotes:
                logger.warning(
                    "Using %s cached Longbridge quotes after transient batch failure for %s. %s",
                    len(cached_quotes),
                    joined_symbols,
                    exc,
                )
                return cached_quotes
            raise
        self._store_cached_quotes(mode=mode, quotes=quotes)
        return quotes

    def list_option_expiry_dates(
        self,
        symbol: str,
        mode: ExecutionMode,
    ) -> list[date]:
        def _load_expiry_dates() -> list[date]:
            sdk = self._load_sdk()
            config = self._build_config(mode=mode, sdk=sdk)
            quote_context = sdk["QuoteContext"](config)
            expiry_dates = quote_context.option_chain_expiry_date_list(symbol)
            return [self._to_date(expiry_date) for expiry_date in expiry_dates]

        return self._run_sdk_action(f"load option expiry dates for '{symbol}'", _load_expiry_dates)

    def list_option_chain(
        self,
        symbol: str,
        expiry_date: date,
        mode: ExecutionMode,
    ) -> list[OptionChainEntry]:
        def _load_option_chain() -> list[OptionChainEntry]:
            sdk = self._load_sdk()
            config = self._build_config(mode=mode, sdk=sdk)
            quote_context = sdk["QuoteContext"](config)
            contracts = quote_context.option_chain_info_by_date(symbol, expiry_date)
            return [
                OptionChainEntry(
                    strike=self._to_decimal(getattr(contract, "price", None)),
                    call_symbol=getattr(contract, "call_symbol", None),
                    put_symbol=getattr(contract, "put_symbol", None),
                    standard=bool(getattr(contract, "standard", True)),
                )
                for contract in contracts
            ]

        return self._run_sdk_action(
            f"load option chain for '{symbol}' on {expiry_date.isoformat()}",
            _load_option_chain,
        )

    def get_option_market_snapshots(
        self,
        symbols: list[str],
        mode: ExecutionMode,
    ) -> list[OptionMarketSnapshot]:
        if not symbols:
            return []

        def _load_option_snapshots() -> list[OptionMarketSnapshot]:
            sdk = self._load_sdk()
            config = self._build_config(mode=mode, sdk=sdk)
            quote_context = sdk["QuoteContext"](config)
            option_quotes = quote_context.option_quote(symbols)
            calc_indexes = quote_context.calc_indexes(
                symbols,
                [
                    sdk["CalcIndex"].OpenInterest,
                    sdk["CalcIndex"].ImpliedVolatility,
                    sdk["CalcIndex"].Delta,
                    sdk["CalcIndex"].Gamma,
                    sdk["CalcIndex"].Theta,
                    sdk["CalcIndex"].Vega,
                    sdk["CalcIndex"].StrikePrice,
                    sdk["CalcIndex"].ExpiryDate,
                ],
            )
            calc_by_symbol = {
                getattr(calc_index, "symbol"): calc_index
                for calc_index in calc_indexes
                if getattr(calc_index, "symbol", None)
            }
            return [
                self._map_option_market_snapshot(
                    quote=quote,
                    calc_index=calc_by_symbol.get(getattr(quote, "symbol", None)),
                )
                for quote in option_quotes
            ]

        return self._run_sdk_action(
            f"load option market snapshots for {', '.join(symbols)}",
            _load_option_snapshots,
        )

    def get_best_bid_ask(
        self,
        symbol: str,
        mode: ExecutionMode,
    ) -> tuple[Decimal | None, Decimal | None]:
        def _load_best_bid_ask() -> tuple[Decimal | None, Decimal | None]:
            sdk = self._load_sdk()
            config = self._build_config(mode=mode, sdk=sdk)
            quote_context = sdk["QuoteContext"](config)
            depth = quote_context.depth(symbol)
            best_ask = self._to_optional_decimal(
                getattr((getattr(depth, "asks", None) or [None])[0], "price", None)
            )
            best_bid = self._to_optional_decimal(
                getattr((getattr(depth, "bids", None) or [None])[0], "price", None)
            )
            return best_bid, best_ask

        return self._run_sdk_action(f"load best bid/ask for '{symbol}'", _load_best_bid_ask)

    def get_recent_daily_bars(
        self,
        symbol: str,
        *,
        count: int,
        mode: ExecutionMode,
    ) -> list[HistoricalPriceBar]:
        def _load_daily_bars() -> list[HistoricalPriceBar]:
            sdk = self._load_sdk()
            config = self._build_config(mode=mode, sdk=sdk)
            quote_context = sdk["QuoteContext"](config)
            candlesticks = quote_context.candlesticks(
                symbol,
                sdk["Period"].Day,
                count,
                sdk["AdjustType"].NoAdjust,
            )
            return [
                HistoricalPriceBar(
                    symbol=symbol,
                    timestamp=self._to_datetime(getattr(bar, "timestamp", None)),
                    open=self._to_decimal(getattr(bar, "open", None)),
                    high=self._to_decimal(getattr(bar, "high", None)),
                    low=self._to_decimal(getattr(bar, "low", None)),
                    close=self._to_decimal(getattr(bar, "close", None)),
                    volume=int(getattr(bar, "volume", 0) or 0),
                    turnover=self._to_decimal(getattr(bar, "turnover", None)),
                    raw_payload=self._serialize_attrs(
                        bar,
                        ["open", "high", "low", "close", "volume", "turnover", "timestamp"],
                    ),
                )
                for bar in candlesticks
            ]

        return self._run_sdk_action(f"load recent daily bars for '{symbol}'", _load_daily_bars)

    def build_account_snapshot(
        self,
        external_account_id: str,
        mode: ExecutionMode,
        currency: str | None = None,
        options_level: str | None = None,
    ) -> AccountSnapshot:
        sdk = self._load_sdk()
        config = self._build_config(mode=mode, sdk=sdk)
        trade_context = sdk["TradeContext"](config)
        quote_context = sdk["QuoteContext"](config)

        balances = trade_context.account_balance(currency)
        balance = self._pick_account_balance(balances=balances, currency=currency)

        positions_response = trade_context.stock_positions()
        stock_positions = self._extract_stock_positions(positions_response)
        quote_by_symbol = self._load_quotes_by_symbol(quote_context, stock_positions)
        captured_at = datetime.now(timezone.utc)

        positions = [
            self._map_position_snapshot(position=position, quote=quote_by_symbol.get(position.symbol))
            for position in stock_positions
        ]

        return AccountSnapshot(
            broker=self.name,
            account_id=external_account_id,
            currency=(getattr(balance, "currency", None) or currency or "USD"),
            cash_balance=self._to_decimal(getattr(balance, "total_cash", None)),
            net_liquidation=self._to_decimal(getattr(balance, "net_assets", None)),
            buying_power=self._to_decimal(getattr(balance, "buy_power", None)),
            day_trade_buying_power=None,
            options_level=options_level,
            positions=positions,
            raw_payload={
                "mode": mode.value,
                "balance": self._serialize_attrs(
                    balance,
                    [
                        "total_cash",
                        "max_finance_amount",
                        "remaining_finance_amount",
                        "risk_level",
                        "margin_call",
                        "currency",
                        "cash_infos",
                        "net_assets",
                        "init_margin",
                        "maintenance_margin",
                        "buy_power",
                        "frozen_transaction_fees",
                    ],
                ),
                "position_channels": self._serialize_position_channels(positions_response),
                "quotes": {
                    symbol: self._serialize_quote(quote)
                    for symbol, quote in sorted(quote_by_symbol.items())
                },
            },
            captured_at=captured_at,
        )

    def submit_order(
        self,
        request: CreateOrderRequest,
    ) -> BrokerOrderSnapshot:
        sdk = self._load_sdk()
        config = self._build_config(mode=request.mode, sdk=sdk)
        trade_context = sdk["TradeContext"](config)

        order_type = self._map_submit_order_type(request.order_type, request.limit_price, request.stop_price, sdk)
        time_in_force = self._map_submit_time_in_force(request.time_in_force, sdk)
        side = self._map_submit_side(request.side, sdk)

        submit_response = trade_context.submit_order(
            symbol=request.symbol,
            order_type=order_type,
            side=side,
            submitted_quantity=Decimal(request.quantity),
            time_in_force=time_in_force,
            submitted_price=request.limit_price,
            trigger_price=request.stop_price,
            remark=request.remark,
        )
        order_detail = trade_context.order_detail(submit_response.order_id)
        return self._map_order_snapshot(
            detail=order_detail,
            mode=request.mode,
        )

    def cancel_order(
        self,
        external_order_id: str,
        mode: ExecutionMode,
    ) -> BrokerOrderSnapshot:
        sdk = self._load_sdk()
        config = self._build_config(mode=mode, sdk=sdk)
        trade_context = sdk["TradeContext"](config)
        trade_context.cancel_order(external_order_id)
        order_detail = trade_context.order_detail(external_order_id)
        return self._map_order_snapshot(detail=order_detail, mode=mode)

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
        sdk = self._load_sdk()
        config = self._build_config(mode=mode, sdk=sdk)
        trade_context = sdk["TradeContext"](config)
        trade_context.replace_order(
            external_order_id,
            quantity=Decimal(quantity),
            price=limit_price,
            trigger_price=stop_price,
            remark=remark,
        )
        order_detail = trade_context.order_detail(external_order_id)
        return self._map_order_snapshot(detail=order_detail, mode=mode)

    def get_order(
        self,
        external_order_id: str,
        mode: ExecutionMode,
    ) -> BrokerOrderSnapshot:
        sdk = self._load_sdk()
        config = self._build_config(mode=mode, sdk=sdk)
        trade_context = sdk["TradeContext"](config)
        order_detail = trade_context.order_detail(external_order_id)
        return self._map_order_snapshot(detail=order_detail, mode=mode)

    def list_today_orders(
        self,
        mode: ExecutionMode,
        *,
        symbol: str | None = None,
        external_order_id: str | None = None,
    ) -> list[BrokerOrderSnapshot]:
        sdk = self._load_sdk()
        config = self._build_config(mode=mode, sdk=sdk)
        trade_context = sdk["TradeContext"](config)
        orders = trade_context.today_orders(symbol=symbol, order_id=external_order_id)
        return [self._map_order_snapshot(detail=order, mode=mode) for order in orders]

    def _load_sdk(self) -> dict[str, Any]:
        try:
            from longbridge.openapi import (
                AdjustType,
                CalcIndex,
                Config,
                Language,
                OrderSide as LongbridgeOrderSide,
                OrderType as LongbridgeOrderType,
                Period,
                QuoteContext,
                TimeInForceType,
                TradeContext,
            )
        except ImportError as exc:
            raise LongbridgeDependencyError(
                "Longbridge SDK is not installed. Run `python -m pip install -e \".[dev]\"` "
                "inside the project virtual environment."
            ) from exc

        return {
            "AdjustType": AdjustType,
            "CalcIndex": CalcIndex,
            "Config": Config,
            "Language": Language,
            "LongbridgeOrderSide": LongbridgeOrderSide,
            "LongbridgeOrderType": LongbridgeOrderType,
            "Period": Period,
            "QuoteContext": QuoteContext,
            "TimeInForceType": TimeInForceType,
            "TradeContext": TradeContext,
        }

    def _build_config(
        self,
        mode: ExecutionMode,
        sdk: dict[str, Any],
    ) -> Any:
        if not self.settings.longbridge_app_key or not self.settings.longbridge_app_secret:
            raise LongbridgeConfigurationError(
                "Longbridge App Key and App Secret must be configured in `.env`."
            )

        access_token = self._get_access_token(mode)
        if not access_token:
            env_name = (
                "LONGBRIDGE_PAPER_ACCESS_TOKEN"
                if mode == ExecutionMode.PAPER
                else "LONGBRIDGE_ACCESS_TOKEN"
            )
            raise LongbridgeConfigurationError(
                f"Missing Longbridge access token for {mode.value} mode. Configure `{env_name}` in `.env`."
            )

        language = self._resolve_language_enum(sdk["Language"])
        return sdk["Config"].from_apikey(
            self.settings.longbridge_app_key,
            self.settings.longbridge_app_secret,
            access_token,
            http_url=self.settings.longbridge_http_url,
            quote_ws_url=self.settings.longbridge_quote_ws_url,
            trade_ws_url=self.settings.longbridge_trade_ws_url,
            language=language,
            enable_overnight=self.settings.longbridge_enable_overnight,
            enable_print_quote_packages=self.settings.longbridge_print_quote_packages,
        )

    def _get_access_token(self, mode: ExecutionMode) -> str:
        if mode == ExecutionMode.PAPER:
            return self.settings.longbridge_paper_access_token
        return self.settings.longbridge_access_token

    def _resolve_language_enum(self, language_enum: Any) -> Any:
        mapping = {
            "en": getattr(language_enum, "EN"),
            "zh-cn": getattr(language_enum, "ZH_CN"),
            "zh-hk": getattr(language_enum, "ZH_HK"),
        }
        return mapping.get(self.settings.longbridge_language.lower(), getattr(language_enum, "EN"))

    def _run_sdk_action(self, action: str, func):
        self._raise_if_circuit_open(action)
        future = self._executor.submit(func)
        try:
            return future.result(timeout=max(1, self.settings.longbridge_request_timeout_seconds))
        except FuturesTimeoutError as exc:
            future.cancel()
            self._open_circuit(
                reason=(
                    f"Longbridge timed out while trying to {action} after "
                    f"{self.settings.longbridge_request_timeout_seconds}s."
                )
            )
            raise LongbridgeIntegrationError(
                f"Longbridge timed out while trying to {action} after "
                f"{self.settings.longbridge_request_timeout_seconds}s."
            ) from exc
        except LongbridgeIntegrationError:
            raise
        except Exception as exc:
            if self._should_open_circuit(exc):
                self._open_circuit(
                    reason=f"Longbridge connectivity failed while trying to {action}: {exc}"
                )
            raise LongbridgeIntegrationError(
                f"Longbridge failed to {action}: {exc}"
            ) from exc

    def _raise_if_circuit_open(self, action: str) -> None:
        with self._circuit_lock:
            now = time.monotonic()
            if now >= self._circuit_open_until:
                self._circuit_open_until = 0.0
                self._circuit_reason = ""
                return
            remaining = max(1, int(round(self._circuit_open_until - now)))
            reason = self._circuit_reason or "Longbridge connectivity is temporarily unavailable."
        raise LongbridgeIntegrationError(
            f"{reason} Skipping attempt to {action} for another {remaining}s."
        )

    def _open_circuit(self, *, reason: str) -> None:
        with self._circuit_lock:
            self._circuit_open_until = time.monotonic() + max(
                1,
                self.settings.longbridge_circuit_breaker_seconds,
            )
            self._circuit_reason = reason

    @staticmethod
    def _should_open_circuit(exc: Exception) -> bool:
        message = str(exc).lower()
        network_markers = (
            "client error (connect)",
            "connection refused",
            "connection reset",
            "connection aborted",
            "timed out",
            "timeout",
            "dns",
            "socket/token",
            "network",
        )
        return any(marker in message for marker in network_markers)

    def _get_cached_quote(
        self,
        *,
        symbol: str,
        mode: ExecutionMode,
    ) -> SecurityQuoteSnapshot | None:
        with self._quote_cache_lock:
            cached = self._quote_cache.get((mode.value, symbol))
            if cached is None:
                return None
            cached_at, quote = cached
            if time.monotonic() - cached_at > self._QUOTE_CACHE_TTL_SECONDS:
                self._quote_cache.pop((mode.value, symbol), None)
                return None
            return quote

    def _get_cached_quotes(
        self,
        *,
        symbols: list[str],
        mode: ExecutionMode,
    ) -> dict[str, SecurityQuoteSnapshot]:
        cached_quotes: dict[str, SecurityQuoteSnapshot] = {}
        for symbol in symbols:
            cached_quote = self._get_cached_quote(symbol=symbol, mode=mode)
            if cached_quote is not None:
                cached_quotes[symbol] = cached_quote
        return cached_quotes

    def _store_cached_quote(
        self,
        *,
        symbol: str,
        mode: ExecutionMode,
        quote: SecurityQuoteSnapshot,
    ) -> None:
        with self._quote_cache_lock:
            self._quote_cache[(mode.value, symbol)] = (time.monotonic(), quote)

    def _store_cached_quotes(
        self,
        *,
        mode: ExecutionMode,
        quotes: dict[str, SecurityQuoteSnapshot],
    ) -> None:
        if not quotes:
            return
        with self._quote_cache_lock:
            cached_at = time.monotonic()
            for symbol, quote in quotes.items():
                self._quote_cache[(mode.value, symbol)] = (cached_at, quote)

    def _pick_account_balance(
        self,
        balances: list[Any],
        currency: str | None,
    ) -> Any:
        if not balances:
            raise LongbridgeIntegrationError("Longbridge returned no account balance rows.")

        if currency is None:
            return balances[0]

        target_currency = currency.upper()
        for balance in balances:
            if getattr(balance, "currency", "").upper() == target_currency:
                return balance

        raise LongbridgeIntegrationError(
            f"Longbridge returned no account balance row for currency '{currency}'."
        )

    def _extract_stock_positions(self, positions_response: Any) -> list[Any]:
        positions: list[Any] = []
        for channel in getattr(positions_response, "channels", []):
            positions.extend(getattr(channel, "positions", []))
        return positions

    def _load_quotes_by_symbol(
        self,
        quote_context: Any,
        positions: list[Any],
    ) -> dict[str, Any]:
        symbols = sorted({getattr(position, "symbol", "") for position in positions if getattr(position, "symbol", "")})
        if not symbols:
            return {}

        quotes = quote_context.quote(symbols)
        return {getattr(quote, "symbol"): quote for quote in quotes}

    def _map_position_snapshot(
        self,
        position: Any,
        quote: Any | None,
    ) -> PositionSnapshot:
        quantity = self._to_decimal(getattr(position, "quantity", None))
        average_cost = self._to_decimal(getattr(position, "cost_price", None))
        mark_price = self._to_decimal(getattr(quote, "last_done", None), default=average_cost)
        market_value = quantity * mark_price
        cost_basis = quantity * average_cost
        unrealized_pnl = market_value - cost_basis

        return PositionSnapshot(
            symbol=getattr(position, "symbol"),
            asset_type=AssetType.STOCK,
            quantity=quantity,
            average_cost=average_cost,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            raw_payload={
                "position": self._serialize_attrs(
                    position,
                    [
                        "symbol",
                        "symbol_name",
                        "quantity",
                        "available_quantity",
                        "currency",
                        "cost_price",
                        "market",
                        "init_quantity",
                    ],
                ),
                "quote": self._serialize_quote(quote) if quote is not None else None,
            },
        )

    def _map_security_quote(self, quote: Any) -> SecurityQuoteSnapshot:
        return SecurityQuoteSnapshot(
            symbol=getattr(quote, "symbol"),
            last_done=self._to_decimal(getattr(quote, "last_done", None)),
            prev_close=self._to_decimal(getattr(quote, "prev_close", None)),
            open=self._to_decimal(getattr(quote, "open", None)),
            high=self._to_decimal(getattr(quote, "high", None)),
            low=self._to_decimal(getattr(quote, "low", None)),
            timestamp=self._to_datetime(getattr(quote, "timestamp", None)),
            volume=int(getattr(quote, "volume", 0) or 0),
            turnover=self._to_decimal(getattr(quote, "turnover", None)),
            trade_status=self._enum_to_value(getattr(quote, "trade_status", None)),
            pre_market_quote=self._map_session_quote(getattr(quote, "pre_market_quote", None)),
            post_market_quote=self._map_session_quote(getattr(quote, "post_market_quote", None)),
            overnight_quote=self._map_session_quote(getattr(quote, "overnight_quote", None)),
        )

    def _map_session_quote(self, quote: Any | None) -> SessionQuote | None:
        if quote is None:
            return None

        return SessionQuote(
            last_done=self._to_decimal(getattr(quote, "last_done", None)),
            timestamp=self._to_datetime(getattr(quote, "timestamp", None)),
            volume=int(getattr(quote, "volume", 0) or 0),
            turnover=self._to_decimal(getattr(quote, "turnover", None)),
            high=self._to_decimal(getattr(quote, "high", None)),
            low=self._to_decimal(getattr(quote, "low", None)),
            prev_close=self._to_decimal(getattr(quote, "prev_close", None)),
        )

    def _map_option_market_snapshot(
        self,
        *,
        quote: Any,
        calc_index: Any | None,
    ) -> OptionMarketSnapshot:
        expiry_date = getattr(quote, "expiry_date", None) or getattr(calc_index, "expiry_date", None)
        strike_price = getattr(quote, "strike_price", None) or getattr(calc_index, "strike_price", None)
        implied_volatility = getattr(quote, "implied_volatility", None)
        if implied_volatility is None:
            implied_volatility = getattr(calc_index, "implied_volatility", None)
        open_interest = getattr(quote, "open_interest", None)
        if open_interest is None:
            open_interest = getattr(calc_index, "open_interest", None)

        return OptionMarketSnapshot(
            symbol=getattr(quote, "symbol"),
            underlying_symbol=getattr(quote, "underlying_symbol"),
            expiration_date=self._to_date(expiry_date),
            strike=self._to_decimal(strike_price),
            right=self._map_option_right(getattr(quote, "direction", None)),
            last_done=self._to_decimal(getattr(quote, "last_done", None)),
            prev_close=self._to_decimal(getattr(quote, "prev_close", None)),
            open=self._to_decimal(getattr(quote, "open", None)),
            high=self._to_decimal(getattr(quote, "high", None)),
            low=self._to_decimal(getattr(quote, "low", None)),
            timestamp=self._to_datetime(getattr(quote, "timestamp", None)),
            volume=int(getattr(quote, "volume", 0) or 0),
            turnover=self._to_decimal(getattr(quote, "turnover", None)),
            trade_status=self._enum_to_value(getattr(quote, "trade_status", None)),
            open_interest=int(open_interest) if open_interest is not None else None,
            implied_volatility=self._to_optional_decimal(implied_volatility),
            historical_volatility=self._to_optional_decimal(getattr(quote, "historical_volatility", None)),
            delta=self._to_optional_decimal(getattr(calc_index, "delta", None)),
            gamma=self._to_optional_decimal(getattr(calc_index, "gamma", None)),
            theta=self._to_optional_decimal(getattr(calc_index, "theta", None)),
            vega=self._to_optional_decimal(getattr(calc_index, "vega", None)),
            contract_multiplier=self._to_decimal(getattr(quote, "contract_multiplier", None)),
            contract_size=self._to_optional_decimal(getattr(quote, "contract_size", None)),
            raw_payload={
                "quote": self._serialize_attrs(
                    quote,
                    [
                        "symbol",
                        "last_done",
                        "prev_close",
                        "open",
                        "high",
                        "low",
                        "timestamp",
                        "volume",
                        "turnover",
                        "trade_status",
                        "implied_volatility",
                        "open_interest",
                        "expiry_date",
                        "strike_price",
                        "contract_multiplier",
                        "contract_type",
                        "contract_size",
                        "direction",
                        "historical_volatility",
                        "underlying_symbol",
                    ],
                    enum_fields={"trade_status", "contract_type", "direction"},
                ),
                "calc_index": self._serialize_attrs(
                    calc_index,
                    [
                        "symbol",
                        "open_interest",
                        "implied_volatility",
                        "expiry_date",
                        "strike_price",
                        "delta",
                        "gamma",
                        "theta",
                        "vega",
                    ],
                )
                if calc_index is not None
                else None,
            },
        )

    def _map_option_right(self, direction: Any) -> OptionRight:
        direction_value = self._normalize_enum_token(direction)
        if direction_value in {"PUT", "P"}:
            return OptionRight.PUT
        if direction_value in {"CALL", "C"}:
            return OptionRight.CALL
        raise LongbridgeIntegrationError(f"Unsupported Longbridge option direction '{direction_value}'.")

    def _map_order_snapshot(
        self,
        detail: Any,
        mode: ExecutionMode,
    ) -> BrokerOrderSnapshot:
        return BrokerOrderSnapshot(
            external_order_id=getattr(detail, "order_id"),
            symbol=getattr(detail, "symbol"),
            side=self._map_local_side(getattr(detail, "side", None)),
            quantity=int(self._to_decimal(getattr(detail, "quantity", None))),
            order_type=self._map_local_order_type(getattr(detail, "order_type", None)),
            time_in_force=self._map_local_time_in_force(getattr(detail, "time_in_force", None)),
            mode=mode,
            status=self._map_local_order_status(getattr(detail, "status", None)),
            limit_price=self._to_optional_decimal(getattr(detail, "price", None)),
            stop_price=self._to_optional_decimal(getattr(detail, "trigger_price", None)),
            executed_quantity=int(self._to_decimal(getattr(detail, "executed_quantity", None))),
            executed_price=self._to_optional_decimal(getattr(detail, "executed_price", None)),
            submitted_at=self._to_optional_datetime(getattr(detail, "submitted_at", None)),
            updated_at=self._to_optional_datetime(getattr(detail, "updated_at", None)),
            raw_payload=self._serialize_order_payload(detail),
        )

    def _map_submit_side(self, side: OrderSide, sdk: dict[str, Any]) -> Any:
        if side == OrderSide.BUY:
            return getattr(sdk["LongbridgeOrderSide"], "Buy")
        if side == OrderSide.SELL:
            return getattr(sdk["LongbridgeOrderSide"], "Sell")
        raise LongbridgeIntegrationError(f"Unsupported order side '{side.value}'.")

    def _map_submit_order_type(
        self,
        order_type: OrderType,
        limit_price: Decimal | None,
        stop_price: Decimal | None,
        sdk: dict[str, Any],
    ) -> Any:
        longbridge_order_type = sdk["LongbridgeOrderType"]
        if order_type == OrderType.LIMIT:
            if limit_price is None:
                raise LongbridgeIntegrationError("Limit orders require `limit_price`.")
            return getattr(longbridge_order_type, "LO")
        if order_type == OrderType.MARKET:
            return getattr(longbridge_order_type, "MO")
        if order_type == OrderType.STOP:
            if stop_price is None:
                raise LongbridgeIntegrationError("Stop orders require `stop_price`.")
            if limit_price is not None:
                return getattr(longbridge_order_type, "LIT")
            return getattr(longbridge_order_type, "MIT")
        raise LongbridgeIntegrationError(f"Unsupported order type '{order_type.value}'.")

    def _map_submit_time_in_force(
        self,
        time_in_force: TimeInForce,
        sdk: dict[str, Any],
    ) -> Any:
        longbridge_time_in_force = sdk["TimeInForceType"]
        if time_in_force == TimeInForce.DAY:
            return getattr(longbridge_time_in_force, "Day")
        if time_in_force == TimeInForce.GTC:
            return getattr(longbridge_time_in_force, "GoodTilCanceled")
        raise LongbridgeIntegrationError(
            f"Unsupported time in force '{time_in_force.value}' for Longbridge submission."
        )

    def _map_local_side(self, side: Any) -> OrderSide:
        side_value = self._normalize_enum_token(side)
        if side_value == "BUY":
            return OrderSide.BUY
        if side_value == "SELL":
            return OrderSide.SELL
        raise LongbridgeIntegrationError(f"Unsupported Longbridge order side '{side_value}'.")

    def _map_local_order_type(self, order_type: Any) -> OrderType:
        order_type_value = self._normalize_enum_token(order_type)
        if order_type_value in {"LO", "ELO", "AO", "ALO", "SLO"}:
            return OrderType.LIMIT
        if order_type_value in {"MO", "ODD"}:
            return OrderType.MARKET
        if order_type_value in {"LIT", "MIT", "TSLPAMT", "TSLPPCT", "TSMAMT", "TSMPCT"}:
            return OrderType.STOP
        raise LongbridgeIntegrationError(
            f"Unsupported Longbridge order type '{order_type_value}' in order detail."
        )

    def _map_local_time_in_force(self, time_in_force: Any) -> TimeInForce:
        tif_value = self._normalize_enum_token(time_in_force)
        if tif_value == "DAY":
            return TimeInForce.DAY
        if tif_value == "GOODTILCANCELED":
            return TimeInForce.GTC
        raise LongbridgeIntegrationError(
            f"Unsupported Longbridge time in force '{tif_value}' in order detail."
        )

    def _map_local_order_status(self, status: Any) -> OrderStatus:
        status_value = self._normalize_enum_token(status)
        if status_value in {"FILLED"}:
            return OrderStatus.FILLED
        if status_value in {"PARTIALFILLED", "PARTIALWITHDRAWAL"}:
            return OrderStatus.PARTIALLY_FILLED
        if status_value in {"CANCELED", "EXPIRED"}:
            return OrderStatus.CANCELED
        if status_value in {"REJECTED"}:
            return OrderStatus.REJECTED
        if status_value in {
            "NOTREPORTED",
            "REPLACEDNOTREPORTED",
            "PROTECTEDNOTREPORTED",
            "VARIETIESNOTREPORTED",
            "WAITTONEW",
            "NEW",
            "WAITTOREPLACE",
            "PENDINGREPLACE",
            "REPLACED",
            "WAITTOCANCEL",
            "PENDINGCANCEL",
        }:
            return OrderStatus.SUBMITTED
        return OrderStatus.CREATED

    def _serialize_position_channels(self, positions_response: Any) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for channel in getattr(positions_response, "channels", []):
            serialized.append(
                {
                    "account_channel": getattr(channel, "account_channel", None),
                    "positions": [
                        self._serialize_attrs(
                            position,
                            [
                                "symbol",
                                "symbol_name",
                                "quantity",
                                "available_quantity",
                                "currency",
                                "cost_price",
                                "market",
                                "init_quantity",
                            ],
                        )
                        for position in getattr(channel, "positions", [])
                    ],
                }
            )
        return serialized

    def _serialize_quote(self, quote: Any | None) -> dict[str, Any] | None:
        if quote is None:
            return None
        return self._serialize_attrs(
            quote,
            [
                "symbol",
                "last_done",
                "prev_close",
                "open",
                "high",
                "low",
                "timestamp",
                "volume",
                "turnover",
                "trade_status",
                "pre_market_quote",
                "post_market_quote",
                "overnight_quote",
            ],
            enum_fields={"trade_status"},
        )

    def _serialize_order_payload(self, detail: Any) -> dict[str, Any]:
        return self._serialize_attrs(
            detail,
            [
                "order_id",
                "status",
                "stock_name",
                "quantity",
                "executed_quantity",
                "price",
                "executed_price",
                "submitted_at",
                "side",
                "symbol",
                "order_type",
                "last_done",
                "trigger_price",
                "msg",
                "tag",
                "time_in_force",
                "expire_date",
                "updated_at",
            ],
            enum_fields={"status", "side", "order_type", "tag", "time_in_force"},
        )

    def _serialize_attrs(
        self,
        source: Any,
        field_names: list[str],
        *,
        enum_fields: set[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        enum_fields = enum_fields or set()
        for field_name in field_names:
            if hasattr(source, field_name):
                raw_value = getattr(source, field_name)
                if field_name in enum_fields:
                    payload[field_name] = self._normalize_enum_token(raw_value)
                else:
                    payload[field_name] = self._serialize_value(raw_value)
        return payload

    def _serialize_value(
        self,
        value: Any,
        *,
        depth: int = 0,
        seen: set[int] | None = None,
    ) -> Any:
        if seen is None:
            seen = set()
        if value is None:
            return None
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Enum):
            return self._enum_to_value(value)
        if isinstance(value, (str, int, float, bool)):
            return value
        if depth >= 4:
            return str(value)

        object_id = id(value)
        if object_id in seen:
            return str(value)
        seen.add(object_id)

        if isinstance(value, list):
            return [
                self._serialize_value(item, depth=depth + 1, seen=seen)
                for item in value
            ]
        if isinstance(value, tuple):
            return [
                self._serialize_value(item, depth=depth + 1, seen=seen)
                for item in value
            ]
        if isinstance(value, dict):
            return {
                str(key): self._serialize_value(item, depth=depth + 1, seen=seen)
                for key, item in value.items()
            }
        if hasattr(value, "__dict__"):
            try:
                object_dict = vars(value)
            except TypeError:
                object_dict = None
            if isinstance(object_dict, dict):
                return {
                    key: self._serialize_value(item, depth=depth + 1, seen=seen)
                    for key, item in object_dict.items()
                    if not key.startswith("_")
                }
        attribute_names = [
            name
            for name in dir(value)
            if not name.startswith("_")
        ]
        object_payload: dict[str, Any] = {}
        for name in attribute_names:
            try:
                attr_value = getattr(value, name)
            except Exception:
                continue
            if callable(attr_value):
                continue
            object_payload[name] = self._serialize_value(
                attr_value,
                depth=depth + 1,
                seen=seen,
            )
        if object_payload:
            return object_payload
        return value

    @staticmethod
    def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
        if value is None:
            return default
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _to_optional_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        return LongbridgeBrokerAdapter._to_decimal(value)

    @staticmethod
    def _to_date(value: Any) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            raw = value.strip()
            if len(raw) == 8 and raw.isdigit():
                return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
            return date.fromisoformat(raw)
        raise LongbridgeIntegrationError("Longbridge returned an invalid date payload.")

    @staticmethod
    def _to_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        raise LongbridgeIntegrationError("Longbridge returned an invalid timestamp payload.")

    @staticmethod
    def _to_optional_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        return LongbridgeBrokerAdapter._to_datetime(value)

    @staticmethod
    def _enum_to_value(value: Any) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        if hasattr(value, "name"):
            return str(value.name)
        return str(value)

    @staticmethod
    def _normalize_enum_token(value: Any) -> str:
        raw = LongbridgeBrokerAdapter._enum_to_value(value).strip()
        if "." in raw:
            raw = raw.rsplit(".", 1)[-1]
        return raw.upper()
