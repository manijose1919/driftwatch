"""Data retention: prune old acknowledged events and orphaned snapshots.

Runs daily from the scheduler. Keeps the SQLite file small indefinitely:
- acknowledged drift events older than the retention window are deleted;
- non-baseline snapshots older than the window are deleted once no remaining
  event references them (as either observed or baseline shape).

Open (unacknowledged) events are never pruned — unreviewed drift stays visible.
"""
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from .config import settings
from .database import SessionLocal
from .models import DriftEvent, ProbeResult, Snapshot, utcnow

log = logging.getLogger("driftwatch.retention")


def prune_old_data() -> dict:
    if settings.retention_days <= 0:
        return {"events": 0, "snapshots": 0, "probe_results": 0}
    cutoff = utcnow() - timedelta(days=settings.retention_days)

    db = SessionLocal()
    try:
        # Probe metrics are pure time series — safe to drop past the window
        # unconditionally (nothing references them).
        probe_results_deleted = db.execute(
            delete(ProbeResult).where(ProbeResult.created_at < cutoff)
        ).rowcount

        events_deleted = db.execute(
            delete(DriftEvent).where(
                DriftEvent.acknowledged.is_(True),
                DriftEvent.created_at < cutoff,
            )
        ).rowcount

        referenced_observed = select(DriftEvent.snapshot_id).where(
            DriftEvent.snapshot_id.is_not(None)
        )
        referenced_baseline = select(DriftEvent.baseline_snapshot_id).where(
            DriftEvent.baseline_snapshot_id.is_not(None)
        )
        snapshots_deleted = db.execute(
            delete(Snapshot).where(
                Snapshot.is_baseline.is_(False),
                Snapshot.created_at < cutoff,
                Snapshot.id.not_in(referenced_observed),
                Snapshot.id.not_in(referenced_baseline),
            )
        ).rowcount

        db.commit()
    finally:
        db.close()

    if events_deleted or snapshots_deleted or probe_results_deleted:
        log.info(
            "retention prune: removed %d event(s), %d snapshot(s), %d probe result(s) "
            "older than %d day(s)",
            events_deleted, snapshots_deleted, probe_results_deleted, settings.retention_days,
        )
    return {
        "events": events_deleted,
        "snapshots": snapshots_deleted,
        "probe_results": probe_results_deleted,
    }
