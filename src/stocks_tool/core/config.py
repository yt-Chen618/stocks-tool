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
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/stocks_tool"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    longbridge_app_key: str = ""
    longbridge_app_secret: str = ""
    longbridge_access_token: str = ""
    longbridge_paper_access_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

