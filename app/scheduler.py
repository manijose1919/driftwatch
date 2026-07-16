"""APScheduler wiring: one interval job per active endpoint."""
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from .alerts import dispatch_event
from .database import SessionLocal
from .engine.prober import run_probe
from .models import Endpoint

log = logging.getLogger("driftwatch.scheduler")

scheduler = AsyncIOScheduler()

_FIRST_RUN_DELAY = timedelta(seconds=3)  # baseline new endpoints almost immediately


async def probe_and_alert(endpoint_id: int) -> None:
    """The scheduled unit of work: probe, then alert if drift was found."""
    event = await run_probe(endpoint_id)
    if event is None:
        return
    db = SessionLocal()
    try:
        endpoint = db.get(Endpoint, endpoint_id)
        if endpoint is not None:
            await dispatch_event(db, endpoint, event)
    finally:
        db.close()


def schedule_endpoint(endpoint: Endpoint) -> None:
    job_id = f"endpoint-{endpoint.id}"
    if not endpoint.is_active:
        unschedule_endpoint(endpoint.id)
        return
    scheduler.add_job(
        probe_and_alert,
        "interval",
        seconds=endpoint.interval_seconds,
        id=job_id,
        args=[endpoint.id],
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + _FIRST_RUN_DELAY,
        max_instances=1,
        coalesce=True,
    )
    log.info(
        "scheduled endpoint %s (%s) every %ss",
        endpoint.id, endpoint.name, endpoint.interval_seconds,
    )


def unschedule_endpoint(endpoint_id: int) -> None:
    job = scheduler.get_job(f"endpoint-{endpoint_id}")
    if job is not None:
        job.remove()


def sync_all_jobs() -> None:
    """Align scheduler jobs with the endpoints table (called at startup)."""
    db = SessionLocal()
    try:
        endpoints = db.scalars(select(Endpoint)).all()
    finally:
        db.close()
    for endpoint in endpoints:
        schedule_endpoint(endpoint)


def start() -> None:
    sync_all_jobs()
    scheduler.start()
    log.info("scheduler started with %d job(s)", len(scheduler.get_jobs()))


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
