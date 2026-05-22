from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from stocks_tool.domain.enums import BrokerName, ExecutionMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
