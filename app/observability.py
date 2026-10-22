import atexit
import contextvars
import logging
import os
import sys
import time
import traceback
import uuid
from typing import Any, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger.jsonlogger import JsonFormatter

# Multiprocess directory configuration for multi-worker Gunicorn/uWSGI deployments
multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if multiproc_dir:
    os.makedirs(multiproc_dir, exist_ok=True)


def cleanup_worker_metrics() -> None:
    """Clean up Prometheus multiprocess files for the current worker process upon exit."""
    active_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if active_dir:
        try:
            from prometheus_client import multiprocess
            multiprocess.mark_process_dead(os.getpid())
        except Exception:
            pass


# Ensure process death is recorded automatically on process termination
atexit.register(cleanup_worker_metrics)

# Context variable for storing request correlation ID across async task execution
current_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_request_id", default=None
)

# Sensitive keys scrubbed from all structured log extras
SENSITIVE_KEYS = {
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "credentials",
    "turnstile_secret",
}

# Network CIDRs and prefixes allowed to scrape /metrics internally
ALLOWED_METRICS_NETWORKS = (
    "192.168.",
    "100.",       # Tailscale CGNAT range (100.64.0.0/10)
    "127.0.0.1",   # Loopback IPv4
    "172.",       # Docker bridge & private range (172.16.0.0/12)
    "10.",        # Private range (10.0.0.0/8)
    "::1",        # Loopback IPv6
    "localhost",
    "testclient",
)

# Known vulnerability and bot scan path signatures fast-dropped in <1ms
BOT_SCAN_PATTERNS = (
    "/.env",
    "/.git",
    "/.aws",
    "/wp-",
    "/phpmyadmin",
    "/actuator",
    "%2f",
)

# Routine static and monitoring paths suppressed from Loki log aggregation
SUPPRESSED_LOG_PREFIXES = (
    "/static/",
    "/metrics",
    "/health",
    "/favicon.ico",
)

# Prometheus Metrics Definitions
security_events_total = Counter(
    "security_events_total",
    "Security events, blocks, and bot mitigations",
    ["type"],
)

external_call_duration_seconds = Histogram(
    "external_call_duration_seconds",
    "Latency of outbound network or DB calls in seconds",
    ["target", "status"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)


def record_security_event(event_type: str) -> None:
    """Increment the security events counter for the specified mitigation type."""
    try:
        security_events_total.labels(type=event_type).inc()
    except Exception:
        pass


class track_external:
    """
    Lightweight context manager isolating downstream API, storage, and DB latency.
    Supports both synchronous ('with track_external(...)') and
    asynchronous ('async with track_external(...)') contexts.
    """

    def __init__(self, target: str):
        self.target = target
        self.status = "success"
        self.start = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.status = "error"
        duration = time.perf_counter() - self.start
        external_call_duration_seconds.labels(target=self.target, status=self.status).observe(duration)
        return False

    async def __aenter__(self):
        self.start = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.status = "error"
        duration = time.perf_counter() - self.start
        external_call_duration_seconds.labels(target=self.target, status=self.status).observe(duration)
        return False


def sanitize_sensitive_data(value: Any) -> Any:
    """Recursively scrub sensitive keys from dictionaries and lists."""
    if isinstance(value, dict):
        sanitized = {}
        for k, v in value.items():
            key_str = str(k).lower()
            if any(sensitive_key in key_str for sensitive_key in SENSITIVE_KEYS):
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = sanitize_sensitive_data(v)
        return sanitized
    if isinstance(value, list):
        return [sanitize_sensitive_data(item) for item in value]
    return value


class RedactingJsonFormatter(JsonFormatter):
    """
    JSON Formatter writing structured logs to stdout with automatic
    PII/secret scrubbing and request correlation ID injection.
    """

    def process_log_record(self, log_record: dict) -> dict:
        req_id = current_request_id.get()
        if req_id and "request_id" not in log_record:
            log_record["request_id"] = req_id

        for k, v in list(log_record.items()):
            key_lower = str(k).lower()
            if any(sensitive_key in key_lower for sensitive_key in SENSITIVE_KEYS):
                log_record[k] = "***REDACTED***"
            elif isinstance(v, (dict, list)):
                log_record[k] = sanitize_sensitive_data(v)

        return super().process_log_record(log_record)


def setup_logging() -> logging.Logger:
    """
    Configure stdout structured JSON logging across the application.
    Redirects root logger to sys.stdout and prevents duplicate plaintext logs.
    """
    log_handler = logging.StreamHandler(sys.stdout)
    formatter = RedactingJsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
            "exc_info": "exception",
        },
    )
    log_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = [log_handler]

    # Suppress duplicate unformatted plaintext lines from uvicorn's default access logger
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers = []
    uvicorn_access.propagate = False

    # Suppress verbose HTTP client logs
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return logging.getLogger("aruga")


logger = logging.getLogger("aruga")


def extract_client_ip(request: Request) -> str:
    """Extract authoritative client IP respecting reverse proxy headers."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_metrics_client_allowed(request: Request) -> bool:
    """
    Verify if request to /metrics originates from an internal network.
    Rejects any request arriving via public Cloudflare proxy or untrusted X-Forwarded-For.
    """
    if request.headers.get("CF-Connecting-IP"):
        return False

    xff = request.headers.get("X-Forwarded-For")
    if xff:
        origin_ip = xff.split(",")[0].strip()
        if not origin_ip.startswith(ALLOWED_METRICS_NETWORKS):
            return False

    client_ip = request.client.host if request.client else ""
    return client_ip.startswith(ALLOWED_METRICS_NETWORKS) or client_ip in (
        "127.0.0.1",
        "::1",
        "localhost",
        "testclient",
    )


def extract_or_generate_request_id(request: Request) -> str:
    """Extract correlation ID from Cloudflare CF-Ray / X-Request-ID or generate 8-char UUID."""
    return (
        request.headers.get("CF-Ray")
        or request.headers.get("X-Request-ID")
        or uuid.uuid4().hex[:8]
    )


async def security_and_logging_middleware(request: Request, call_next):
    """
    Core observability & security middleware:
    1. Injects correlation ID (request_id) into context & response headers.
    2. Enforces security gate on /metrics (rejecting public traffic with 403).
    3. Fast-drops automated bot vulnerability probes in <1ms with 404.
    4. Logs structured access records to stdout for Loki aggregation.
    """
    req_id = extract_or_generate_request_id(request)
    request.state.request_id = req_id
    token = current_request_id.set(req_id)
    path_lower = request.url.path.lower()

    try:
        # Security Gate: Reject public internet traffic hitting /metrics
        if path_lower.rstrip("/") == "/metrics":
            if not is_metrics_client_allowed(request):
                record_security_event("metrics_blocked")
                return JSONResponse(
                    status_code=403,
                    content={"error": "Forbidden: Internal metrics endpoint", "request_id": req_id},
                    headers={"X-Request-ID": req_id},
                )
            return await call_next(request)

        # Bot Defense: Fast-drop common vulnerability probes instantly (<1ms)
        if any(pattern in path_lower for pattern in BOT_SCAN_PATTERNS):
            record_security_event("scanner_probe")
            logger.info(
                "HTTP request handled",
                extra={
                    "request_id": req_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 404,
                    "latency_ms": 0.1,
                    "is_bot": True,
                    "client_ip": extract_client_ip(request),
                },
            )
            return JSONResponse(
                status_code=404,
                content={"error": "Not Found", "request_id": req_id},
                headers={"X-Request-ID": req_id},
            )

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                f"Unhandled Server Exception: {str(exc)}",
                extra={
                    "request_id": req_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "latency_ms": duration_ms,
                    "exception": traceback.format_exc(),
                    "client_ip": extract_client_ip(request),
                },
            )
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "request_id": req_id},
                headers={"X-Request-ID": req_id},
            )

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = req_id

        # Suppress routine health checks, metrics, and static assets from flooding Loki
        if not any(request.url.path.startswith(prefix) for prefix in SUPPRESSED_LOG_PREFIXES):
            is_bot = response.status_code == 404
            log_level = logging.INFO if is_bot or response.status_code < 500 else logging.ERROR
            logger.log(
                log_level,
                "HTTP request handled",
                extra={
                    "request_id": req_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "latency_ms": duration_ms,
                    "is_bot": is_bot,
                    "client_ip": extract_client_ip(request),
                },
            )

        return response

    finally:
        current_request_id.reset(token)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all unhandled exception handler ensuring stack trace capture
    in JSON stdout logs and guaranteed 500 response delivery.
    """
    req_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        f"Unhandled Server Exception: {str(exc)}",
        extra={
            "request_id": req_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": 500,
            "exception": traceback.format_exc(),
            "client_ip": extract_client_ip(request),
        },
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "request_id": req_id},
        headers={"X-Request-ID": req_id},
    )


def setup_metrics(app: FastAPI) -> Instrumentator:
    """
    Configure Prometheus / VictoriaMetrics metrics instrumentator.
    Excludes static assets, health checks, and metrics endpoint from latency histograms.
    Restricts high-resolution latency tracking strictly to 2xx responses to prevent
    bot scans from distorting p50, p95, and p99 percentile calculations.
    """
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/health", "/favicon.ico", ".*static.*"],
    )
    instrumentator.instrument(app, should_only_respect_2xx_for_highr=True).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
    )
    return instrumentator
