"""Multi-probe baseline learning: the first N probes merge into the baseline."""
import pytest

from app.config import settings


@pytest.fixture()
def learning(monkeypatch):
    monkeypatch.setattr(settings, "baseline_probes", 3)


def make_endpoint(client):
    resp = client.post("/api/endpoints", json={
        "name": "flappy api",
        "url": "https://api.example.com/flappy",
        "interval_seconds": 60,
    })
    assert resp.status_code == 201
    return resp.json()


def probe(client, ep_id, fake_api, payload):
    fake_api["payload"] = payload
    return client.post(f"/api/endpoints/{ep_id}/probe").json()


def test_learning_status_progression(client, fake_api, learning):
    ep = make_endpoint(client)
    assert probe(client, ep["id"], fake_api, {"a": 1})["last_status"] == "learning"
    assert probe(client, ep["id"], fake_api, {"a": 1})["last_status"] == "learning"
    assert probe(client, ep["id"], fake_api, {"a": 1})["last_status"] == "ok"
    assert client.get("/api/events").json() == []


def test_intermittent_field_learned_as_optional(client, fake_api, learning):
    ep = make_endpoint(client)
    probe(client, ep["id"], fake_api, {"a": 1, "b": "x"})
    probe(client, ep["id"], fake_api, {"a": 1})            # b missing: learned optional
    probe(client, ep["id"], fake_api, {"a": 1, "b": "y"})

    # Armed now. A payload without b must NOT be drift (b is optional).
    result = probe(client, ep["id"], fake_api, {"a": 2})
    assert result["last_status"] == "ok"
    assert client.get("/api/events").json() == []

    # But losing the always-present field IS breaking.
    result = probe(client, ep["id"], fake_api, {"b": "z"})
    assert result["last_status"] == "drift"
    events = client.get("/api/events").json()
    assert events[0]["severity"] == "breaking"
    assert any(c["path"] == "$.a" and c["kind"] == "field_removed" for c in events[0]["changes"])


def test_no_drift_events_during_learning(client, fake_api, learning):
    """Structural changes during learning are absorbed, not alerted."""
    ep = make_endpoint(client)
    probe(client, ep["id"], fake_api, {"a": 1})
    probe(client, ep["id"], fake_api, {"a": "one"})  # type flip mid-learning
    probe(client, ep["id"], fake_api, {"a": 1})
    assert client.get("/api/events").json() == []
    # merged baseline should treat a as mixed type: neither variant drifts
    assert probe(client, ep["id"], fake_api, {"a": "two"})["last_status"] == "ok"
    assert probe(client, ep["id"], fake_api, {"a": 7})["last_status"] == "ok"


def test_accept_reenters_learning(client, fake_api, learning):
    ep = make_endpoint(client)
    for _ in range(3):
        probe(client, ep["id"], fake_api, {"a": 1})

    result = probe(client, ep["id"], fake_api, {"a": 1, "b": True})
    assert result["last_status"] == "drift"
    event = client.get("/api/events").json()[0]
    client.post(f"/api/events/{event['id']}/accept")

    # Accepted baseline has 1 sample: the next probes merge (learning) again.
    assert probe(client, ep["id"], fake_api, {"a": 1, "b": True})["last_status"] == "learning"
    assert probe(client, ep["id"], fake_api, {"a": 1, "b": True})["last_status"] == "ok"


def test_single_probe_baseline_when_learning_disabled(client, fake_api):
    """Default test config: baseline_probes=1 arms immediately."""
    ep = make_endpoint(client)
    assert probe(client, ep["id"], fake_api, {"a": 1})["last_status"] == "ok"
    assert probe(client, ep["id"], fake_api, {"a": "x"})["last_status"] == "drift"
