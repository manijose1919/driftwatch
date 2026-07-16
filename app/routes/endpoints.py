"""CRUD + probe-now routes for monitored endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..alerts import dispatch_event
from ..auth import require_token
from ..config import settings
from ..database import get_db
from ..engine.prober import run_probe
from ..models import DriftEvent, Endpoint, Snapshot
from ..schemas import EndpointCreate, EndpointOut, EndpointUpdate, SnapshotOut
from .. import scheduler

router = APIRouter(prefix="/api/endpoints", tags=["endpoints"], dependencies=[Depends(require_token)])


def _open_event_counts(db: Session, endpoint_ids: list[int]) -> dict[int, int]:
    if not endpoint_ids:
        return {}
    rows = db.execute(
        select(DriftEvent.endpoint_id, func.count(DriftEvent.id))
        .where(DriftEvent.endpoint_id.in_(endpoint_ids), DriftEvent.acknowledged.is_(False))
        .group_by(DriftEvent.endpoint_id)
    ).all()
    return dict(rows)


def _to_out(endpoint: Endpoint, open_events: int) -> EndpointOut:
    out = EndpointOut.model_validate(endpoint)
    out.open_events = open_events
    return out


@router.get("", response_model=list[EndpointOut])
def list_endpoints(db: Session = Depends(get_db)):
    endpoints = db.scalars(select(Endpoint).order_by(Endpoint.id)).all()
    counts = _open_event_counts(db, [e.id for e in endpoints])
    return [_to_out(e, counts.get(e.id, 0)) for e in endpoints]


@router.post("", response_model=EndpointOut, status_code=201)
def create_endpoint(data: EndpointCreate, db: Session = Depends(get_db)):
    endpoint = Endpoint(**data.model_dump())
    db.add(endpoint)
    db.commit()
    if settings.scheduler_enabled:
        scheduler.schedule_endpoint(endpoint)
    return _to_out(endpoint, 0)


@router.get("/{endpoint_id}", response_model=EndpointOut)
def get_endpoint(endpoint_id: int, db: Session = Depends(get_db)):
    endpoint = db.get(Endpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(404, "endpoint not found")
    counts = _open_event_counts(db, [endpoint.id])
    return _to_out(endpoint, counts.get(endpoint.id, 0))


@router.put("/{endpoint_id}", response_model=EndpointOut)
def update_endpoint(endpoint_id: int, data: EndpointUpdate, db: Session = Depends(get_db)):
    endpoint = db.get(Endpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(404, "endpoint not found")

    fields = data.model_dump(exclude_unset=True)
    url_changed = "url" in fields and fields["url"] != endpoint.url
    if "interval_seconds" in fields and fields["interval_seconds"] is not None:
        fields["interval_seconds"] = max(fields["interval_seconds"], settings.min_interval_seconds)
    for key, value in fields.items():
        setattr(endpoint, key, value)

    if url_changed:
        # A different URL is a different contract: drop baselines so the
        # next probe re-baselines instead of reporting bogus drift.
        for snap in db.scalars(
            select(Snapshot).where(Snapshot.endpoint_id == endpoint.id)
        ):
            snap.is_baseline = False
        endpoint.last_status = "pending"

    db.commit()
    if settings.scheduler_enabled:
        scheduler.schedule_endpoint(endpoint)
    counts = _open_event_counts(db, [endpoint.id])
    return _to_out(endpoint, counts.get(endpoint.id, 0))


@router.delete("/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: int, db: Session = Depends(get_db)):
    endpoint = db.get(Endpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(404, "endpoint not found")
    db.delete(endpoint)
    db.commit()
    scheduler.unschedule_endpoint(endpoint_id)


@router.post("/{endpoint_id}/probe", response_model=EndpointOut)
async def probe_now(endpoint_id: int, db: Session = Depends(get_db)):
    endpoint = db.get(Endpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(404, "endpoint not found")
    event = await run_probe(endpoint_id)
    if event is not None:
        await dispatch_event(db, endpoint, event)
    db.expire_all()  # run_probe used its own session; re-read fresh state
    endpoint = db.get(Endpoint, endpoint_id)
    counts = _open_event_counts(db, [endpoint.id])
    return _to_out(endpoint, counts.get(endpoint.id, 0))


@router.get("/{endpoint_id}/snapshots", response_model=list[SnapshotOut])
def list_snapshots(endpoint_id: int, db: Session = Depends(get_db)):
    if db.get(Endpoint, endpoint_id) is None:
        raise HTTPException(404, "endpoint not found")
    return db.scalars(
        select(Snapshot)
        .where(Snapshot.endpoint_id == endpoint_id)
        .order_by(Snapshot.id.desc())
        .limit(50)
    ).all()
