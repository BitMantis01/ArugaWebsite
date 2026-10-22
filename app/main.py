import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

# Configure centralized stdout structured JSON logging before other application modules import
from app.observability import (
    setup_logging,
    setup_metrics,
    security_and_logging_middleware,
    global_exception_handler,
    cleanup_worker_metrics,
)

logger = setup_logging()

from app.config import SECRET_KEY, UPLOAD_DIR, ENABLE_API_DOCS, ENVIRONMENT
from app.database import init_db
from app.routers import auth, vitals, esp32, live_feed, dashboard
from app.services.csrf_service import verify_csrf_token

app = FastAPI(
    title="ARUGA - Intelligent Health Companion & Research Dashboard",
    version="1.1.0",
    description="Preventive Healthcare & Continuous Vital Sign Analytics API",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
)

# Global Unhandled Exception Handler (captures stack trace in JSON logs and delivers 500)
app.add_exception_handler(Exception, global_exception_handler)

# CORS Configuration
allowed_origins = [
    "https://aruga.bitmantis.xyz",
    "http://aruga.bitmantis.xyz",
]
if ENVIRONMENT == "development":
    allowed_origins.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Security Headers & Content-Security-Policy Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https://aruga.bitmantis.xyz; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss: wss://aruga.bitmantis.xyz https://aruga.bitmantis.xyz https://cdn.jsdelivr.net https://cloudflareinsights.com https://static.cloudflareinsights.com; "
        "frame-ancestors 'none';"
    )
    if ENVIRONMENT == "production" or request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# CSRF Protection Middleware for state-mutating requests
@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        path = request.url.path
        # Exempt hardware endpoints authenticated by x-api-key and WebSocket paths
        if not path.startswith("/api/server/") and not path.startswith("/ws/"):
            await verify_csrf_token(request)
    return await call_next(request)

# Add Session Middleware with secure cookie settings
is_production = ENVIRONMENT == "production"
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=is_production,
    same_site="lax",
    max_age=86400,  # 24 hours
)

# Observability, Request Correlation & Security Gate Middleware
app.middleware("http")(security_and_logging_middleware)

# Routine Health Check Endpoint (suppressed from Loki logs and metrics histograms)
@app.get("/health", tags=["monitoring"])
def health_check():
    return {"status": "healthy"}

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include Routers
app.include_router(dashboard.router)
app.include_router(auth.router)
app.include_router(vitals.router)
app.include_router(esp32.router)
app.include_router(live_feed.router)

# Instrument FastAPI app with Prometheus / VictoriaMetrics metrics at /metrics
setup_metrics(app)


@app.get("/health", status_code=200, tags=["health"])
async def health_check():
    return {"status": "ok"}


@app.on_event("startup")
def on_startup():
    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.on_event("shutdown")
def on_shutdown():
    cleanup_worker_metrics()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=4241, reload=True)
