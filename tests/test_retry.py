"""Probe retry/backoff: transient failures retried, deterministic ones not."""
import asyncio

import httpx
import pytest

from app.config import settings
from app.engine import prober
from app.models import Endpoint


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for httpx.AsyncClient; pops one scripted outcome per attempt."""

    script: list = []   # each item: Exception instance or FakeResponse
    calls: int = 0

    def __init__(self, *args, **kwargs): ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, *args, **kwargs):
        FakeClient.calls += 1
        outcome = FakeClient.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture()
def fake_client(monkeypatch):
    monkeypatch.setattr(prober.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(settings, "probe_retries", 2)
    monkeypatch.setattr(settings, "probe_backoff_seconds", 0)
    FakeClient.script = []
    FakeClient.calls = 0
    return FakeClient


def endpoint():
    return Endpoint(name="t", url="https://x.example.com", method="GET", headers={}, body=None)


def test_transient_network_error_is_retried(fake_client):
    fake_client.script = [
        httpx.ConnectError("boom"),
        httpx.ReadTimeout("slow"),
        FakeResponse(200, {"a": 1}),
    ]
    payload, status, _ = asyncio.run(prober._request(endpoint()))
    assert payload == {"a": 1} and status == 200
    assert fake_client.calls == 3


def test_5xx_is_retried(fake_client):
    fake_client.script = [FakeResponse(503), FakeResponse(200, {"up": True})]
    payload, _, _ = asyncio.run(prober._request(endpoint()))
    assert payload == {"up": True}
    assert fake_client.calls == 2


def test_4xx_is_not_retried(fake_client):
    fake_client.script = [FakeResponse(404)]
    with pytest.raises(prober.ProbeError, match="404"):
        asyncio.run(prober._request(endpoint()))
    assert fake_client.calls == 1


def test_exhausted_retries_reports_attempts(fake_client):
    fake_client.script = [httpx.ConnectError("x")] * 3
    with pytest.raises(prober.ProbeError, match=r"after 3 attempt"):
        asyncio.run(prober._request(endpoint()))
    assert fake_client.calls == 3


def test_non_json_is_not_retried(fake_client):
    class HtmlResponse(FakeResponse):
        def json(self):
            raise ValueError("not json")

    fake_client.script = [HtmlResponse(200)]
    with pytest.raises(prober.ProbeError, match="not valid JSON"):
        asyncio.run(prober._request(endpoint()))
    assert fake_client.calls == 1
