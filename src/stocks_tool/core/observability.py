"""Small, dependency-free runtime observability helpers.

The application is intentionally a local modular monolith.  These helpers keep
request diagnostics useful without introducing a metrics service, storing
request contents, or allowing arbitrary URL values to become metric labels.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import re
import threading
import time
from typing import Any
from uuid import uuid4

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_request_id_context: ContextVar[str | None] = ContextVar("stocks_tool_request_id", default=None)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_INTEGER_SEGMENT = re.compile(r"^[0-9]+$")
_UUID_SEGMENT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


_REDACTION_PATTERNS = (
    (
        re.compile(
            r"(?i)(?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
        ),
        "authorization=[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(?:password|passwd|secret|token|api[_-]?key|access[_-]?token|refresh[_-]?token)"
            r"\s*[:=]\s*[^\s,;&]+"
        ),
        "credential=[REDACTED]",
    ),
    (
        re.compile(r"(?i)(?<=://)[^\s/@:]+:[^\s/@]+@"),
        "[REDACTED]@",
    ),
    (
        re.compile(r"(?i)\b(?:sk|pk|lb|ds)_[A-Za-z0-9_-]{8,}\b"),
        "[REDACTED]",
    ),
)


def current_request_id() -> str | None:
    """Return the request id for the current task, if one is active."""

    return _request_id_context.get()


def resolve_request_id(raw_value: str | None) -> str:
    """Accept a bounded safe request id or issue a fresh opaque one.

    A caller supplied id is useful when correlating a browser action with a
    server log, but arbitrary header values are not allowed to become log
    injection or unbounded-cardinality input.
    """

    if raw_value and _SAFE_REQUEST_ID.fullmatch(raw_value):
        return raw_value
    return uuid4().hex


def redact_text(value: object, *, max_length: int = 512) -> str:
    """Return a short, conservative representation safe for logs and errors."""

    text = str(value)
    for pattern, replacement in _REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    text = text.replace("\x00", "\\0").replace("\r", "\\r").replace("\n", "\\n")
    if len(text) > max_length:
        return f"{text[: max_length - 3]}..."
    return text


def stable_error_code(error: BaseException) -> str:
    """Map an exception to a low-cardinality, non-secret error code."""

    name = type(error).__name__.lower()
    message = redact_text(error, max_length=256).lower()
    if "timeout" in name or "timeout" in message or "timed out" in message:
        return "timeout"
    if "validation" in name or "invalid" in name:
        return "validation_error"
    if "permission" in name or "forbidden" in message or "unauthorized" in message:
        return "permission_error"
    if (
        "sql" in name
        or "database" in name
        or "connection" in name
        or "could not connect" in message
    ):
        return "dependency_unavailable"
    return "internal_error"


def sanitized_error(error: BaseException) -> dict[str, str]:
    """Build a stable error summary without returning an exception payload."""

    return {
        "code": stable_error_code(error),
        "message": redact_text(error),
    }


def sanitize_http_detail(detail: object) -> object:
    """Redact sensitive substrings while preserving established detail shapes."""

    if isinstance(detail, str):
        return redact_text(detail)
    if isinstance(detail, dict):
        return {str(key): sanitize_http_detail(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [sanitize_http_detail(value) for value in detail]
    if isinstance(detail, tuple):
        return [sanitize_http_detail(value) for value in detail]
    return detail


def normalize_route(path: str, route_template: str | None = None) -> str:
    """Return a bounded route label suitable for rolling metrics."""

    if route_template and route_template.startswith("/"):
        return route_template
    parts: list[str] = []
    for part in path.split("/"):
        if not part:
            continue
        if _INTEGER_SEGMENT.fullmatch(part) or _UUID_SEGMENT.fullmatch(part):
            parts.append("{id}")
        elif len(part) > 48:
            parts.append("{value}")
        else:
            parts.append(part)
    return "/" + "/".join(parts) if parts else "/"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


@dataclass
class _LatencyWindow:
    samples: deque[float]
    request_count: int = 0
    error_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)


class RollingLatencyMetrics:
    """Bounded rolling latency observations with low-cardinality route labels."""

    def __init__(self, *, max_samples: int = 256, max_routes: int = 64) -> None:
        self.max_samples = max(16, max_samples)
        self.max_routes = max(4, max_routes)
        self._lock = threading.Lock()
        self._all = _LatencyWindow(deque(maxlen=self.max_samples))
        self._by_route: OrderedDict[str, _LatencyWindow] = OrderedDict()
        self._generated_at = datetime.now(timezone.utc)

    def observe(
        self,
        *,
        method: str,
        route: str,
        latency_ms: float,
        status_code: int,
    ) -> None:
        bounded_route = f"{method.upper()} {route if route == '<unknown>' else normalize_route(route)}"
        with self._lock:
            self._record(self._all, latency_ms=latency_ms, status_code=status_code)
            window = self._by_route.get(bounded_route)
            if window is None:
                if len(self._by_route) >= self.max_routes:
                    self._by_route.popitem(last=False)
                window = _LatencyWindow(deque(maxlen=self.max_samples))
                self._by_route[bounded_route] = window
            else:
                self._by_route.move_to_end(bounded_route)
            self._record(window, latency_ms=latency_ms, status_code=status_code)
            self._generated_at = datetime.now(timezone.utc)

    @staticmethod
    def _record(window: _LatencyWindow, *, latency_ms: float, status_code: int) -> None:
        window.samples.append(max(0.0, float(latency_ms)))
        window.request_count += 1
        status_key = str(status_code)
        window.status_counts[status_key] = window.status_counts.get(status_key, 0) + 1
        if status_code >= 500:
            window.error_count += 1

    @staticmethod
    def _snapshot_window(window: _LatencyWindow) -> dict[str, Any]:
        values = list(window.samples)
        return {
            "sample_count": len(values),
            "request_count": window.request_count,
            "error_count": window.error_count,
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
            "p99_ms": _percentile(values, 0.99),
            "last_latency_ms": round(values[-1], 3) if values else None,
            "status_counts": dict(sorted(window.status_counts.items())),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "generated_at": self._generated_at.isoformat(),
                "window_size": self.max_samples,
                "route_limit": self.max_routes,
                "overall": self._snapshot_window(self._all),
                "routes": {
                    route: self._snapshot_window(window)
                    for route, window in self._by_route.items()
                },
            }


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach request ids, bounded latency observations, and safe 500 errors."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        token = _request_id_context.set(request_id)
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
        except Exception as error:
            code = stable_error_code(error)
            logger.error(
                "Unhandled request error request_id=%s code=%s error=%s",
                request_id,
                code,
                redact_text(error),
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error.",
                    "error_code": "internal_server_error",
                    "request_id": request_id,
                },
            )
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            metrics = getattr(request.app.state, "observability_metrics", None)
            if isinstance(metrics, RollingLatencyMetrics):
                route_template = getattr(request.scope.get("route"), "path", None)
                route = (
                    normalize_route(request.url.path, route_template)
                    if route_template
                    else "<unknown>"
                )
                metrics.observe(
                    method=request.method,
                    route=route,
                    latency_ms=latency_ms,
                    status_code=getattr(response, "status_code", 500),
                )
            _request_id_context.reset(token)

        assert response is not None
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-Ms"] = f"{latency_ms:.3f}"
        return response
