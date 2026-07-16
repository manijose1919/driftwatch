"""Integration tests: full probe -> drift -> alert -> accept lifecycle over the REST API."""


def make_endpoint(client, **overrides):
    data = {
        "name": "orders api",
        "url": "https://api.example.com/orders",
        "interval_seconds": 60,
    }
    data.update(overrides)
    resp = client.post("/api/endpoints", json=data)
    assert resp.status_code == 201, resp.text
    return resp.json()


BASELINE_PAYLOAD = {
    "orders": [{"id": 1, "total": 9.99, "status": "open"}],
    "count": 1,
}
BREAKING_PAYLOAD = {
    "orders": [{"id": 1, "total": "9.99", "status": "open"}],  # number -> string
    "count": 1,
}


def test_endpoint_crud(client):
    ep = make_endpoint(client)
    assert ep["last_status"] == "pending"
    assert client.get("/api/endpoints").json()[0]["id"] == ep["id"]

    resp = client.put(f"/api/endpoints/{ep['id']}", json={"name": "renamed"})
    assert resp.json()["name"] == "renamed"

    assert client.delete(f"/api/endpoints/{ep['id']}").status_code == 204
    assert client.get(f"/api/endpoints/{ep['id']}").status_code == 404


def test_endpoint_validation(client):
    resp = client.post("/api/endpoints", json={"name": "bad", "url": "ftp://nope"})
    assert resp.status_code == 422
    ep = make_endpoint(client, interval_seconds=1)  # below floor
    assert ep["interval_seconds"] >= 10


def test_first_probe_captures_baseline(client, fake_api):
    fake_api["payload"] = BASELINE_PAYLOAD
    ep = make_endpoint(client)
    resp = client.post(f"/api/endpoints/{ep['id']}/probe")
    assert resp.json()["last_status"] == "ok"

    snaps = client.get(f"/api/endpoints/{ep['id']}/snapshots").json()
    assert len(snaps) == 1 and snaps[0]["is_baseline"] is True
    assert client.get("/api/events").json() == []


def test_data_change_without_shape_change_is_quiet(client, fake_api):
    fake_api["payload"] = BASELINE_PAYLOAD
    ep = make_endpoint(client)
    client.post(f"/api/endpoints/{ep['id']}/probe")

    fake_api["payload"] = {"orders": [{"id": 77, "total": 1.5, "status": "open"}], "count": 999}
    resp = client.post(f"/api/endpoints/{ep['id']}/probe")
    assert resp.json()["last_status"] == "ok"
    assert client.get("/api/events").json() == []


def test_breaking_drift_creates_event_and_accept_rebaselines(client, fake_api):
    fake_api["payload"] = BASELINE_PAYLOAD
    ep = make_endpoint(client)
    client.post(f"/api/endpoints/{ep['id']}/probe")

    fake_api["payload"] = BREAKING_PAYLOAD
    resp = client.post(f"/api/endpoints/{ep['id']}/probe")
    assert resp.json()["last_status"] == "drift"
    assert resp.json()["open_events"] == 1

    events = client.get("/api/events").json()
    assert len(events) == 1
    event = events[0]
    assert event["severity"] == "breaking"
    assert event["endpoint_name"] == "orders api"
    paths = {c["path"] for c in event["changes"]}
    assert "$.orders[].total" in paths

    # Same drifted shape again: no duplicate event spam.
    client.post(f"/api/endpoints/{ep['id']}/probe")
    assert len(client.get("/api/events").json()) == 1

    # Still the same *structure* but different free-form string data:
    # must also be suppressed (regression: dict-equality suppression failed here).
    fake_api["payload"] = {
        "orders": [{"id": 2, "total": "1.00", "status": "closed"}],
        "count": 1,
    }
    client.post(f"/api/endpoints/{ep['id']}/probe")
    assert len(client.get("/api/events").json()) == 1

    # Accept: new shape becomes the baseline, event closes, status back to ok.
    resp = client.post(f"/api/events/{event['id']}/accept")
    assert resp.json()["acknowledged"] is True
    resp = client.post(f"/api/endpoints/{ep['id']}/probe")
    assert resp.json()["last_status"] == "ok"
    assert resp.json()["open_events"] == 0

    stats = client.get("/api/stats").json()
    assert stats["open_events"] == 0 and stats["probes_ok"] == 1


def test_probe_error_is_edge_triggered(client, fake_api):
    fake_api["error"] = "request failed: boom"
    ep = make_endpoint(client)
    resp = client.post(f"/api/endpoints/{ep['id']}/probe")
    assert resp.json()["last_status"] == "error"
    assert "boom" in resp.json()["last_error"]
    assert len(client.get("/api/events").json()) == 1

    client.post(f"/api/endpoints/{ep['id']}/probe")  # still failing
    assert len(client.get("/api/events").json()) == 1  # no spam

    fake_api["error"] = None
    fake_api["payload"] = BASELINE_PAYLOAD
    resp = client.post(f"/api/endpoints/{ep['id']}/probe")
    assert resp.json()["last_status"] == "ok"


def test_url_change_forces_rebaseline(client, fake_api):
    fake_api["payload"] = BASELINE_PAYLOAD
    ep = make_endpoint(client)
    client.post(f"/api/endpoints/{ep['id']}/probe")

    client.put(f"/api/endpoints/{ep['id']}", json={"url": "https://api.example.com/v2/orders"})
    fake_api["payload"] = BREAKING_PAYLOAD  # totally different shape, but new URL
    resp = client.post(f"/api/endpoints/{ep['id']}/probe")
    assert resp.json()["last_status"] == "ok"  # re-baselined, not drift
    assert client.get("/api/events").json() == []


def test_channels_crud_and_alert_dispatch(client, fake_api, monkeypatch):
    resp = client.post("/api/channels", json={
        "name": "team chat", "kind": "discord",
        "webhook_url": "https://discord.com/api/webhooks/x/y",
        "min_severity": "risky",
    })
    assert resp.status_code == 201
    assert client.get("/api/channels").json()[0]["name"] == "team chat"

    sent = []

    class FakeResponse:
        status_code = 204

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            sent.append((url, json))
            return FakeResponse()

    from app import alerts
    monkeypatch.setattr(alerts.httpx, "AsyncClient", FakeClient)

    fake_api["payload"] = BASELINE_PAYLOAD
    ep = make_endpoint(client)
    client.post(f"/api/endpoints/{ep['id']}/probe")
    assert sent == []  # baseline is not an alert

    fake_api["payload"] = BREAKING_PAYLOAD
    client.post(f"/api/endpoints/{ep['id']}/probe")
    assert len(sent) == 1
    url, body = sent[0]
    assert "discord.com" in url
    assert "BREAKING" in body["content"]
    assert "$.orders[].total" in body["content"]


def test_benign_drift_filtered_by_min_severity(client, fake_api, monkeypatch):
    client.post("/api/channels", json={
        "name": "quiet", "kind": "slack",
        "webhook_url": "https://hooks.slack.com/services/x",
        "min_severity": "breaking",
    })
    sent = []

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            sent.append(url)
            return FakeResponse()

    from app import alerts
    monkeypatch.setattr(alerts.httpx, "AsyncClient", FakeClient)

    fake_api["payload"] = BASELINE_PAYLOAD
    ep = make_endpoint(client)
    client.post(f"/api/endpoints/{ep['id']}/probe")

    benign = {
        "orders": [{"id": 1, "total": 9.99, "status": "open", "note": "hi"}],
        "count": 1,
    }
    fake_api["payload"] = benign
    client.post(f"/api/endpoints/{ep['id']}/probe")
    assert client.get("/api/events").json()[0]["severity"] == "benign"
    assert sent == []  # below channel threshold


def test_api_token_auth(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "api_token", "sekrit")

    assert client.get("/api/endpoints").status_code == 401
    assert client.get(
        "/api/endpoints", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401
    assert client.get(
        "/api/endpoints", headers={"Authorization": "Bearer sekrit"}
    ).status_code == 200
