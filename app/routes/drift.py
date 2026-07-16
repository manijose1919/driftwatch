"""Drift-event routes: feed, acknowledge, accept-as-baseline, stats."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_token
from ..database import get_db
from ..models import STATUS_ERROR, STATUS_OK, DriftEvent, Endpoint, Snapshot
from ..schemas import DriftEventOut, StatsOut

router = APIRouter(prefix="/api", tags=["drift"], dependencies=[Depends(require_token)])


def _to_out(event: DriftEvent, endpoint_name: str) -> DriftEventOut:
    out = DriftEventOut.model_validate(event)
    out.endpoint_name = endpoint_name
    return out


@router.get("/events", response_model=list[DriftEventOut])
def list_events(
    endpoint_id: int | None = None,
    include_acknowledged: bool = True,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = select(DriftEvent, Endpoint.name).join(Endpoint, DriftEvent.endpoint_id == Endpoint.id)
    if endpoint_id is not None:
        q = q.where(DriftEvent.endpoint_id == endpoint_id)
    if not include_acknowledged:
        q = q.where(DriftEvent.acknowledged.is_(False))
    q = q.order_by(DriftEvent.id.desc()).limit(min(limit, 500))
    return [_to_out(event, name) for event, name in db.execute(q).all()]


@router.post("/events/{event_id}/ack", response_model=DriftEventOut)
def acknowledge_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(DriftEvent, event_id)
    if event is None:
        raise HTTPException(404, "event not found")
    event.acknowledged = True
    db.commit()
    return _to_out(event, event.endpoint.name)


@router.post("/events/{event_id}/accept", response_model=DriftEventOut)
def accept_event(event_id: int, db: Session = Depends(get_db)):
    """Accept the drifted shape as the new baseline and close the event.

    'This change is intentional/fine — measure future drift against it.'
    """
    event = db.get(DriftEvent, event_id)
    if event is None:
        raise HTTPException(404, "event not found")
    if event.snapshot is None:
        raise HTTPException(400, "event has no snapshot to accept (probe error events cannot be accepted)")

    for snap in db.scalars(
        select(Snapshot).where(
            Snapshot.endpoint_id == event.endpoint_id, Snapshot.is_baseline.is_(True)
        )
    ):
        snap.is_baseline = False
    event.snapshot.is_baseline = True
    event.acknowledged = True

    # Close sibling open events: they were measured against the old baseline.
    for sibling in db.scalars(
        select(DriftEvent).where(
            DriftEvent.endpoint_id == event.endpoint_id,
            DriftEvent.acknowledged.is_(False),
        )
    ):
        sibling.acknowledged = True

    event.endpoint.last_status = STATUS_OK
    db.commit()
    return _to_out(event, event.endpoint.name)


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)):
    endpoints = db.scalar(select(func.count(Endpoint.id))) or 0
    active = db.scalar(
        select(func.count(Endpoint.id)).where(Endpoint.is_active.is_(True))
    ) or 0
    open_events = db.scalar(
        select(func.count(DriftEvent.id)).where(DriftEvent.acknowledged.is_(False))
    ) or 0
    open_breaking = db.scalar(
        select(func.count(DriftEvent.id)).where(
            DriftEvent.acknowledged.is_(False), DriftEvent.severity == "breaking"
        )
    ) or 0
    probes_ok = db.scalar(
        select(func.count(Endpoint.id)).where(Endpoint.last_status == STATUS_OK)
    ) or 0
    probes_error = db.scalar(
        select(func.count(Endpoint.id)).where(Endpoint.last_status == STATUS_ERROR)
    ) or 0
    return StatsOut(
        endpoints=endpoints,
        active_endpoints=active,
        open_events=open_events,
        open_breaking=open_breaking,
        probes_ok=probes_ok,
        probes_error=probes_error,
    )
