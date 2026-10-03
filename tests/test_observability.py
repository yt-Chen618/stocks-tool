import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocks_tool.core.observability import (
    ObservabilityMiddleware,
    RollingLatencyMetrics,
    redact_text,
    resolve_request_id,
)
from stocks_tool.main import _await_shutdown_task


def test_request_id_accepts_safe_value_and_replaces_unbounded_value() -> None:
    assert resolve_request_id("browser-123") == "browser-123"
    generated = resolve_request_id("x" * 1000)
    assert len(generated) == 32
    assert generated != "x" * 1000


def test_redaction_removes_credentials_and_bounds_error_text() -> None:
    redacted = redact_text(
        "https://user:password@example.test/path?access_token=secret-value "
        "authorization=Bearer abc123"
    )
    assert "password@example" not in redacted
    assert "secret-value" not in redacted
    assert "abc123" not in redacted
    assert len(redact_text("x" * 1000)) == 512


def test_rolling_metrics_are_bounded_and_compute_percentiles() -> None:
    metrics = RollingLatencyMetrics(max_samples=16, max_routes=4)
    for index in range(100):
        metrics.observe(
            method="GET",
            route=f"/items/{index}",
            latency_ms=index + 1,
            status_code=200,
        )
    snapshot = metrics.snapshot()
    assert snapshot["overall"]["sample_count"] == 16
    assert len(snapshot["routes"]) <= 4
    assert snapshot["overall"]["p50_ms"] is not None
    assert snapshot["overall"]["p95_ms"] is not None
    assert snapshot["overall"]["p99_ms"] is not None


def test_middleware_returns_fixed_unexpected_error_and_request_id(caplog) -> None:
    app = FastAPI()
    app.state.observability_metrics = RollingLatencyMetrics()
    app.add_middleware(ObservabilityMiddleware)

    @app.get("/boom/{item}")
    def boom(item: str):
        raise RuntimeError("password=super-secret")

    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        response = client.get("/boom/one", headers={"X-Request-ID": "test-request"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "test-request"
    assert response.json() == {
        "detail": "Internal server error.",
        "error_code": "internal_server_error",
        "request_id": "test-request",
    }
    assert "super-secret" not in caplog.text
    assert "credential=[REDACTED]" in caplog.text
    snapshot = app.state.observability_metrics.snapshot()
    assert snapshot["overall"]["error_count"] == 1
    assert "GET /boom/{item}" in snapshot["routes"]


def test_shutdown_timeout_keeps_inflight_task_unknown(caplog) -> None:
    async def exercise() -> tuple[bool, bool]:
        async def never_finishes() -> None:
            await asyncio.Event().wait()

        task = asyncio.create_task(never_finishes())
        result = await _await_shutdown_task(
            task,
            label="test scheduler",
            timeout_seconds=0.01,
        )
        pending = not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return result, pending

    with caplog.at_level(logging.ERROR):
        result, pending = asyncio.run(exercise())
    assert result is False
    assert "UNKNOWN" in caplog.text
    assert pending is True
