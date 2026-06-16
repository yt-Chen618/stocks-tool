from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_longbridge_adapter
from stocks_tool.domain.enums import BrokerName, ExecutionMode
from stocks_tool.domain.models import BrokerCapability, BrokerProfile
from stocks_tool.main import app


class StubBrokerAdapter:
    def get_profile(self) -> BrokerProfile:
        return BrokerProfile(
            id="longbridge-paper-LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            name=BrokerName.LONGBRIDGE,
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            supported_modes=[ExecutionMode.PAPER, ExecutionMode.LIVE],
            capabilities=[
                BrokerCapability(
                    name="paper_trading",
                    supported=True,
                    notes="Paper trading is suitable for first-pass validation.",
                )
            ],
            readonly=False,
            paper_guard="config_declared",
            configured=True,
            credential_status="ready",
            notes=["Paper guard is declared by local configuration."],
        )


def test_broker_profiles_route_returns_unified_profile_shape() -> None:
    app.dependency_overrides[get_longbridge_adapter] = lambda: StubBrokerAdapter()
    client = TestClient(app)
    try:
        response = client.get("/brokers/profiles")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "longbridge-paper-LBPT10087357"
    assert body[0]["broker"] == "longbridge"
    assert body[0]["external_account_id"] == "LBPT10087357"
    assert body[0]["mode"] == "paper"
    assert body[0]["paper_guard"] == "config_declared"
    assert body[0]["credential_status"] == "ready"


def test_legacy_longbridge_profile_route_keeps_profile_available() -> None:
    app.dependency_overrides[get_longbridge_adapter] = lambda: StubBrokerAdapter()
    client = TestClient(app)
    try:
        response = client.get("/brokers/longbridge/profile")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "longbridge"
    assert body["broker"] == "longbridge"
    assert body["paper_guard"] == "config_declared"
