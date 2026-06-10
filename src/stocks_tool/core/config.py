from decimal import Decimal
from functools import lru_cache

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from stocks_tool.domain.enums import BrokerName, ExecutionMode


class BullPutSpreadStrategySettings(BaseModel):
    enabled: bool = True
    auto_scan_enabled: bool = True
    auto_monitor_enabled: bool = True
    auto_review_enabled: bool = True
    scan_window_start_hour_et: int = Field(default=10, ge=0, le=23)
    scan_window_start_minute_et: int = Field(default=45, ge=0, le=59)
    scan_window_end_hour_et: int = Field(default=11, ge=0, le=23)
    scan_window_end_minute_et: int = Field(default=15, ge=0, le=59)
    monitor_interval_seconds: int = Field(default=300, ge=1)
    symbols: tuple[str, ...] = ("QQQ.US", "SMH.US", "SOXL.US", "EWY.US")
    correlated_symbols: tuple[str, ...] = ("QQQ.US", "SMH.US", "SOXL.US")
    account_max_open_spreads: int = Field(default=2, ge=1)
    per_symbol_max_open_spreads: int = Field(default=1, ge=1)
    correlated_group_max_open_spreads: int = Field(default=1, ge=1)
    max_new_spreads_per_day: int = Field(default=1, ge=1)
    daily_realized_loss_limit: Decimal = Field(default=Decimal("300"), gt=0)
    min_dte: int = Field(default=28, ge=1)
    max_dte: int = Field(default=35, ge=1)
    short_delta_target: Decimal = Field(default=Decimal("0.22"), gt=0)
    short_delta_min: Decimal = Field(default=Decimal("0.18"), gt=0)
    short_delta_max: Decimal = Field(default=Decimal("0.28"), gt=0)
    min_open_interest: int = Field(default=200, ge=1)
    min_short_leg_volume: int = Field(default=10, ge=0)
    min_long_leg_volume: int = Field(default=10, ge=0)
    max_option_quote_age_seconds: int = Field(default=1800, ge=1)
    max_bid_ask_spread_pct: Decimal = Field(default=Decimal("0.10"), gt=0)
    preview_cache_ttl_seconds: int = Field(default=120, ge=0)
    min_credit_per_width_ratio: Decimal = Field(default=Decimal("0.18"), gt=0)
    min_conservative_credit_per_width_ratio: Decimal = Field(default=Decimal("0.10"), gt=0)
    min_mid_credit: Decimal = Field(default=Decimal("0.20"), gt=0)
    entry_session_start_hour_et: int = Field(default=9, ge=0, le=23)
    entry_session_start_minute_et: int = Field(default=30, ge=0, le=59)
    entry_session_end_hour_et: int = Field(default=16, ge=0, le=23)
    entry_session_end_minute_et: int = Field(default=0, ge=0, le=59)
    entry_open_confirmation_minutes: int = Field(default=15, ge=0)
    entry_close_buffer_minutes: int = Field(default=5, ge=0)
    entry_long_limit_buffer: Decimal = Field(default=Decimal("0.10"), ge=0)
    entry_fill_timeout_seconds: int = Field(default=45, ge=0)
    entry_fill_poll_interval_seconds: int = Field(default=5, ge=0)
    entry_reprice_increment: Decimal = Field(default=Decimal("0.05"), gt=0)
    entry_reprice_max_steps: int = Field(default=2, ge=0)
    pre_open_proxy_spy_symbol: str = "SPY.US"
    pre_open_proxy_qqq_symbol: str = "QQQ.US"
    pre_open_proxy_semis_symbol: str = "SOXX.US"
    pre_open_proxy_oil_symbol: str = "USO.US"
    pre_open_proxy_rates_symbol: str = "TLT.US"
    pre_open_put_min_dte: int = Field(default=3, ge=0)
    pre_open_put_max_dte: int = Field(default=10, ge=1)
    contracts_per_trade: int = Field(default=1, ge=1)
    per_trade_max_account_risk_pct: Decimal = Field(default=Decimal("0.01"), gt=0)
    architecture_max_account_risk_pct: Decimal = Field(default=Decimal("0.02"), gt=0)
    take_profit_exit_ratio: Decimal = Field(default=Decimal("0.50"), ge=0)
    stop_loss_exit_multiple: Decimal = Field(default=Decimal("2.00"), gt=0)
    close_days_to_expiration: int = Field(default=7, ge=0)
    review_interval_days: int = Field(default=30, ge=1)
    review_min_closed_spreads: int = Field(default=20, ge=1)
    review_min_spreads_for_suggestion: int = Field(default=5, ge=1)
    review_delta_step: Decimal = Field(default=Decimal("0.02"), gt=0)
    review_credit_step: Decimal = Field(default=Decimal("0.05"), gt=0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "BullPutSpreadStrategySettings":
        if self.min_dte > self.max_dte:
            raise ValueError("Bull put spread min_dte must be less than or equal to max_dte.")
        if (self.entry_session_end_hour_et, self.entry_session_end_minute_et) <= (
            self.entry_session_start_hour_et,
            self.entry_session_start_minute_et,
        ):
            raise ValueError("Bull put spread entry session end must be after the entry session start.")
        entry_start_minutes = (self.entry_session_start_hour_et * 60) + self.entry_session_start_minute_et
        entry_end_minutes = (self.entry_session_end_hour_et * 60) + self.entry_session_end_minute_et
        if self.entry_open_confirmation_minutes + self.entry_close_buffer_minutes >= (
            entry_end_minutes - entry_start_minutes
        ):
            raise ValueError(
                "Bull put spread entry confirmation and close buffers must leave a positive execution window."
            )
        if (self.scan_window_end_hour_et, self.scan_window_end_minute_et) < (
            self.scan_window_start_hour_et,
            self.scan_window_start_minute_et,
        ):
            raise ValueError("Bull put spread scan window end must be after the scan window start.")
        if self.pre_open_put_min_dte > self.pre_open_put_max_dte:
            raise ValueError("Bull put pre-open put min_dte must be less than or equal to max_dte.")
        if self.short_delta_min > self.short_delta_target:
            raise ValueError("Bull put spread short_delta_min cannot exceed short_delta_target.")
        if self.short_delta_target > self.short_delta_max:
            raise ValueError("Bull put spread short_delta_target cannot exceed short_delta_max.")
        if self.per_trade_max_account_risk_pct > self.architecture_max_account_risk_pct:
            raise ValueError(
                "Bull put spread per_trade_max_account_risk_pct cannot exceed architecture_max_account_risk_pct."
            )
        if self.take_profit_exit_ratio > Decimal("1"):
            raise ValueError("Bull put spread take_profit_exit_ratio cannot exceed 1.")
        if self.correlated_group_max_open_spreads > self.account_max_open_spreads:
            raise ValueError(
                "Bull put spread correlated_group_max_open_spreads cannot exceed account_max_open_spreads."
            )
        if self.per_symbol_max_open_spreads > self.account_max_open_spreads:
            raise ValueError(
                "Bull put spread per_symbol_max_open_spreads cannot exceed account_max_open_spreads."
            )
        return self

    def width_for_underlying_price(self, underlying_price: Decimal) -> Decimal:
        if underlying_price < Decimal("75"):
            return Decimal("1")
        if underlying_price < Decimal("250"):
            return Decimal("2")
        return Decimal("3")


class CoveredCallStrategySettings(BaseModel):
    enabled: bool = True
    auto_propose_enabled: bool = False
    auto_monitor_enabled: bool = False
    auto_lifecycle_enabled: bool = False
    proposal_interval_seconds: int = Field(default=3600, ge=60)
    monitor_interval_seconds: int = Field(default=900, ge=60)
    lifecycle_interval_seconds: int = Field(default=300, ge=60)
    min_shares: int = Field(default=100, ge=100)
    min_dte: int = Field(default=21, ge=1)
    max_dte: int = Field(default=45, ge=1)
    delta_target: Decimal = Field(default=Decimal("0.30"), gt=0)
    delta_min: Decimal = Field(default=Decimal("0.20"), gt=0)
    delta_max: Decimal = Field(default=Decimal("0.35"), gt=0)
    min_otm_pct: Decimal = Field(default=Decimal("0.02"), ge=0)
    max_otm_pct: Decimal = Field(default=Decimal("0.12"), gt=0)
    min_open_interest: int = Field(default=100, ge=0)
    min_volume: int = Field(default=1, ge=0)
    min_bid: Decimal = Field(default=Decimal("0.10"), gt=0)
    max_bid_ask_spread_pct: Decimal = Field(default=Decimal("0.15"), gt=0)
    max_option_quote_age_seconds: int = Field(default=1800, ge=1)
    max_contracts_per_symbol: int = Field(default=1, ge=1)
    event_blackout_days: int = Field(default=7, ge=0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "CoveredCallStrategySettings":
        if self.min_dte > self.max_dte:
            raise ValueError("Covered call min_dte must be less than or equal to max_dte.")
        if self.delta_min > self.delta_target:
            raise ValueError("Covered call delta_min cannot exceed delta_target.")
        if self.delta_target > self.delta_max:
            raise ValueError("Covered call delta_target cannot exceed delta_max.")
        if self.min_otm_pct > self.max_otm_pct:
            raise ValueError("Covered call min_otm_pct must be less than or equal to max_otm_pct.")
        return self


class ZeroDteLotteryStrategySettings(BaseModel):
    enabled: bool = True
    auto_execute_enabled: bool = False
    scan_interval_seconds: int = Field(default=900, ge=60)
    scan_window_start_hour_et: int = Field(default=10, ge=0, le=23)
    scan_window_start_minute_et: int = Field(default=0, ge=0, le=59)
    scan_window_end_hour_et: int = Field(default=14, ge=0, le=23)
    scan_window_end_minute_et: int = Field(default=30, ge=0, le=59)
    symbols: tuple[str, ...] = ("QQQ.US",)
    max_premium_per_trade: Decimal = Field(default=Decimal("150"), gt=0)
    contracts_per_trade: int = Field(default=1, ge=1)
    max_trades_per_day: int = Field(default=1, ge=1)
    delta_target: Decimal = Field(default=Decimal("0.22"), gt=0)
    delta_min: Decimal = Field(default=Decimal("0.15"), gt=0)
    delta_max: Decimal = Field(default=Decimal("0.30"), gt=0)
    min_open_interest: int = Field(default=100, ge=0)
    min_volume: int = Field(default=10, ge=0)
    min_bid: Decimal = Field(default=Decimal("0.05"), gt=0)
    max_bid_ask_spread_pct: Decimal = Field(default=Decimal("0.20"), gt=0)
    max_option_quote_age_seconds: int = Field(default=1800, ge=1)
    min_direction_change_pct: Decimal = Field(default=Decimal("0.30"), ge=0)
    max_candidate_symbols: int = Field(default=80, ge=1)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "ZeroDteLotteryStrategySettings":
        if (self.scan_window_end_hour_et, self.scan_window_end_minute_et) <= (
            self.scan_window_start_hour_et,
            self.scan_window_start_minute_et,
        ):
            raise ValueError("Zero-DTE lottery scan window end must be after the scan window start.")
        if self.delta_min > self.delta_target:
            raise ValueError("Zero-DTE lottery delta_min cannot exceed delta_target.")
        if self.delta_target > self.delta_max:
            raise ValueError("Zero-DTE lottery delta_target cannot exceed delta_max.")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",
    )

    app_name: str = "Stocks Tool API"
    app_env: str = "local"
    log_level: str = "INFO"
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    allow_live_trading: bool = False
    default_broker: BrokerName = BrokerName.LONGBRIDGE
    postgres_db: str = "stocks_tool"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_port: int = 5432
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/stocks_tool"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    sqlalchemy_echo: bool = False
    reconciliation_scheduler_enabled: bool = True
    reconciliation_poll_interval_seconds: int = 15
    reconciliation_account_interval_seconds: int = 300
    reconciliation_orders_interval_seconds: int = 300
    reconciliation_working_orders_interval_seconds: int = 60
    market_event_auto_import_enabled: bool = False
    market_event_import_csv_path: str = ""
    market_event_import_interval_seconds: int = Field(default=3600, ge=60)
    market_event_provider_auto_import_enabled: bool = False
    market_event_provider: str = "fmp"
    market_event_provider_symbols: str = ""
    market_event_provider_lookahead_days: int = Field(default=30, ge=1)
    market_event_provider_timeout_seconds: int = Field(default=20, ge=1)
    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: int = Field(default=120, ge=1)
    deepseek_max_tokens: int = Field(default=4096, ge=256)
    deepseek_temperature: Decimal = Field(default=Decimal("0.2"), ge=0, le=2)
    longbridge_app_key: str = ""
    longbridge_app_secret: str = ""
    longbridge_access_token: str = ""
    longbridge_paper_access_token: str = ""
    longbridge_http_url: str = "https://openapi.longbridge.com"
    longbridge_quote_ws_url: str = "wss://openapi-quote.longbridge.com/v2"
    longbridge_trade_ws_url: str = "wss://openapi-trade.longbridge.com/v2"
    longbridge_language: str = "en"
    longbridge_enable_overnight: bool = False
    longbridge_print_quote_packages: bool = False
    longbridge_request_timeout_seconds: int = Field(default=20, ge=1)
    longbridge_circuit_breaker_seconds: int = 30
    longbridge_executor_max_workers: int = 2
    bull_put_strategy: BullPutSpreadStrategySettings = Field(
        default_factory=BullPutSpreadStrategySettings
    )
    covered_call_strategy: CoveredCallStrategySettings = Field(
        default_factory=CoveredCallStrategySettings
    )
    zero_dte_lottery_strategy: ZeroDteLotteryStrategySettings = Field(
        default_factory=ZeroDteLotteryStrategySettings
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
