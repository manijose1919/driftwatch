"""DriftWatch application entrypoint.

Run with:  uvicorn app.main:app --port 8000
Dashboard: http://127.0.0.1:8000/
API docs:  http://127.0.0.1:8000/docs
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .config import settings
from .database import init_db
from .routes import channels, demo, drift, endpoints, health

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.scheduler_enabled:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="DriftWatch",
    description="Self-hosted API contract drift sentinel: watches third-party "
                "JSON APIs and alerts when their response *shape* changes.",
    version="1.2.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(endpoints.router)
app.include_router(drift.router)
app.include_router(channels.router)
app.include_router(demo.router)

app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")
