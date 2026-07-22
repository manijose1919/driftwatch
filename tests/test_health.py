"""The /healthz liveness+readiness probe (unauthenticated, DB-aware)."""


def test_healthz_reports_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["version"]  # non-empty
    # Scheduler is disabled in the test env (see conftest).
    assert body["scheduler"] == "disabled"


def test_healthz_requires_no_token(client, monkeypatch):
    """Health must stay reachable even when the API is token-protected."""
    from app.config import settings

    monkeypatch.setattr(settings, "api_token", "s3cret")
    # /api routes now require the token...
    assert client.get("/api/stats").status_code == 401
    # ...but /healthz does not.
    assert client.get("/healthz").status_code == 200


def test_healthz_503_when_db_unreachable(client, monkeypatch):
    """A failing DB check flips the probe to 503 so orchestrators react."""
    from app.routes import health

    class _BrokenSession:
        def execute(self, *_a, **_k):
            from sqlalchemy.exc import OperationalError

            raise OperationalError("SELECT 1", {}, Exception("no db"))

        def close(self):
            pass

    monkeypatch.setattr(health, "SessionLocal", lambda: _BrokenSession())
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json()["database"] == "unreachable"
