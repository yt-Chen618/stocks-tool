from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import BrokerName, ExecutionMode
from stocks_tool.domain.models import (
    BrokerCapability,
    BrokerConfigurationStatus,
    BrokerProfile,
)
from stocks_tool.ports.broker import BrokerAdapter


class LongbridgeBrokerAdapter(BrokerAdapter):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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

