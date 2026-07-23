"""Per-probe metrics: ProbeResult recording, the /history route, and pruning."""
from datetime import timedelta

from app.models import ProbeResult, utcnow


def _add_endpoint(client, **over):
    body = {"name": "hist", "url": "https://api.test/x", "interval_seconds": 300}
    body.update(over)
    return client.post("/api/endpoints", json=body).json()


def test_every_probe_records_a_result(client, fake_api):
    ep = _add_endpoint(client)
    fake_api["payload"] = {"a": 1}

    for _ in range(3):
        client.post(f"/api/endpoints/{ep['id']}/probe")

    hist = client.get(f"/api/endpoints/{ep['id']}/history").json()
    assert len(hist) == 3
    # Baseline (single-probe in tests) then two OK probes.
    assert [h["status"] for h in hist] == ["ok", "ok", "ok"]
    # Latency is captured on successful probes.
    assert all(h["response_ms"] is not None for h in hist)
    # Chronological order (oldest first) for left-to-right charting.
    assert hist == sorted(hist, key=lambda h: h["id"])


def test_error_probe_is_recorded_with_no_latency(client, fake_api):
    ep = _add_endpoint(client)
    fake_api["error"] = "connection refused"

    client.post(f"/api/endpoints/{ep['id']}/probe")

    hist = client.get(f"/api/endpoints/{ep['id']}/history").json()
    assert len(hist) == 1
    assert hist[0]["status"] == "error"
    assert hist[0]["response_ms"] is None


def test_drift_probe_records_drift_status(client, fake_api):
    ep = _add_endpoint(client)
    fake_api["payload"] = {"price": 12.5}
    client.post(f"/api/endpoints/{ep['id']}/probe")  # baseline
    fake_api["payload"] = {"price": "cheap"}          # type change -> drift
    client.post(f"/api/endpoints/{ep['id']}/probe")

    hist = client.get(f"/api/endpoints/{ep['id']}/history").json()
    assert [h["status"] for h in hist] == ["ok", "drift"]


def test_history_404_for_unknown_endpoint(client):
    assert client.get("/api/endpoints/9999/history").status_code == 404


def test_history_respects_limit(client, fake_api):
    ep = _add_endpoint(client)
    fake_api["payload"] = {"a": 1}
    for _ in range(5):
        client.post(f"/api/endpoints/{ep['id']}/probe")

    hist = client.get(f"/api/endpoints/{ep['id']}/history?limit=2").json()
    assert len(hist) == 2  # the 2 most recent, still oldest-first among them


def test_retention_prunes_old_probe_results(client, fake_api):
    from app.database import SessionLocal
    from app.retention import prune_old_data

    ep = _add_endpoint(client)
    fake_api["payload"] = {"a": 1}
    client.post(f"/api/endpoints/{ep['id']}/probe")

    # Backdate the row well past the retention window.
    db = SessionLocal()
    try:
        row = db.query(ProbeResult).filter_by(endpoint_id=ep["id"]).one()
        row.created_at = utcnow() - timedelta(days=999)
        db.commit()
    finally:
        db.close()

    result = prune_old_data()
    assert result["probe_results"] == 1
    assert client.get(f"/api/endpoints/{ep['id']}/history").json() == []


def test_deleting_endpoint_cascades_probe_results(client, fake_api):
    from app.database import SessionLocal

    ep = _add_endpoint(client)
    fake_api["payload"] = {"a": 1}
    client.post(f"/api/endpoints/{ep['id']}/probe")
    client.delete(f"/api/endpoints/{ep['id']}")

    db = SessionLocal()
    try:
        assert db.query(ProbeResult).filter_by(endpoint_id=ep["id"]).count() == 0
    finally:
        db.close()
