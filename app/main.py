import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import SECRET_KEY, UPLOAD_DIR
from app.database import init_db
from app.routers import auth, vitals, esp32, live_feed, dashboard

app = FastAPI(
    title="ARUGA - Intelligent Health Companion & Research Dashboard",
    version="1.1.0",
    description="Preventive Healthcare & Continuous Vital Sign Analytics API",
)

# Add Session Middleware with central secret key
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include Routers
app.include_router(dashboard.router)
app.include_router(auth.router)
app.include_router(vitals.router)
app.include_router(esp32.router)
app.include_router(live_feed.router)


@app.on_event("startup")
def on_startup():
    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
