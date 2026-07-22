"""Liveness/readiness probe for Docker HEALTHCHECK and uptime monitors.

Deliberately unauthenticated (no `require_token` dependency): health checks
can't carry the API bearer token, and this endpoint exposes nothing sensitive.
Returns 200 when the database is reachable, 503 otherwise, so an orchestrator
can restart or route around an unhealthy instance.
"""
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..database import SessionLocal
from ..scheduler import scheduler

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(request: Request, response: Response) -> dict:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        db_ok = False
    finally:
        db.close()

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    if not settings.scheduler_enabled:
        scheduler_state = "disabled"
    else:
        scheduler_state = "running" if scheduler.running else "stopped"

    return {
        "status": "ok" if db_ok else "unavailable",
        "version": request.app.version,
        "database": "ok" if db_ok else "unreachable",
        "scheduler": scheduler_state,
    }
