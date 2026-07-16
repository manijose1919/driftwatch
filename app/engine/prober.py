"""Probe executor: fetch an endpoint, infer its shape, detect + record drift.

`run_probe(endpoint_id)` owns its DB session so it can be called from the
scheduler, from API routes, and from tests alike. Network I/O is isolated in
`_request` so tests can monkeypatch it with canned payloads.
"""
import json
import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import (
    STATUS_DRIFT,
    STATUS_ERROR,
    STATUS_OK,
    DriftEvent,
    Endpoint,
    Snapshot,
    utcnow,
)
from .differ import diff_shapes, overall_severity
from .shape import infer_shape

log = logging.getLogger("driftwatch.prober")


class ProbeError(Exception):
    pass


async def _request(endpoint: Endpoint) -> tuple[object, int, float]:
    """Fetch the endpoint. Returns (parsed_json, status_code, elapsed_ms)."""
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.probe_timeout_seconds) as client:
            resp = await client.request(
                endpoint.method,
                endpoint.url,
                headers=endpoint.headers or {},
                content=endpoint.body,
            )
    except httpx.HTTPError as exc:
        raise ProbeError(f"request failed: {exc.__class__.__name__}: {exc}") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000

    if resp.status_code >= 300:
        raise ProbeError(f"unexpected status {resp.status_code}")
    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProbeError(f"response is not valid JSON: {exc}") from exc
    return payload, resp.status_code, elapsed_ms


async def run_probe(endpoint_id: int) -> DriftEvent | None:
    """Probe one endpoint. Returns the new DriftEvent if drift was detected."""
    db = SessionLocal()
    try:
        endpoint = db.get(Endpoint, endpoint_id)
        if endpoint is None or not endpoint.is_active:
            return None
        return await _probe(db, endpoint)
    finally:
        db.close()


async def _probe(db: Session, endpoint: Endpoint) -> DriftEvent | None:
    was_erroring = endpoint.last_status == STATUS_ERROR
    endpoint.last_probed_at = utcnow()

    try:
        payload, status_code, elapsed_ms = await _request(endpoint)
    except ProbeError as exc:
        endpoint.last_error = str(exc)
        endpoint.last_status = STATUS_ERROR
        event = None
        if not was_erroring:
            # Edge-triggered: alert once when an endpoint starts failing,
            # not on every scheduled probe while it stays down.
            event = DriftEvent(
                endpoint_id=endpoint.id,
                severity="error",
                changes=[{
                    "path": "$", "kind": "probe_error",
                    "severity": "error", "detail": str(exc),
                }],
            )
            db.add(event)
        db.commit()
        log.warning("probe error for endpoint %s (%s): %s", endpoint.id, endpoint.name, exc)
        return event

    endpoint.last_error = None
    endpoint.last_response_ms = elapsed_ms
    shape = infer_shape(payload)

    baseline = db.scalar(
        select(Snapshot)
        .where(Snapshot.endpoint_id == endpoint.id, Snapshot.is_baseline.is_(True))
        .order_by(Snapshot.id.desc())
    )

    if baseline is None:
        db.add(Snapshot(
            endpoint_id=endpoint.id, shape=shape, status_code=status_code,
            response_ms=elapsed_ms, is_baseline=True,
        ))
        endpoint.last_status = STATUS_OK
        db.commit()
        log.info("baseline captured for endpoint %s (%s)", endpoint.id, endpoint.name)
        return None

    changes = diff_shapes(baseline.shape, shape)
    if not changes:
        endpoint.last_status = STATUS_OK
        db.commit()
        return None

    endpoint.last_status = STATUS_DRIFT

    # Suppress duplicates: if the latest open event already describes this
    # exact shape, don't re-alert every probe while the drift persists.
    latest_open = db.scalar(
        select(DriftEvent)
        .where(DriftEvent.endpoint_id == endpoint.id, DriftEvent.acknowledged.is_(False))
        .order_by(DriftEvent.id.desc())
    )
    if latest_open is not None and latest_open.snapshot is not None:
        # Structural comparison (not dict equality): free-form string value
        # samples differ between probes without being drift.
        if not diff_shapes(latest_open.snapshot.shape, shape):
            db.commit()
            return None

    snapshot = Snapshot(
        endpoint_id=endpoint.id, shape=shape, status_code=status_code,
        response_ms=elapsed_ms, is_baseline=False,
    )
    db.add(snapshot)
    db.flush()  # assign snapshot.id
    event = DriftEvent(
        endpoint_id=endpoint.id,
        snapshot_id=snapshot.id,
        severity=overall_severity(changes),
        changes=changes,
    )
    db.add(event)
    db.commit()
    log.info(
        "drift detected for endpoint %s (%s): %s, %d change(s)",
        endpoint.id, endpoint.name, event.severity, len(changes),
    )
    return event
