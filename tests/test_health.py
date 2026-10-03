from fastapi.testclient import TestClient

from stocks_tool.main import app
from stocks_tool.api.routes import health


def test_healthcheck() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_health_contract_remains_minimal() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": response.json()["app"],
        "environment": response.json()["environment"],
        "execution_mode": response.json()["execution_mode"],
        "live_trading_enabled": response.json()["live_trading_enabled"],
    }


def test_liveness_does_not_touch_database() -> None:
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]


def test_readiness_separates_read_only_usability_from_trade_readiness(monkeypatch) -> None:
    settings = health.get_settings()
    monkeypatch.setattr(
        health,
        "get_settings",
        lambda: settings.model_copy(update={"reconciliation_scheduler_enabled": True}),
    )
    monkeypatch.setattr(
        health,
        "_database_readiness",
        lambda: ({"status": "ok"}, {"status": "ok", "revision": "test-head"}),
    )
    monkeypatch.setattr(
        health,
        "_cached_quarantine_readiness",
        lambda: {
            "status": "not_initialized",
            "broker_session_initialized": False,
            "pending_count": None,
        },
    )
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] == {
        "usable": True,
        "status": "usable",
        "reason_codes": ["scheduler_heartbeat_missing"],
    }
    assert body["trade_readiness"]["ready"] is False
    assert "broker_session_not_initialized" in body["trade_readiness"]["reason_codes"]
    assert "account_authorization_not_evaluated" in body["trade_readiness"]["reason_codes"]
    assert body["execution_controls"]["zero_dte_execution_locked"] is True


def test_readiness_does_not_construct_uncached_broker_adapter(monkeypatch) -> None:
    class CacheInfo:
        currsize = 0

    class Factory:
        def __init__(self) -> None:
            self.calls = 0

        def cache_info(self):
            return CacheInfo()

        def __call__(self):
            self.calls += 1
            raise AssertionError("readiness must not construct the broker adapter")

    factory = Factory()
    monkeypatch.setattr(health, "get_longbridge_adapter", factory)
    assert health._cached_quarantine_readiness()["status"] == "not_initialized"
    assert factory.calls == 0


def test_readiness_reports_dependency_failure_without_driver_text(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "_database_readiness",
        lambda: (
            {"status": "unavailable", "reason_code": "database_unavailable"},
            {"status": "unknown", "reason_code": "schema_unavailable"},
        ),
    )
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["read_only"]["usable"] is False
    assert body["checks"]["database"]["reason_code"] == "database_unavailable"
    assert "password" not in response.text.lower()


def test_clear_infrastructure_never_greenlights_global_trade_readiness(monkeypatch) -> None:
    settings = health.get_settings().model_copy(
        update={
            "reconciliation_scheduler_enabled": False,
            "allow_live_trading": False,
            "bull_put_strategy": health.get_settings().bull_put_strategy.model_copy(
                update={"entry_kill_switch_active": True}
            ),
        }
    )
    monkeypatch.setattr(health, "get_settings", lambda: settings)
    monkeypatch.setattr(
        health,
        "_database_readiness",
        lambda: ({"status": "ok"}, {"status": "ok", "revision": "test-head"}),
    )
    monkeypatch.setattr(
        health,
        "_cached_quarantine_readiness",
        lambda: {
            "status": "clear",
            "broker_session_initialized": True,
            "pending_count": 0,
        },
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"]["usable"] is True
    assert body["trade_readiness"]["ready"] is False
    assert body["trade_readiness"]["status"] == "requires_account_authorization"
    assert "account_authorization_not_evaluated" in body["trade_readiness"]["reason_codes"]
    assert body["execution_controls"]["bull_put_entry_kill_switch_active"] is True
