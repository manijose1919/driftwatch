"""Retention pruning: old acknowledged events and orphaned snapshots go; open drift stays."""
from datetime import timedelta

from app.config import settings
from app.database import SessionLocal
from app.models import DriftEvent, Endpoint, Snapshot, utcnow
from app.retention import prune_old_data

OLD = utcnow() - timedelta(days=40)
RECENT = utcnow() - timedelta(days=1)


def seed(db):
    ep = Endpoint(name="e", url="https://x.example.com", method="GET", headers={})
    db.add(ep)
    db.flush()
    baseline = Snapshot(endpoint_id=ep.id, shape={"type": "object", "fields": {}},
                        is_baseline=True, created_at=OLD)
    db.add(baseline)
    db.flush()
    return ep, baseline


def snap(db, ep, created_at):
    s = Snapshot(endpoint_id=ep.id, shape={"type": "integer"}, is_baseline=False,
                 created_at=created_at)
    db.add(s)
    db.flush()
    return s


def event(db, ep, snapshot, baseline, created_at, acknowledged):
    e = DriftEvent(endpoint_id=ep.id, snapshot_id=snapshot.id,
                   baseline_snapshot_id=baseline.id, severity="breaking",
                   changes=[], acknowledged=acknowledged, created_at=created_at)
    db.add(e)
    db.flush()
    return e


def test_prune_removes_old_acked_keeps_open_and_recent(client, monkeypatch):
    monkeypatch.setattr(settings, "retention_days", 30)
    db = SessionLocal()
    try:
        ep, baseline = seed(db)
        old_acked_snap = snap(db, ep, OLD)
        old_open_snap = snap(db, ep, OLD)
        recent_snap = snap(db, ep, RECENT)

        old_acked = event(db, ep, old_acked_snap, baseline, OLD, acknowledged=True)
        old_open = event(db, ep, old_open_snap, baseline, OLD, acknowledged=False)
        recent_acked = event(db, ep, recent_snap, baseline, RECENT, acknowledged=True)
        db.commit()

        result = prune_old_data()
        assert result["events"] == 1      # only the old acknowledged event
        assert result["snapshots"] == 1   # its snapshot, now orphaned

        remaining_events = {e.id for e in db.query(DriftEvent).all()}
        assert old_acked.id not in remaining_events
        assert old_open.id in remaining_events        # open drift is never pruned
        assert recent_acked.id in remaining_events    # inside retention window

        remaining_snaps = {s.id for s in db.query(Snapshot).all()}
        assert old_acked_snap.id not in remaining_snaps
        assert old_open_snap.id in remaining_snaps    # still referenced by open event
        assert baseline.id in remaining_snaps         # baselines are never pruned
    finally:
        db.close()


def test_prune_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "retention_days", 0)
    db = SessionLocal()
    try:
        ep, baseline = seed(db)
        s = snap(db, ep, OLD)
        event(db, ep, s, baseline, OLD, acknowledged=True)
        db.commit()
        assert prune_old_data() == {"events": 0, "snapshots": 0, "probe_results": 0}
        assert db.query(DriftEvent).count() == 1
    finally:
        db.close()
