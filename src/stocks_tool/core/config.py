from decimal import Decimal
from functools import lru_cache

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from stocks_tool.domain.enums import BrokerName, ExecutionMode


class BullPutSpreadStrategySettings(BaseModel):
    enabled: bool = True
    auto_monitor_enabled: bool = True
    monitor_interval_seconds: int = Field(default=300, ge=1)
    symbols: tuple[str, ...] = ("QQQ.US", "SMH.US", "SOXL.US", "EWY.US")
    correlated_symbols: tuple[str, ...] = ("QQQ.US", "SMH.US", "SOXL.US")
    account_max_open_spreads: int = Field(default=2, ge=1)
    per_symbol_max_open_spreads: int = Field(default=1, ge=1)
    correlated_group_max_open_spreads: int = Field(default=1, ge=1)
    min_dte: int = Field(default=28, ge=1)
    max_dte: int = Field(default=35, ge=1)
    short_delta_target: Decimal = Field(default=Decimal("0.22"), gt=0)
    short_delta_min: Decimal = Field(default=Decimal("0.18"), gt=0)
    short_delta_max: Decimal = Field(default=Decimal("0.28"), gt=0)
    min_open_interest: int = Field(default=200, ge=1)
    max_bid_ask_spread_pct: Decimal = Field(default=Decimal("0.10"), gt=0)
    min_credit_per_width_ratio: Decimal = Field(default=Decimal("0.18"), gt=0)
    min_conservative_credit_per_width_ratio: Decimal = Field(default=Decimal("0.10"), gt=0)
    min_mid_credit: Decimal = Field(default=Decimal("0.20"), gt=0)
    contracts_per_trade: int = Field(default=1, ge=1)
    per_trade_max_account_risk_pct: Decimal = Field(default=Decimal("0.01"), gt=0)
    architecture_max_account_risk_pct: Decimal = Field(default=Decimal("0.02"), gt=0)
    take_profit_exit_ratio: Decimal = Field(default=Decimal("0.50"), ge=0)
    stop_loss_exit_multiple: Decimal = Field(default=Decimal("2.00"), gt=0)
    close_days_to_expiration: int = Field(default=7, ge=0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "BullPutSpreadStrategySettings":
        if self.min_dte > self.max_dte:
            raise ValueError("Bull put spread min_dte must be less than or equal to max_dte.")
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
    bull_put_strategy: BullPutSpreadStrategySettings = Field(
        default_factory=BullPutSpreadStrategySettings
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
